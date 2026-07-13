from __future__ import annotations

from time import monotonic
from typing import Any
import uuid

from django.db import transaction
from django.db.models import Max
from django.utils import timezone

from agent_runtime.models import AgentEvent, AgentRun, ToolInvocation

from .schemas import ResearchPlan
from .generation import generate_research_answer
from .schemas import ContentEvidence
from .tools import build_default_registry
from .workflow import build_research_graph


def normalized_request_id(request_id: str | uuid.UUID | None = None) -> uuid.UUID:
    try:
        return uuid.UUID(str(request_id)) if request_id else uuid.uuid4()
    except (TypeError, ValueError, AttributeError):
        return uuid.uuid4()


def append_event(run: AgentRun, event_type: str, payload: dict[str, Any] | None = None) -> AgentEvent:
    with transaction.atomic():
        locked_run = AgentRun.objects.select_for_update().get(id=run.id)
        last_sequence = locked_run.events.aggregate(value=Max("sequence"))["value"] or 0
        return AgentEvent.objects.create(
            run=locked_run,
            sequence=last_sequence + 1,
            event_type=event_type,
            payload_json=payload or {},
        )


def create_research_run(
    goal: str,
    client_request_id: str,
    request_id: str | uuid.UUID | None = None,
) -> tuple[AgentRun, bool]:
    normalized_id = (client_request_id or "").strip()[:120]
    if not normalized_id:
        raise ValueError("client_request_id is required")
    run_request_id = normalized_request_id(request_id)
    with transaction.atomic():
        run, created = AgentRun.objects.get_or_create(
            client_request_id=normalized_id,
            defaults={
                "kind": AgentRun.Kind.RAG,
                "goal": (goal or "").strip()[:1000],
                "trigger": "research_api",
                "status": AgentRun.Status.QUEUED,
                "request_id": run_request_id,
            },
        )
        if created:
            append_event(run, "run.created", {"status": AgentRun.Status.QUEUED})
    return run, created


def replay_research_run(
    source: AgentRun,
    request_id: str | uuid.UUID | None = None,
) -> AgentRun:
    run_request_id = normalized_request_id(request_id)
    with transaction.atomic():
        replay = AgentRun.objects.create(
            kind=source.kind,
            client_request_id=f"replay-{uuid.uuid4()}",
            goal=source.goal,
            trigger="research_replay",
            status=AgentRun.Status.QUEUED,
            request_id=run_request_id,
            graph_version=source.graph_version,
            prompt_version=source.prompt_version,
            replay_of=source,
        )
        append_event(
            replay,
            "run.replayed",
            {"source_run_id": str(source.public_id), "status": AgentRun.Status.QUEUED},
        )
    return replay


def cancel_research_run(run: AgentRun) -> bool:
    terminal = {AgentRun.Status.SUCCEEDED, AgentRun.Status.FAILED, AgentRun.Status.CANCELLED}
    with transaction.atomic():
        locked_run = AgentRun.objects.select_for_update().get(id=run.id)
        if locked_run.status in terminal:
            return False
        locked_run.status = AgentRun.Status.CANCELLED
        locked_run.finished_at = timezone.now()
        locked_run.save(update_fields=["status", "finished_at", "updated_at"])
        append_event(locked_run, "run.cancelled", {"status": AgentRun.Status.CANCELLED})
    return True


