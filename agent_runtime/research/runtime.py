from __future__ import annotations

from time import monotonic
from typing import Any

from django.db import transaction
from django.db.models import Max
from django.utils import timezone

from agent_runtime.models import AgentEvent, AgentRun, ToolInvocation

from .schemas import ResearchPlan
from .tools import build_default_registry
from .workflow import build_research_graph


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


def create_research_run(goal: str, client_request_id: str) -> tuple[AgentRun, bool]:
    normalized_id = (client_request_id or "").strip()[:120]
    if not normalized_id:
        raise ValueError("client_request_id is required")
    with transaction.atomic():
        run, created = AgentRun.objects.get_or_create(
            client_request_id=normalized_id,
            defaults={
                "kind": AgentRun.Kind.RAG,
                "goal": (goal or "").strip()[:1000],
                "trigger": "research_api",
                "status": AgentRun.Status.QUEUED,
            },
        )
        if created:
            append_event(run, "run.created", {"status": AgentRun.Status.QUEUED})
    return run, created


def execute_research_run(run_id: int) -> dict[str, Any]:
    run = AgentRun.objects.get(id=run_id)
    registry = build_default_registry()
    try:
        run.status = AgentRun.Status.PLANNING
        run.current_node = "plan"
        run.save(update_fields=["status", "current_node", "updated_at"])
        result = build_research_graph(registry).invoke(
            {"goal": run.goal, "actor_is_staff": False}
        )
        plan = ResearchPlan.model_validate(result["plan"])
        append_event(run, "plan.created", {"task_type": plan.task_type, "step_count": len(plan.steps)})

        outputs = result.get("tool_outputs", {})
        for step in plan.steps:
            started = monotonic()
            spec = registry.get(step.tool)
            ToolInvocation.objects.update_or_create(
                run=run,
                step_id=step.id,
                defaults={
                    "tool_name": step.tool,
                    "tool_version": spec.version,
                    "risk_level": spec.risk_level,
                    "permission": spec.permission,
                    "status": ToolInvocation.Status.SUCCEEDED,
                    "input_json": step.args,
                    "output_json": outputs.get(step.id, {}),
                    "duration_ms": max(0, int((monotonic() - started) * 1000)),
                    "idempotency_key": f"{run.public_id}:{step.id}",
                },
            )
            append_event(run, "tool.completed", {"step_id": step.id, "tool": step.tool})

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
