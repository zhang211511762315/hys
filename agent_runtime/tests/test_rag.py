from decimal import Decimal
import json
from io import StringIO

import pytest
from django.core.management import call_command
from django.test import Client
from django.utils import timezone

from aggregator.models import Category, ContentItem, Source
from agent_runtime.models import AgentRun, ContentChunk, LLMUsageEvent, RagMessage, RagSession
from agent_runtime import services
from agent_runtime.services import (
    answer_question_events,
    rebuild_rag_chunks,
    retrieve_contexts,
    run_self_heal,
    upsert_rag_chunks_for_item,
)


@pytest.fixture
def published_item():
    source = Source.objects.create(
        name="中北大学官网",
        url="https://www.nuc.edu.cn/",
        source_type=Source.SourceType.OFFICIAL_SITE,
    )
    category = Category.objects.create(name="就业", slug="jobs")
    return ContentItem.objects.create(
        source=source,
        category=category,
        title="就业招聘宣讲会通知",
        canonical_url="https://www.nuc.edu.cn/info/1001/job.htm",
        summary="本周举行就业招聘宣讲会。",
        content_text="学校将组织多场就业招聘宣讲会，学生可以携带简历参加。",
        status=ContentItem.Status.PUBLISHED,
        is_public=True,
        source_published_at=timezone.datetime(2026, 6, 1, tzinfo=timezone.get_current_timezone()),
    )


@pytest.mark.django_db
def test_rebuild_rag_chunks_indexes_public_content(published_item, settings):
    settings.MEILISEARCH_URL = ""

    result = rebuild_rag_chunks(sync_meili=False)

    assert result["created"] == 1
    chunk = ContentChunk.objects.get(content_item=published_item)
    assert "就业招聘宣讲会" in chunk.text
    assert chunk.search_document_id == f"item-{published_item.id}-0"


@pytest.mark.django_db
def test_incremental_rag_index_updates_and_removes_unpublished_content(published_item, settings):
    settings.MEILISEARCH_URL = ""
    settings.RAG_CHUNK_CHARS = 30
    settings.RAG_CHUNK_OVERLAP_CHARS = 5

    first = upsert_rag_chunks_for_item(published_item.id, sync_meili=False)
    assert first["chunk_count"] > 1

    published_item.content_text = "短内容"
    published_item.save(update_fields=["content_text", "updated_at"])
    second = upsert_rag_chunks_for_item(published_item.id, sync_meili=False)
    assert second["chunk_count"] == 1
    assert ContentChunk.objects.filter(content_item=published_item).count() == 1

    published_item.is_public = False
    published_item.save(update_fields=["is_public", "updated_at"])
    removed = upsert_rag_chunks_for_item(published_item.id, sync_meili=False)
    assert removed == {"chunk_count": 0, "removed": True, "meili_synced": 0}
    assert not ContentChunk.objects.filter(content_item=published_item).exists()


@pytest.mark.django_db
def test_retrieve_contexts_returns_public_chunks(published_item, settings):
    settings.MEILISEARCH_URL = ""
    rebuild_rag_chunks(sync_meili=False)

    contexts = retrieve_contexts("就业 招聘", limit=3)

    assert contexts
    assert contexts[0].item == published_item
    assert "简历" in contexts[0].text


@pytest.mark.django_db
def test_answer_question_falls_back_without_llm_budget(published_item, settings):
    settings.MEILISEARCH_URL = ""
    settings.DEEPSEEK_API_KEY = ""
    rebuild_rag_chunks(sync_meili=False)

    events = list(answer_question_events("有哪些就业招聘信息？"))

    assert any(event["type"] == "usage_estimate" and event["allowed"] is False for event in events)
    answer_text = "".join(event["text"] for event in events if event["type"] == "delta")
    assert "未消耗付费模型预算" in answer_text
    session = RagSession.objects.get()
    assert session.total_cost_cny == Decimal("0")
    assert RagMessage.objects.filter(role=RagMessage.Role.ASSISTANT).exists()
    usage = LLMUsageEvent.objects.get()
    assert usage.status == LLMUsageEvent.Status.FALLBACK
    assert AgentRun.objects.filter(kind=AgentRun.Kind.RAG, status=AgentRun.Status.SUCCEEDED).exists()


@pytest.mark.django_db
def test_answer_question_falls_back_when_model_returns_blank(published_item, settings, monkeypatch):
    settings.MEILISEARCH_URL = ""
    settings.DEEPSEEK_API_KEY = "test-key"
    settings.DEEPSEEK_DAILY_BUDGET_CNY = "100"
    settings.DEEPSEEK_MONTHLY_BUDGET_CNY = "1000"
    rebuild_rag_chunks(sync_meili=False)

    def blank_answer(prompt, contexts, estimate):
        return "", {"prompt_tokens": 10, "completion_tokens": 0}, ""

    monkeypatch.setattr(services, "_generate_answer", blank_answer)

    events = list(answer_question_events("有哪些就业招聘信息？"))

    assert events[-1]["type"] == "done"
    assert not any(event["type"] == "error" for event in events)
    answer_text = "".join(event["text"] for event in events if event["type"] == "delta")
    assert "原模型本次未返回有效文本" in answer_text
    usage = LLMUsageEvent.objects.get()
    assert usage.status == LLMUsageEvent.Status.FALLBACK
    run = AgentRun.objects.get(kind=AgentRun.Kind.RAG)
    assert run.status == AgentRun.Status.SUCCEEDED
    assert run.metrics_json["fallback"] is True


