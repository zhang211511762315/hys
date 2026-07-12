import pytest
from django.utils import timezone

from aggregator.models import Category, ContentItem, Source


def test_template_planner_builds_bounded_deadline_research_plan():
    from agent_runtime.research.planner import build_template_plan

    plan = build_template_plan("整理最近的就业招聘信息和报名截止时间")

    assert plan.task_type == "deadline_research"
    assert [step.tool for step in plan.steps] == [
        "search_public_content",
        "get_content_details",
        "build_deadline_timeline",
    ]
    assert len(plan.steps) <= 6
    assert plan.steps[1].input_from == {"item_ids": "search.item_ids"}
    assert plan.steps[2].input_from == {"items": "details.items"}


def test_hybrid_planner_accepts_valid_model_plan_for_complex_goal():
    from agent_runtime.research.planner import build_hybrid_plan

    def model_planner(_goal):
        return {
            "goal": "综合比较就业与科研机会，并按适合本科生的程度说明理由",
            "task_type": "comparison",
            "steps": [
                {
                    "id": "search",
                    "tool": "search_public_content",
                    "description": "检索公开信息",
                    "args": {"query": "就业 科研 本科生", "limit": 8},
                },
                {
                    "id": "details",
                    "tool": "get_content_details",
                    "description": "读取详情",
                    "input_from": {"item_ids": "search.item_ids"},
                },
                {
                    "id": "comparison",
                    "tool": "compare_evidence",
                    "description": "比较证据",
                    "input_from": {"items": "details.items"},
                },
            ],
        }

    plan = build_hybrid_plan(
        "综合比较就业与科研机会，并按适合本科生的程度说明理由",
        model_planner=model_planner,
    )

    assert plan.task_type == "comparison"
    assert plan.steps[-1].tool == "compare_evidence"


def test_hybrid_planner_rejects_admin_tool_and_falls_back():
    from agent_runtime.research.planner import build_hybrid_plan

    def unsafe_planner(goal):
        return {
            "goal": goal,
            "task_type": "search",
            "steps": [
                {
                    "id": "repair",
                    "tool": "retry_source",
                    "description": "越权修复来源",
                    "args": {"source_id": 1},
                }
            ],
        }

    plan = build_hybrid_plan(
        "综合整理学校信息并判断哪些内容值得本科生关注",
        model_planner=unsafe_planner,
    )

    assert [step.tool for step in plan.steps] == ["search_public_content", "get_content_details"]


def test_public_actor_cannot_execute_admin_write_tool():
    from pydantic import BaseModel

    from agent_runtime.research.tools import (
        RiskLevel,
        ToolContext,
        ToolPermission,
        ToolRegistry,
        ToolSpec,
    )

    class EmptyInput(BaseModel):
        pass

    class Result(BaseModel):
        ok: bool

    registry = ToolRegistry()
    registry.register(
        ToolSpec(
            name="retry_source",
            version="1",
            input_model=EmptyInput,
            output_model=Result,
            risk_level=RiskLevel.HIGH,
            permission=ToolPermission.STAFF,
            timeout_seconds=10,
            max_retries=0,
            idempotent=True,
            executor=lambda _payload, _context: {"ok": True},
        )
    )

    with pytest.raises(PermissionError, match="staff permission"):
        registry.execute("retry_source", {}, ToolContext(actor_is_staff=False))


@pytest.fixture
def research_item():
    source = Source.objects.create(
        name="就业信息网",
        url="https://job.example.edu/",
        source_type=Source.SourceType.OFFICIAL_SITE,
    )
    category = Category.objects.create(name="就业", slug="jobs")
    return ContentItem.objects.create(
        source=source,
        category=category,
        title="暑期实习双选会报名通知",
        canonical_url="https://job.example.edu/internship-2026",
        summary="暑期实习双选会报名截止时间为2026年7月20日。",
        content_text="学校举办暑期实习双选会，学生须在2026年7月20日前完成报名。",
        status=ContentItem.Status.PUBLISHED,
        is_public=True,
    )


@pytest.mark.django_db
def test_research_graph_executes_tools_and_verifies_citations(research_item, settings):
    settings.MEILISEARCH_URL = ""

    from agent_runtime.research.workflow import build_research_graph

    result = build_research_graph().invoke(
        {"goal": "整理就业实习报名截止时间", "actor_is_staff": False}
    )

    assert result["status"] == "succeeded"
    assert result["verification"]["passed"] is True
    assert result["answer"]["citations"][0]["item_id"] == research_item.id
    assert "2026年7月20日" in result["answer"]["answer"]
    assert result["executed_tools"] == [
        "search_public_content",
        "get_content_details",
        "build_deadline_timeline",
    ]


@pytest.mark.django_db
def test_research_graph_safely_terminates_when_no_evidence(settings):
    settings.MEILISEARCH_URL = ""

    from agent_runtime.research.workflow import build_research_graph

    result = build_research_graph().invoke(
        {"goal": "查询不存在的量子传送校园活动", "actor_is_staff": False}
    )

    assert result["status"] == "succeeded"
    assert result["verification"] == {"passed": True, "reasons": []}
    assert result["answer"]["insufficient_evidence"] is True
    assert result["answer"]["citations"] == []


@pytest.mark.django_db
def test_research_graph_replans_once_after_verification_failure(research_item, settings):
    settings.MEILISEARCH_URL = ""
    from agent_runtime.research.workflow import build_research_graph

    def answer_builder(state, items, _outputs):
        item = items[0]
        citation_id = 999999 if state.get("replan_count", 0) == 0 else item["item_id"]
        return {
            "answer": "带验证的研究结论",
            "citations": [
                {
                    "item_id": citation_id,
                    "title": item["title"],
                    "source": item["source"],
                    "url": item["url"],
                }
            ],
            "insufficient_evidence": False,
        }

    result = build_research_graph(answer_builder=answer_builder).invoke(
        {"goal": "查询就业实习信息", "actor_is_staff": False}
    )

    assert result["status"] == "succeeded"
    assert result["replan_count"] == 1
    assert result["verification"]["passed"] is True
    assert result["answer"]["citations"][0]["item_id"] == research_item.id


@pytest.mark.django_db
def test_search_tool_applies_source_category_and_date_filters(research_item):
    from datetime import timedelta
    from agent_runtime.research.tools import ToolContext, build_default_registry

    research_item.source_published_at = timezone.now() - timedelta(days=2)
    research_item.save(update_fields=["source_published_at", "updated_at"])
    registry = build_default_registry()
    result = registry.execute(
        "search_public_content",
        {
            "query": "暑期实习",
            "source_names": ["就业信息网"],
            "category_slugs": ["jobs"],
            "published_after": (timezone.now() - timedelta(days=7)).date().isoformat(),
            "published_before": timezone.now().date().isoformat(),
        },
        ToolContext(),
    )
    excluded = registry.execute(
        "search_public_content",
        {"query": "暑期实习", "source_names": ["教务处"]},
        ToolContext(),
    )

    assert result["item_ids"] == [research_item.id]
    assert excluded["item_ids"] == []
