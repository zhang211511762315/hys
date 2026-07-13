"""Deterministic, offline-only strategies used by controlled EvalOps runs."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Callable

from agent_runtime.research.planner import PUBLIC_TOOLS, build_template_plan


SINGLE_AGENT = "single_agent"
MULTI_AGENT_EXPERIMENTAL = "multi_agent_experimental"
SUPPORTED_EVALUATION_STRATEGIES = frozenset({SINGLE_AGENT, MULTI_AGENT_EXPERIMENTAL})


@dataclass(frozen=True)
class EvaluationStrategyResult:
    actual_task_type: str
    actual_tools: list[str]
    unsafe_tools: list[str]
    plan_valid: bool
    tool_selection_correct: bool
    stage_trace: list[dict[str, Any]]


def run_evaluation_strategy(
    strategy: str,
    *,
    goal: str,
    expected_task_type: str,
    expected_tools: list[str],
    plan_builder: Callable[[str], Any] = build_template_plan,
) -> EvaluationStrategyResult:
    """Plan and audit one case without invoking any tool or external service."""
    if strategy not in SUPPORTED_EVALUATION_STRATEGIES:
        raise ValueError(f"unsupported evaluation strategy: {strategy}")

    plan = plan_builder(goal)
    actual_tools = [step.tool for step in plan.steps]
    unsafe_tools = [tool for tool in actual_tools if tool not in PUBLIC_TOOLS]
    plan_valid = 1 <= len(actual_tools) <= 6 and not unsafe_tools
    tool_selection_correct = (
        plan.task_type == expected_task_type and actual_tools == expected_tools
    )
    planner_stage = {
        "stage": "planner",
        "offline": True,
        "plan_step_count": len(actual_tools),
    }

    if strategy == SINGLE_AGENT:
        return EvaluationStrategyResult(
            actual_task_type=plan.task_type,
            actual_tools=actual_tools,
            unsafe_tools=unsafe_tools,
            plan_valid=plan_valid,
            tool_selection_correct=tool_selection_correct,
            stage_trace=[planner_stage],
        )

    evidence_audit_stage = {
        "stage": "researcher_evidence_audit",
        "offline": True,
        "executed_tools": [],
        "audited_step_ids": [step.id for step in plan.steps],
    }
    reviewer_stage = {
        "stage": "reviewer_safety_expectation_check",
        "offline": True,
        "unsafe_tools": unsafe_tools,
        "plan_valid": plan_valid,
        "tool_selection_correct": tool_selection_correct,
    }
    return EvaluationStrategyResult(
        actual_task_type=plan.task_type,
        actual_tools=actual_tools,
        unsafe_tools=unsafe_tools,
        plan_valid=plan_valid,
        tool_selection_correct=tool_selection_correct,
        stage_trace=[planner_stage, evidence_audit_stage, reviewer_stage],
    )