@pytest.mark.django_db
def test_answer_question_returns_error_event_when_pipeline_raises(settings, monkeypatch):
    settings.MEILISEARCH_URL = ""

    def broken_retrieval(question):
        raise RuntimeError("retrieval failed")

    monkeypatch.setattr(services, "retrieve_contexts", broken_retrieval)

    events = list(answer_question_events("任意问题"))

    assert events[-2]["type"] == "error"
    assert events[-1]["type"] == "done"
    run = AgentRun.objects.get(kind=AgentRun.Kind.RAG)
    assert run.status == AgentRun.Status.FAILED
    assert "retrieval failed" in run.error_message


@pytest.mark.django_db
def test_ask_page_sets_session_cookie_for_new_visitor():
    client = Client()

    response = client.get("/ask/")

    assert response.status_code == 200
    assert "rag_session_key" in response.cookies
    assert response.cookies["rag_session_key"].value


@pytest.mark.django_db
def test_ask_page_renders_demo_questions():
    client = Client()

    response = client.get("/ask/")
    html = response.content.decode()

    assert response.status_code == 200
    assert 'data-question="最近有哪些就业招聘信息？"' in html
    assert 'data-question="研究生招生相关通知有哪些？"' in html
    assert 'data-question="有哪些学术科研活动？"' in html


@pytest.mark.django_db
def test_ask_page_posts_question_without_query_string():
    html = Client().get("/ask/").content.decode()

    assert 'method: "POST"' in html
    assert 'fetch("/ask/stream/"' in html
    assert "?q=" not in html


@pytest.mark.django_db
def test_ask_page_renders_only_current_session_history():
    current_session = RagSession.objects.create(
        session_key="current-session",
        title="当前会话",
        total_input_tokens=12,
        total_output_tokens=8,
        total_cost_cny=Decimal("0.001000"),
    )
    other_session = RagSession.objects.create(session_key="other-session", title="其他会话")
    RagMessage.objects.create(
        session=current_session,
        role=RagMessage.Role.USER,
        content="当前会话的问题",
    )
    RagMessage.objects.create(
        session=current_session,
        role=RagMessage.Role.ASSISTANT,
        content="当前会话的回答",
        input_tokens=12,
        output_tokens=8,
        cost_cny=Decimal("0.001000"),
        model="rules",
    )
    RagMessage.objects.create(
        session=other_session,
        role=RagMessage.Role.USER,
        content="其他人的问题",
    )

    client = Client()
    client.cookies["rag_session_key"] = "current-session"
    response = client.get("/ask/")
    content = response.content.decode()

    assert response.status_code == 200
    assert "当前会话的问题" in content
    assert "当前会话的回答" in content
    assert "其他人的问题" not in content
    assert 'id="session-input">12</strong>' in content
    assert 'id="session-output">8</strong>' in content
    assert 'id="session-cost">0.001000</strong>' in content


@pytest.mark.django_db
def test_ask_page_new_conversation_ignores_existing_cookie():
    old_session = RagSession.objects.create(session_key="old-session", title="旧会话")
    RagMessage.objects.create(
        session=old_session,
        role=RagMessage.Role.USER,
        content="旧会话问题",
    )
    client = Client()
    client.cookies["rag_session_key"] = "old-session"

    response = client.get("/ask/?new=1")
    content = response.content.decode()

    assert response.status_code == 200
    assert "旧会话问题" not in content
    assert response.cookies["rag_session_key"].value != "old-session"


@pytest.mark.django_db
def test_self_heal_dry_run_declares_no_llm_budget(settings):
    settings.SELF_HEAL_ENABLED = True

    result = run_self_heal(dry_run=True)

    assert result["enabled"] is True
    assert result["dry_run"] is True
    assert result["consumes_llm_budget"] is False


@pytest.mark.django_db
def test_agent_dashboard_is_resume_ready_without_public_admin_link(settings):
    settings.DEEPSEEK_DAILY_BUDGET_CNY = "0.1"
    settings.DEEPSEEK_MONTHLY_BUDGET_CNY = "3"

    client = Client()
    response = client.get("/agent/")
    html = response.content.decode()

    assert response.status_code == 200
    assert "AI Agent 工程项目" in html
    assert "RAG 问答演示" in html
    assert "工具调用 / MCP" in html
    assert 'href="/admin/"' not in html


@pytest.mark.django_db
def test_agent_dashboard_formats_latest_eval_metrics_as_percentages(settings):
    settings.DEEPSEEK_DAILY_BUDGET_CNY = "0.1"
    settings.DEEPSEEK_MONTHLY_BUDGET_CNY = "3"
    AgentRun.objects.create(
        kind=AgentRun.Kind.EVAL,
        status=AgentRun.Status.SUCCEEDED,
        metrics_json={
            "retrieval_hit_rate": 1.0,
            "expected_keyword_hit_rate": 0.75,
            "paid_llm_calls": 0,
        },
    )

    client = Client()
    response = client.get("/agent/")
    html = response.content.decode()

    assert response.status_code == 200
    assert "检索命中率 100.0%" in html
    assert "期望关键词命中率 75.0%" in html


@pytest.mark.django_db
def test_agent_eval_json_records_structured_eval_run(published_item, settings):
    settings.MEILISEARCH_URL = ""
    rebuild_rag_chunks(sync_meili=False)
    out = StringIO()

    call_command("agent_eval", "--json", stdout=out)

    payload = json.loads(out.getvalue())
    assert payload["case_count"] >= 3
    assert payload["retrieval_hit_rate"] > 0
    assert payload["total_cost_cny"] == "0"
    run = AgentRun.objects.get(kind=AgentRun.Kind.EVAL)
    assert run.status == AgentRun.Status.SUCCEEDED
    assert run.metrics_json["case_count"] == payload["case_count"]
    assert run.metrics_json["paid_llm_calls"] == 0
