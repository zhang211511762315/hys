from __future__ import annotations

from collections import Counter
from decimal import Decimal, InvalidOperation
import json
from math import ceil, isfinite
from pathlib import Path
from time import perf_counter
from typing import Any
import uuid

from django.conf import settings
from pydantic import BaseModel, Field

from agent_runtime.evaluation.strategies import (
    MULTI_AGENT_EXPERIMENTAL,
    SINGLE_AGENT,
    SUPPORTED_EVALUATION_STRATEGIES,
    run_evaluation_strategy,
)
from agent_runtime.research.planner import build_template_plan


DATASET_DIRECTORY = Path(__file__).parent / "datasets"
DATASET_PATH = DATASET_DIRECTORY / "campus_research_v1.json"
V2_DATASET_PATH = DATASET_DIRECTORY / "campus_research_v2.json"
RETRIEVAL_FIXTURE_PATH = Path(__file__).parent / "datasets" / "campus_retrieval_v1.json"
OFFLINE_MODE = "offline"
PAID_MODE = "paid"
DEFAULT_STRATEGY = "single_agent"
ABSOLUTE_PAID_HARD_CAP_CNY = Decimal("5")
DEFAULT_PROMOTION_P95_LATENCY_MULTIPLIER = 2.0

_REQUIRED_PROMOTION_METRICS = (
    "case_count",
    "plan_valid_count",
    "tool_selection_correct_count",
    "unsafe_tool_selection_count",
    "total_cost_cny",
    "p95_latency_ms",
    "plan_valid_rate",
    "tool_selection_accuracy",
)


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
    comparison_id: uuid.UUID | str | None = None,
) -> dict[str, Any]:
    """Run a deterministic planner evaluation, optionally recording durable snapshots."""
    normalized_mode, budget_cap = _validate_evaluation_options(mode, budget_cap_cny)
    if strategy not in SUPPORTED_EVALUATION_STRATEGIES:
        raise ValueError(f"unsupported evaluation strategy: {strategy}")
    if normalized_mode != OFFLINE_MODE:
        raise ValueError("evaluation strategies are offline only")
    normalized_comparison_id = _normalize_comparison_id(comparison_id)

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
            comparison_id=normalized_comparison_id,
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
                strategy_result = run_evaluation_strategy(
                    strategy,
                    goal=case.goal,
                    expected_task_type=case.expected_task_type,
                    expected_tools=case.expected_tools,
                    plan_builder=build_template_plan,
                )
                actual_task_type = strategy_result.actual_task_type
                actual_tools = strategy_result.actual_tools
                unsafe_tools = strategy_result.unsafe_tools
                plan_valid = strategy_result.plan_valid
                selection_correct = strategy_result.tool_selection_correct
                stage_trace = strategy_result.stage_trace
            except Exception as exc:
                error_message = str(exc)
                stage_trace = []

            latency_ms = max(1, ceil((perf_counter() - started) * 1000))
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
                "stage_trace": stage_trace,
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
            "plan_valid_count": valid,
            "tool_selection_correct_count": selected_correctly,
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
            "comparison_id": str(normalized_comparison_id) if normalized_comparison_id else None,
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


def run_strategy_comparison(
    dataset: str | Path = V2_DATASET_PATH,
    *,
    mode: str = OFFLINE_MODE,
    budget_cap_cny: Decimal | int | float | str | None = None,
) -> dict[str, Any]:
    """Run the offline baseline and experimental strategy as one durable comparison."""
    comparison_id = uuid.uuid4()
    baseline = run_evaluation(
        dataset,
        strategy=SINGLE_AGENT,
        mode=mode,
        budget_cap_cny=budget_cap_cny,
        record=True,
        comparison_id=comparison_id,
    )
    candidate = run_evaluation(
        dataset,
        strategy=MULTI_AGENT_EXPERIMENTAL,
        mode=mode,
        budget_cap_cny=budget_cap_cny,
        record=True,
        comparison_id=comparison_id,
    )
    promotion = evaluate_promotion_gate(baseline, candidate)
    return {
        "comparison_id": str(comparison_id),
        "dataset_version": baseline["dataset_version"],
        "mode": baseline["mode"],
        "baseline": baseline,
        "candidate": candidate,
        "promotion": promotion,
        "promotion_status": promotion["status"],
    }


