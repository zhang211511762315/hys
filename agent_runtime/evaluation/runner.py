from __future__ import annotations

from collections import Counter
from decimal import Decimal, InvalidOperation
import json
from math import ceil
from pathlib import Path
from time import perf_counter
from typing import Any

from django.conf import settings
from pydantic import BaseModel, Field

from agent_runtime.research.planner import PUBLIC_TOOLS, build_template_plan


DATASET_DIRECTORY = Path(__file__).parent / "datasets"
DATASET_PATH = DATASET_DIRECTORY / "campus_research_v1.json"
V2_DATASET_PATH = DATASET_DIRECTORY / "campus_research_v2.json"
RETRIEVAL_FIXTURE_PATH = Path(__file__).parent / "datasets" / "campus_retrieval_v1.json"
OFFLINE_MODE = "offline"
PAID_MODE = "paid"
DEFAULT_STRATEGY = "single_agent"
ABSOLUTE_PAID_HARD_CAP_CNY = Decimal("5")


class ResearchEvalCase(BaseModel):
    id: str
    category: str
    goal: str
    expected_task_type: str
    expected_tools: list[str] = Field(min_length=1)


class EvaluationDataset(BaseModel):
    version: str
    metadata: dict[str, Any] = Field(default_factory=dict)
    cases: list[ResearchEvalCase] = Field(default_factory=list)


def load_evaluation_dataset(dataset: str | Path = V2_DATASET_PATH) -> EvaluationDataset:
    path = _resolve_dataset_path(dataset)
    payload = json.loads(path.read_text(encoding="utf-8"))
    cases = _load_dataset_cases(payload)
    return EvaluationDataset(
        version=payload["version"],
        metadata=payload.get("metadata", {}),
        cases=cases,
    )


def load_research_dataset(path: Path = DATASET_PATH) -> list[ResearchEvalCase]:
    """Load the original v1 dataset for backwards-compatible offline checks."""
    return load_evaluation_dataset(path).cases


def _resolve_dataset_path(dataset: str | Path) -> Path:
    if isinstance(dataset, Path):
        return dataset
    name = str(dataset).strip()
    if name in {"campus-research-v1", "v1"}:
        return DATASET_PATH
    if name in {"campus-research-v2", "v2"}:
        return V2_DATASET_PATH
    candidate = Path(name)
    if candidate.suffix == ".json":
        return candidate
    return DATASET_DIRECTORY / f"{name}.json"


def _load_dataset_cases(payload: dict[str, Any]) -> list[ResearchEvalCase]:
    if "cases" in payload:
        return [ResearchEvalCase.model_validate(case) for case in payload["cases"]]

    cases = []
    sequence = 1
    for group in payload["groups"]:
        for variant in group["variants"]:
            for topic in variant["topics"]:
                cases.append(
                    ResearchEvalCase(
                        id=f"case-{sequence:03d}",
                        category=group["category"],
                        goal=variant["template"].format(topic=topic),
                        expected_task_type=variant["expected_task_type"],
                        expected_tools=variant["expected_tools"],
                    )
                )
                sequence += 1
    return cases


