import json

import pytest
from django.core.cache import cache
from django.test import Client

from aggregator.models import Category, ContentItem, Source


@pytest.fixture(autouse=True)
def clear_research_cache():
    cache.clear()
@pytest.fixture
def deadline_item():
    source = Source.objects.create(
        name="教务处",
        url="https://jwc.example.edu/",
        source_type=Source.SourceType.DEPARTMENT_SITE,
    )
    category = Category.objects.create(name="通知", slug="notice")
    return ContentItem.objects.create(
        source=source,
        category=category,
        title="创新竞赛报名通知",
        canonical_url="https://jwc.example.edu/contest",
        summary="创新竞赛报名截止时间为2026年8月1日。",
        content_text="请参赛学生在2026年8月1日前完成报名。",
        status=ContentItem.Status.PUBLISHED,
        is_public=True,
    )


@pytest.mark.django_db
def test_create_research_run_is_idempotent():
    from agent_runtime.models import AgentEvent
    from agent_runtime.research.runtime import create_research_run

    first, first_created = create_research_run("查询竞赛截止日期", "request-001")
    second, second_created = create_research_run("不同文本不会覆盖原任务", "request-001")

    assert first_created is True
    assert second_created is False
    assert second.id == first.id
    assert second.goal == "查询竞赛截止日期"
    assert AgentEvent.objects.filter(run=first, event_type="run.created").count() == 1


@pytest.mark.django_db
def test_execute_research_run_persists_trace_and_terminal_state(deadline_item, settings):
    settings.MEILISEARCH_URL = ""
    from agent_runtime.models import AgentRun, ToolInvocation
    from agent_runtime.research.runtime import create_research_run, execute_research_run

    run, _ = create_research_run("整理创新竞赛报名截止时间", "request-002")
    result = execute_research_run(run.id)
    run.refresh_from_db()

    assert result["status"] == "succeeded"
    assert run.status == AgentRun.Status.SUCCEEDED
    assert run.current_node == "finalize"
    assert run.state_json["answer"]["citations"][0]["item_id"] == deadline_item.id
    assert list(run.events.values_list("sequence", flat=True)) == list(range(1, run.events.count() + 1))
    assert set(run.events.values_list("event_type", flat=True)) >= {
        "run.created",
        "plan.created",
        "tool.completed",
        "verification.passed",
        "run.completed",
    }
    assert ToolInvocation.objects.filter(run=run, status=ToolInvocation.Status.SUCCEEDED).count() == 3


@pytest.mark.django_db
def test_research_run_api_enqueues_once_for_same_client_request(monkeypatch):
    from agent_runtime.models import AgentRun

    calls = []
    monkeypatch.setattr(
        "agent_runtime.views.execute_research_run_task.delay",
        lambda run_id: calls.append(run_id),
    )
    client = Client()
    payload = {"goal": "比较近期就业活动", "client_request_id": "browser-request-1"}

    first = client.post("/api/v1/research-runs", data=json.dumps(payload), content_type="application/json")
    second = client.post("/api/v1/research-runs", data=json.dumps(payload), content_type="application/json")

    assert first.status_code == 202
    assert second.status_code == 200
    assert first.json()["run_id"] == second.json()["run_id"]
    assert calls == [str(AgentRun.objects.get().public_id)]


@pytest.mark.django_db
def test_research_event_stream_includes_stable_sse_ids():
    from agent_runtime.models import AgentRun
    from agent_runtime.research.runtime import append_event, create_research_run

    run, _ = create_research_run("查询校园通知", "request-events")
    append_event(run, "plan.created", {"step_count": 2})
    run.status = AgentRun.Status.SUCCEEDED
    run.save(update_fields=["status", "updated_at"])
    client = Client()

    response = client.get(f"/api/v1/research-runs/{run.public_id}/events")
    body = b"".join(response.streaming_content).decode()

    assert response.status_code == 200
    assert "id: 1\nevent: run.created" in body
    assert "id: 2\nevent: plan.created" in body
    assert 'data: {"step_count": 2}' in body


