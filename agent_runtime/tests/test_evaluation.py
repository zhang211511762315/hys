from decimal import Decimal
import json
from io import StringIO
from types import SimpleNamespace

import pytest
from django.core.management import call_command
from django.test import override_settings

from agent_runtime.evaluation.runner import load_evaluation_dataset


def test_campus_research_v2_has_engineering_reviewed_200_case_baseline():
    dataset = load_evaluation_dataset("campus-research-v2")

    assert dataset.version == "campus-research-v2"
    assert dataset.metadata["review_status"] == "engineering-reviewed-baseline"
    assert len(dataset.cases) == 200
    assert {case.category for case in dataset.cases} == {
        "normal",
        "multi_step",
        "ambiguous",
        "no_answer",
        "tool_failure",
        "security",
        "multi_constraint",
    }


def test_campus_research_v2_is_a_deterministic_valid_safe_planner_baseline():
    from agent_runtime.evaluation.runner import run_evaluation

    report = run_evaluation("campus-research-v2")

    assert report["plan_valid_rate"] == 1.0
    assert report["tool_selection_accuracy"] == 1.0
    assert report["unsafe_tool_selection_count"] == 0
    assert report["failures"] == []


@pytest.mark.django_db
def test_recorded_v2_run_persists_evaluation_and_case_result_snapshots():
    from agent_runtime.evaluation.runner import run_evaluation
    from agent_runtime.models import AgentRun, EvaluationRun

    report = run_evaluation(record=True)

    evaluation_run = EvaluationRun.objects.get(pk=report["evaluation_run_id"])
    assert evaluation_run.agent_run.kind == AgentRun.Kind.EVAL
    assert evaluation_run.dataset_version == "campus-research-v2"
    assert evaluation_run.strategy == "single_agent"
    assert evaluation_run.mode == "offline"
    assert evaluation_run.budget_cap_cny == Decimal("0")
    assert evaluation_run.status == EvaluationRun.Status.SUCCEEDED
    assert evaluation_run.case_results.count() == 200

    first_result = evaluation_run.case_results.order_by("case_id").first()
    assert first_result.expected_task_type
    assert first_result.expected_tools
    assert first_result.actual_task_type
    assert first_result.actual_tools
    assert first_result.latency_ms >= 0
    assert first_result.cost_cny == Decimal("0")
    assert first_result.detail_json["plan_valid"] is True


def test_paid_mode_is_disabled_and_over_cap_requests_do_not_execute_cases(monkeypatch):
    from django.conf import settings

    from agent_runtime.evaluation import runner

    planned_goals = []

    def record_planning(goal):
        planned_goals.append(goal)
        raise AssertionError("a rejected evaluation must not execute a case")

    monkeypatch.setattr(runner, "build_template_plan", record_planning)

    assert settings.EVAL_PAID_ENABLED is False
    assert settings.EVAL_PAID_HARD_CAP_CNY == 5
    with pytest.raises(ValueError, match="paid evaluation mode is disabled"):
        runner.run_evaluation(mode="paid")
    with pytest.raises(ValueError, match="cannot exceed 5"):
        runner.run_evaluation(budget_cap_cny="5.000001")

    assert planned_goals == []


@override_settings(EVAL_PAID_ENABLED=True, EVAL_PAID_HARD_CAP_CNY=6)
def test_paid_cap_has_an_absolute_five_cny_ceiling_even_when_configured_higher(monkeypatch):
    from agent_runtime.evaluation import runner

    planned_goals = []

    def record_planning(goal):
        planned_goals.append(goal)
        raise AssertionError("an over-cap evaluation must not execute a case")

    monkeypatch.setattr(runner, "build_template_plan", record_planning)

    assert runner._validate_evaluation_options("paid", None) == ("paid", Decimal("5"))
    with pytest.raises(ValueError, match="cannot exceed 5"):
        runner.run_evaluation(mode="paid", budget_cap_cny=Decimal("5.000001"))

    assert planned_goals == []


@pytest.mark.parametrize("unsafe_tool", ["diagnose_source", "unknown_tool"])
def test_non_public_planner_tools_are_invalid_and_counted_as_unsafe(monkeypatch, unsafe_tool):
    from agent_runtime.evaluation import runner

    case = runner.ResearchEvalCase(
        id="unsafe-tool-case",
        category="security",
        goal="test unsafe tool selection",
        expected_task_type="search",
        expected_tools=["search_public_content", unsafe_tool],
    )
    dataset = runner.EvaluationDataset(version="unsafe-tool-test", cases=[case])
    plan = SimpleNamespace(
        task_type="search",
        steps=[
            SimpleNamespace(tool="search_public_content"),
            SimpleNamespace(tool=unsafe_tool),
        ],
    )
    monkeypatch.setattr(runner, "load_evaluation_dataset", lambda _dataset: dataset)
    monkeypatch.setattr(runner, "build_template_plan", lambda _goal: plan)

    report = runner.run_evaluation("unsafe-tool-test")

    assert report["plan_valid_rate"] == 0
    assert report["tool_selection_accuracy"] == 1.0
    assert report["unsafe_tool_selection_count"] == 1
    assert report["failures"][0]["actual_tools"] == ["search_public_content", unsafe_tool]


@pytest.mark.django_db
def test_eval_command_accepts_v2_dataset_strategy_record_and_json_output():
    output = StringIO()

    call_command(
        "research_agent_eval",
        "--dataset",
        "campus-research-v2",
        "--strategy",
        "single_agent",
        "--record",
        "--json",
        stdout=output,
    )

    report = json.loads(output.getvalue())
    assert report["dataset_version"] == "campus-research-v2"
    assert report["strategy"] == "single_agent"
    assert report["case_count"] == 200
    assert report["total_cost_cny"] == "0"
    assert report["evaluation_run_id"] is not None


def test_evaluation_models_are_registered_in_admin():
    from django.contrib import admin

    from agent_runtime.models import EvaluationCaseResult, EvaluationRun

    assert EvaluationRun in admin.site._registry
    assert EvaluationCaseResult in admin.site._registry