def run_evaluation(
    dataset: str | Path = V2_DATASET_PATH,
    *,
    strategy: str = DEFAULT_STRATEGY,
    mode: str = OFFLINE_MODE,
    budget_cap_cny: Decimal | int | float | str | None = None,
    record: bool = False,
) -> dict[str, Any]:
    """Run a deterministic planner evaluation, optionally recording durable snapshots."""
    normalized_mode, budget_cap = _validate_evaluation_options(mode, budget_cap_cny)
    if strategy != DEFAULT_STRATEGY:
        raise ValueError(f"unsupported evaluation strategy: {strategy}")

    evaluation_dataset = load_evaluation_dataset(dataset)
    cases = evaluation_dataset.cases
    evaluation_run = None
    agent_run = None
    EvaluationCaseResult = None
    if record:
        from agent_runtime.models import AgentRun, EvaluationCaseResult, EvaluationRun

        agent_run = AgentRun.objects.create(
            kind=AgentRun.Kind.EVAL,
            trigger=f"evaluation:{evaluation_dataset.version}:{strategy}",
            status=AgentRun.Status.RUNNING,
        )
        evaluation_run = EvaluationRun.objects.create(
            agent_run=agent_run,
            dataset_version=evaluation_dataset.version,
            strategy=strategy,
            mode=normalized_mode,
            budget_cap_cny=budget_cap,
            status=EvaluationRun.Status.RUNNING,
        )

    valid = 0
    selected_correctly = 0
    unsafe_count = 0
    failures: list[dict[str, Any]] = []
    latencies: list[int] = []
    total_cost = Decimal("0")

    try:
        for case in cases:
            started = perf_counter()
            actual_task_type = ""
            actual_tools: list[str] = []
            plan_valid = False
            selection_correct = False
            unsafe_tools: list[str] = []
            error_message = ""
            try:
                plan = build_template_plan(case.goal)
                actual_task_type = plan.task_type
                actual_tools = [step.tool for step in plan.steps]
                unsafe_tools = [tool for tool in actual_tools if tool not in PUBLIC_TOOLS]
                plan_valid = 1 <= len(plan.steps) <= 6 and not unsafe_tools
                selection_correct = (
                    actual_task_type == case.expected_task_type and actual_tools == case.expected_tools
                )
            except Exception as exc:
                error_message = str(exc)

            latency_ms = max(0, round((perf_counter() - started) * 1000))
            latencies.append(latency_ms)
            valid += int(plan_valid)
            selected_correctly += int(selection_correct)
            unsafe_count += len(unsafe_tools)
            case_status = "succeeded" if plan_valid and selection_correct and not unsafe_tools else "failed"
            detail = {
                "plan_valid": plan_valid,
                "tool_selection_correct": selection_correct,
                "unsafe_tools": unsafe_tools,
                "plan_step_count": len(actual_tools),
            }
            if error_message:
                detail["error"] = error_message

            if case_status == "failed":
                failure = {
                    "id": case.id,
                    "expected_task_type": case.expected_task_type,
                    "actual_task_type": actual_task_type,
                    "expected_tools": case.expected_tools,
                    "actual_tools": actual_tools,
                }
                if error_message:
                    failure["error"] = error_message
                failures.append(failure)

            if evaluation_run is not None and EvaluationCaseResult is not None:
                EvaluationCaseResult.objects.create(
                    evaluation_run=evaluation_run,
                    case_id=case.id,
                    category=case.category,
                    goal=case.goal,
                    expected_task_type=case.expected_task_type,
                    expected_tools=list(case.expected_tools),
                    actual_task_type=actual_task_type,
                    actual_tools=actual_tools,
                    status=case_status,
                    latency_ms=latency_ms,
                    cost_cny=Decimal("0"),
                    detail_json=detail,
                )

        total = len(cases)
        metrics = {
            "case_count": total,
            "category_counts": dict(Counter(case.category for case in cases)),
            "plan_valid_rate": round(valid / total, 4) if total else 0,
            "tool_selection_accuracy": round(selected_correctly / total, 4) if total else 0,
            "unsafe_tool_selection_count": unsafe_count,
            "total_latency_ms": sum(latencies),
            "average_latency_ms": round(sum(latencies) / total, 2) if total else 0,
            "p50_latency_ms": _percentile(latencies, 0.50),
            "p95_latency_ms": _percentile(latencies, 0.95),
            "total_cost_cny": str(total_cost),
        }
        if evaluation_run is not None and agent_run is not None:
            from django.utils import timezone

            evaluation_run.status = "succeeded"
            evaluation_run.metrics_json = metrics
            evaluation_run.finished_at = timezone.now()
            evaluation_run.save(
                update_fields=["status", "metrics_json", "finished_at", "updated_at"]
            )
            agent_run.total_cost_cny = total_cost
            agent_run.save(update_fields=["total_cost_cny", "updated_at"])
            agent_run.finish(agent_run.Status.SUCCEEDED, metrics=metrics)

        return {
            "dataset_version": evaluation_dataset.version,
            "strategy": strategy,
            "mode": normalized_mode,
            "budget_cap_cny": str(budget_cap),
            "evaluation_run_id": evaluation_run.pk if evaluation_run is not None else None,
            **metrics,
            "failures": failures,
        }
    except Exception as exc:
        if evaluation_run is not None and agent_run is not None:
            from django.utils import timezone

            evaluation_run.status = "failed"
            evaluation_run.error_message = str(exc)[:2000]
            evaluation_run.finished_at = timezone.now()
            evaluation_run.save(
                update_fields=["status", "error_message", "finished_at", "updated_at"]
            )
            agent_run.finish(agent_run.Status.FAILED, error_message=str(exc))
        raise