def execute_research_run(run_id: int) -> dict[str, Any]:
    run = AgentRun.objects.get(id=run_id)
    if run.status == AgentRun.Status.CANCELLED:
        return {"status": "cancelled"}
    registry = build_default_registry()
    try:
        run.status = AgentRun.Status.PLANNING
        run.current_node = "plan"
        run.save(update_fields=["status", "current_node", "updated_at"])
        def answer_builder(_state, items, _outputs):
            evidence = [ContentEvidence.model_validate(item) for item in items]
            return generate_research_answer(
                run.goal,
                evidence,
                on_delta=lambda text: append_event(run, "answer.delta", {"text": text}),
            )

        def plan_observer(plan: ResearchPlan) -> None:
            append_event(run, "plan.created", {"task_type": plan.task_type, "step_count": len(plan.steps)})

        def tool_event_observer(step, spec, event: dict[str, Any]) -> None:
            attempt = int(event["attempt"])
            defaults = {
                "tool_name": step.tool,
                "tool_version": spec.version,
                "risk_level": spec.risk_level,
                "permission": spec.permission,
                "input_json": step.args,
                "idempotency_key": f"{run.public_id}:{step.id}:{attempt}",
            }
            invocation, _ = ToolInvocation.objects.get_or_create(
                run=run,
                step_id=step.id,
                attempt=attempt,
                defaults={**defaults, "status": ToolInvocation.Status.RUNNING},
            )
            event_type = event["event"]
            if event_type == "completed":
                invocation.status = ToolInvocation.Status.SUCCEEDED
                invocation.output_json = event.get("output", {})
                invocation.duration_ms = int(event.get("duration_ms", 0))
                invocation.error_type = ""
                invocation.error_message = ""
                invocation.save(update_fields=["status", "output_json", "duration_ms", "error_type", "error_message", "updated_at"])
                append_event(run, "tool.completed", {"step_id": step.id, "tool": step.tool, "attempt": attempt})
            elif event_type == "retrying":
                invocation.status = ToolInvocation.Status.FAILED
                invocation.duration_ms = int(event.get("duration_ms", 0))
                invocation.error_type = event.get("error_type", "execution")
                invocation.save(update_fields=["status", "duration_ms", "error_type", "updated_at"])
                append_event(run, "tool.retrying", {"step_id": step.id, "tool": step.tool, "attempt": attempt})
            elif event_type == "failed":
                invocation.status = ToolInvocation.Status.FAILED
                invocation.duration_ms = int(event.get("duration_ms", 0))
                invocation.error_type = event.get("error_type", "execution")
                invocation.error_message = event.get("message", "")[:2000]
                invocation.save(update_fields=["status", "duration_ms", "error_type", "error_message", "updated_at"])
                append_event(run, "tool.failed", {"step_id": step.id, "tool": step.tool, "attempt": attempt, "error_type": invocation.error_type})
            elif event_type == "started":
                append_event(run, "tool.started", {"step_id": step.id, "tool": step.tool, "attempt": attempt})

        result = build_research_graph(
            registry,
            answer_builder=answer_builder,
            plan_observer=plan_observer,
            tool_event_observer=tool_event_observer,
        ).invoke(
            {"goal": run.goal, "actor_is_staff": False}
        )
        plan = ResearchPlan.model_validate(result["plan"])

        verification = result["verification"]
        append_event(
            run,
            "verification.passed" if verification["passed"] else "verification.failed",
            verification,
        )
        run.state_json = result
        run.current_node = "finalize"
        run.status = AgentRun.Status.SUCCEEDED if result["status"] == "succeeded" else AgentRun.Status.FAILED
        run.finished_at = timezone.now()
        run.metrics_json = {
            "tool_calls": len(plan.steps),
            "citations": len(result.get("answer", {}).get("citations", [])),
            "verified": bool(verification["passed"]),
            "replans": int(result.get("replan_count", 0)),
        }
        run.save(
            update_fields=[
                "state_json",
                "current_node",
                "status",
                "finished_at",
                "metrics_json",
                "updated_at",
            ]
        )
        append_event(run, "run.completed", {"status": run.status})
        return result
    except Exception as exc:
        run.status = AgentRun.Status.FAILED
        run.finished_at = timezone.now()
        run.error_message = str(exc)[:2000]
        run.save(update_fields=["status", "finished_at", "error_message", "updated_at"])
        append_event(run, "run.failed", {"message": "research execution failed"})
        raise