def evaluate_promotion_gate(
    baseline_metrics: dict[str, Any],
    candidate_metrics: dict[str, Any],
) -> dict[str, Any]:
    """Return the deterministic safety gate for an experimental evaluation result."""
    reasons: list[str] = []
    baseline = _validated_promotion_metrics(baseline_metrics)
    candidate = _validated_promotion_metrics(candidate_metrics)
    if baseline is None:
        reasons.append("invalid_baseline_metrics")
    if candidate is None:
        reasons.append("invalid_candidate_metrics")

    multiplier = _promotion_p95_latency_multiplier()
    if multiplier is None:
        reasons.append("invalid_p95_latency_multiplier")

    p95_latency_limit_ms = None
    if baseline is not None and multiplier is not None:
        calculated_limit = baseline["p95_latency_ms"] * multiplier
        if isfinite(calculated_limit):
            p95_latency_limit_ms = calculated_limit
        else:
            reasons.append("invalid_p95_latency_limit")

    if baseline is None or candidate is None or p95_latency_limit_ms is None:
        return {
            "status": "blocked",
            "eligible": False,
            "reasons": reasons,
            "p95_latency_limit_ms": p95_latency_limit_ms,
        }

    if candidate["case_count"] != baseline["case_count"]:
        reasons.append("case_count_mismatch")
    if candidate["unsafe_tool_selection_count"] > 0:
        reasons.append("unsafe_tool_selection")
    if candidate["plan_valid_count"] < baseline["plan_valid_count"]:
        reasons.append("plan_valid_count_regression")
    if candidate["tool_selection_correct_count"] < baseline["tool_selection_correct_count"]:
        reasons.append("tool_selection_correct_count_regression")
    if candidate["total_cost_cny"] > ABSOLUTE_PAID_HARD_CAP_CNY:
        reasons.append("cost_cap_exceeded")
    if candidate["p95_latency_ms"] > p95_latency_limit_ms:
        reasons.append("p95_latency_regression")

    eligible = not reasons
    return {
        "status": "candidate" if eligible else "blocked",
        "eligible": eligible,
        "reasons": reasons,
        "p95_latency_limit_ms": p95_latency_limit_ms,
    }


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


def _normalize_comparison_id(value: uuid.UUID | str | None) -> uuid.UUID | None:
    if value is None:
        return None
    if isinstance(value, uuid.UUID):
        return value
    try:
        return uuid.UUID(str(value))
    except (AttributeError, TypeError, ValueError) as exc:
        raise ValueError("comparison_id must be a UUID") from exc


def _validated_promotion_metrics(metrics: Any) -> dict[str, Any] | None:
    """Validate persisted comparison metrics without supplying permissive defaults."""
    if not isinstance(metrics, dict) or any(key not in metrics for key in _REQUIRED_PROMOTION_METRICS):
        return None

    case_count = _promotion_count(metrics["case_count"])
    plan_valid_count = _promotion_count(metrics["plan_valid_count"])
    tool_selection_correct_count = _promotion_count(metrics["tool_selection_correct_count"])
    unsafe_tool_selection_count = _promotion_count(metrics["unsafe_tool_selection_count"])
    total_cost_cny = _promotion_decimal(metrics["total_cost_cny"])
    p95_latency_ms = _promotion_number(metrics["p95_latency_ms"])
    plan_valid_rate = _promotion_number(metrics["plan_valid_rate"])
    tool_selection_accuracy = _promotion_number(metrics["tool_selection_accuracy"])

    if (
        case_count is None
        or case_count <= 0
        or plan_valid_count is None
        or tool_selection_correct_count is None
        or unsafe_tool_selection_count is None
        or total_cost_cny is None
        or p95_latency_ms is None
        or plan_valid_rate is None
        or tool_selection_accuracy is None
    ):
        return None
    if plan_valid_count > case_count or tool_selection_correct_count > case_count:
        return None
    if total_cost_cny < 0 or p95_latency_ms < 0:
        return None
    if not 0 <= plan_valid_rate <= 1 or not 0 <= tool_selection_accuracy <= 1:
        return None
    if not _rate_matches_count(plan_valid_rate, plan_valid_count, case_count):
        return None
    if not _rate_matches_count(tool_selection_accuracy, tool_selection_correct_count, case_count):
        return None

    return {
        "case_count": case_count,
        "plan_valid_count": plan_valid_count,
        "tool_selection_correct_count": tool_selection_correct_count,
        "unsafe_tool_selection_count": unsafe_tool_selection_count,
        "total_cost_cny": total_cost_cny,
        "p95_latency_ms": p95_latency_ms,
        "plan_valid_rate": plan_valid_rate,
        "tool_selection_accuracy": tool_selection_accuracy,
    }


def _promotion_count(value: Any) -> int | None:
    if isinstance(value, bool) or not isinstance(value, int):
        return None
    return value if value >= 0 else None


def _promotion_number(value: Any) -> float | None:
    if isinstance(value, bool) or not isinstance(value, (int, float, Decimal)):
        return None
    try:
        number = float(value)
    except (OverflowError, ValueError):
        return None
    return number if isfinite(number) else None


def _promotion_decimal(value: Any) -> Decimal | None:
    if isinstance(value, bool):
        return None
    try:
        result = Decimal(str(value))
    except (InvalidOperation, ValueError):
        return None
    return result if result.is_finite() else None


def _rate_matches_count(rate: float, count: int, case_count: int) -> bool:
    return abs(rate - round(count / case_count, 4)) <= 1e-12


def _promotion_p95_latency_multiplier() -> float | None:
    value = getattr(
        settings,
        "EVAL_PROMOTION_P95_LATENCY_MULTIPLIER",
        DEFAULT_PROMOTION_P95_LATENCY_MULTIPLIER,
    )
    if isinstance(value, bool):
        return None
    try:
        multiplier = float(value)
    except (TypeError, ValueError, OverflowError):
        return None
    return multiplier if isfinite(multiplier) and multiplier > 0 else None


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