def run_planner_evaluation(path: Path = DATASET_PATH) -> dict[str, Any]:
    """Keep the original v1 planner function as a zero-cost, non-recording wrapper."""
    return run_evaluation(path, record=False)


def _validate_evaluation_options(
    mode: str,
    requested_budget_cap: Decimal | int | float | str | None,
) -> tuple[str, Decimal]:
    normalized_mode = (mode or "").strip().lower()
    if normalized_mode not in {OFFLINE_MODE, PAID_MODE}:
        raise ValueError(f"unsupported evaluation mode: {mode}")

    hard_cap = min(
        ABSOLUTE_PAID_HARD_CAP_CNY,
        _decimal_setting("EVAL_PAID_HARD_CAP_CNY", ABSOLUTE_PAID_HARD_CAP_CNY),
    )
    default_cap = Decimal("0") if normalized_mode == OFFLINE_MODE else hard_cap
    budget_cap = _to_decimal(requested_budget_cap, default_cap)
    if budget_cap < 0:
        raise ValueError("evaluation budget cap cannot be negative")
    if budget_cap > hard_cap:
        raise ValueError(f"evaluation budget cap cannot exceed {hard_cap} CNY")
    if normalized_mode == PAID_MODE and not getattr(settings, "EVAL_PAID_ENABLED", False):
        raise ValueError("paid evaluation mode is disabled")
    return normalized_mode, budget_cap


def _decimal_setting(name: str, default: Decimal) -> Decimal:
    return _to_decimal(getattr(settings, name, default), default)


def _to_decimal(value: Decimal | int | float | str | None, default: Decimal) -> Decimal:
    if value is None:
        return default
    try:
        result = Decimal(str(value))
    except (InvalidOperation, ValueError) as exc:
        raise ValueError("evaluation budget cap must be a decimal value") from exc
    if not result.is_finite():
        raise ValueError("evaluation budget cap must be finite")
    return result


def _percentile(values: list[int], percentile: float) -> int:
    if not values:
        return 0
    index = max(0, ceil(len(values) * percentile) - 1)
    return sorted(values)[index]


def load_retrieval_fixture(path: Path = RETRIEVAL_FIXTURE_PATH) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))


def run_retrieval_evaluation(queries: list[dict], gold_ids: dict[str, int], registry) -> dict:
    hits = 0
    reciprocal_rank = 0.0
    failures = []
    from agent_runtime.research.tools import ToolContext

    for case in queries:
        result = registry.execute(
            "search_public_content",
            {"query": case["query"], "limit": 5},
            ToolContext(actor_is_staff=False, run_id="offline-eval"),
        )
        item_ids = result["item_ids"]
        gold_id = gold_ids[case["gold_key"]]
        if gold_id in item_ids:
            hits += 1
            reciprocal_rank += 1 / (item_ids.index(gold_id) + 1)
        else:
            failures.append({"id": case["id"], "query": case["query"], "returned_ids": item_ids})
    total = len(queries)
    return {
        "dataset_version": "campus-retrieval-v1",
        "case_count": total,
        "recall_at_5": round(hits / total, 4) if total else 0,
        "mrr": round(reciprocal_rank / total, 4) if total else 0,
        "failures": failures,
    }
