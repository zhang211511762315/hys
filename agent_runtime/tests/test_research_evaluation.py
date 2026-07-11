import json
from io import StringIO

import pytest
from django.core.management import call_command

from aggregator.models import Category, ContentItem, Source


def test_versioned_research_dataset_has_120_stratified_cases():
    from agent_runtime.evaluation.runner import load_research_dataset

    cases = load_research_dataset()
    counts = {}
    for case in cases:
        counts[case.category] = counts.get(case.category, 0) + 1

    assert len(cases) == 120
    assert counts == {
        "retrieval_filter": 40,
        "multi_step": 30,
        "ambiguous": 15,
        "no_answer": 15,
        "tool_failure": 10,
        "security": 10,
    }
    assert len({case.id for case in cases}) == 120


def test_planner_evaluation_reports_valid_safe_tool_plans():
    from agent_runtime.evaluation.runner import run_planner_evaluation

    report = run_planner_evaluation()

    assert report["dataset_version"] == "campus-research-v1"
    assert report["case_count"] == 120
    assert report["plan_valid_rate"] == 1.0
    assert report["tool_selection_accuracy"] == 1.0
    assert report["unsafe_tool_selection_count"] == 0


def test_research_agent_eval_command_outputs_json():
    output = StringIO()

    call_command("research_agent_eval", "--json", stdout=output)

    report = json.loads(output.getvalue())
    assert report["case_count"] == 120
    assert report["total_cost_cny"] == "0"


@pytest.mark.django_db
def test_frozen_corpus_retrieval_meets_recall_and_mrr_gate():
    from agent_runtime.evaluation.runner import load_retrieval_fixture, run_retrieval_evaluation
    from agent_runtime.research.tools import build_default_registry

    fixture = load_retrieval_fixture()
    category = Category.objects.create(name="评测", slug="eval")
    gold_ids = {}
    for index, document in enumerate(fixture["documents"], start=1):
        source = Source.objects.create(
            name=document["source"],
            url=f"https://source-{index}.example.edu/",
            source_type=Source.SourceType.DEPARTMENT_SITE,
        )
        item = ContentItem.objects.create(
            source=source,
            category=category,
            title=document["title"],
            canonical_url=document["url"],
            summary=document["summary"],
            content_text=document["summary"],
            status=ContentItem.Status.PUBLISHED,
            is_public=True,
        )
        gold_ids[document["key"]] = item.id

    report = run_retrieval_evaluation(fixture["queries"], gold_ids, build_default_registry())

    assert report["case_count"] == 40
    assert report["recall_at_5"] >= 0.95
    assert report["mrr"] >= 0.90