@pytest.mark.django_db(transaction=True)
def test_research_event_stream_observes_events_created_after_connection():
    from agent_runtime.models import AgentRun
    from agent_runtime.research.runtime import append_event, create_research_run

    run, _ = create_research_run("查询实时事件", "request-live-events")
    response = Client().get(f"/api/v1/research-runs/{run.public_id}/events")
    iterator = iter(response.streaming_content)

    first = next(iterator).decode()
    append_event(run, "answer.delta", {"text": "第一段"})
    run.status = AgentRun.Status.SUCCEEDED
    run.save(update_fields=["status", "updated_at"])
    second = next(iterator).decode()

    assert "event: run.created" in first
    assert "event: answer.delta" in second


@pytest.mark.django_db
def test_research_api_enforces_daily_limit_for_new_requests(monkeypatch, settings):
    settings.RESEARCH_AGENT_DAILY_LIMIT = 1
    monkeypatch.setattr("agent_runtime.views.execute_research_run_task.delay", lambda _run_id: None)
    client = Client()

    first = client.post(
        "/api/v1/research-runs",
        data=json.dumps({"goal": "查询就业信息", "client_request_id": "daily-limit-0001"}),
        content_type="application/json",
    )
    second = client.post(
        "/api/v1/research-runs",
        data=json.dumps({"goal": "查询科研活动", "client_request_id": "daily-limit-0002"}),
        content_type="application/json",
    )

    assert first.status_code == 202
    assert second.status_code == 429
    assert second.json()["error"] == "daily limit exceeded"


@pytest.mark.django_db
def test_cancel_research_run_marks_terminal_and_emits_event():
    from agent_runtime.models import AgentRun
    from agent_runtime.research.runtime import create_research_run

    run, _ = create_research_run("查询通知", "cancel-request-01")
    response = Client().post(f"/api/v1/research-runs/{run.public_id}/cancel")
    run.refresh_from_db()

    assert response.status_code == 200
    assert run.status == AgentRun.Status.CANCELLED
    assert run.events.filter(event_type="run.cancelled").exists()


@pytest.mark.django_db
def test_session_memory_is_used_only_when_secure_mode_enabled(settings):
    from agent_runtime.models import RagMessage, RagSession
    from agent_runtime.research.memory import resolve_goal_with_memory

    session = RagSession.objects.create(session_key="memory-session", title="就业活动")
    RagMessage.objects.create(session=session, role=RagMessage.Role.USER, content="帮我找近期就业活动")
    RagMessage.objects.create(session=session, role=RagMessage.Role.ASSISTANT, content="找到了三项就业活动")

    settings.RESEARCH_AGENT_SESSION_MEMORY_ENABLED = False
    assert resolve_goal_with_memory("这些活动的截止时间", session) == "这些活动的截止时间"

    settings.RESEARCH_AGENT_SESSION_MEMORY_ENABLED = True
    resolved = resolve_goal_with_memory("这些活动的截止时间", session)
    assert "帮我找近期就业活动" in resolved
    assert resolved.endswith("当前目标：这些活动的截止时间")


@pytest.mark.django_db
def test_research_page_uses_post_api_and_event_stream():
    response = Client().get("/research/")
    html = response.content.decode()

    assert response.status_code == 200
    assert 'fetch("/api/v1/research-runs"' in html
    assert 'method: "POST"' in html
    assert "new EventSource(payload.events_url)" in html
    assert "?q=" not in html


@pytest.mark.django_db
def test_agent_dashboard_displays_research_latency_percentiles():
    from agent_runtime.models import ToolInvocation
    from agent_runtime.research.runtime import create_research_run

    run, _ = create_research_run("延迟统计", "latency-dashboard")
    for index, duration in enumerate([10, 20, 100], start=1):
        ToolInvocation.objects.create(
            run=run,
            step_id=f"step-{index}",
            tool_name="search_public_content",
            status=ToolInvocation.Status.SUCCEEDED,
            duration_ms=duration,
        )

    html = Client().get("/agent/").content.decode()

    assert "工具延迟 P50" in html
    assert ">20 ms<" in html
    assert "工具延迟 P95" in html
    assert ">100 ms<" in html
