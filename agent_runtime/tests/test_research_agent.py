import pytest

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
