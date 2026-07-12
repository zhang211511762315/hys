from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal, ROUND_HALF_UP
import json
import re
import secrets
from typing import Iterable

import httpx
from django.conf import settings
from django.db.models import Q, Sum
from django.urls import reverse
from django.utils import timezone

from aggregator.models import AIUsageDaily, ContentItem, CrawlFailure, CrawlJob
from aggregator.services.ai import (
    finalize_deepseek_budget,
    release_deepseek_budget,
    reserve_deepseek_budget,
)

from .models import (
    AgentRun,
    AgentStep,
    ContentChunk,
    LLMUsageEvent,
    RagCitation,
    RagMessage,
    RagSession,
    MemoryEntry,
)
from .graph import build_rag_graph
from .schemas import RagAnswerSchema, SelfHealPlanSchema, UsageReportSchema


QUERY_STOP_TERMS = {
    "有哪",
    "哪些",
    "最近",
    "信息",
    "相关",
    "关于",
    "什么",
    "怎么",
    "如何",
    "可以",
    "一下",
}


@dataclass(frozen=True)
class RagContext:
    chunk: ContentChunk | None
    item: ContentItem
    text: str
    score: float = 0.0


@dataclass(frozen=True)
class UsageEstimate:
    input_tokens: int
    output_tokens: int
    cost_cny: Decimal
    budget_remaining_cny: Decimal
    allowed: bool


AGENT_EVAL_CASES = [
    {
        "question": "最近有哪些就业招聘信息？",
        "expected_terms": ["就业", "招聘"],
    },
    {
        "question": "研究生招生相关通知有哪些？",
        "expected_terms": ["研究生", "招生"],
    },
    {
        "question": "有哪些学术科研活动？",
        "expected_terms": ["学术", "科研"],
    },
    {
        "question": "学生社团近期有什么活动？",
        "expected_terms": ["社团", "活动"],
    },
]


def new_session_key() -> str:
    return secrets.token_urlsafe(24)


def get_or_create_session(session_key: str | None, title: str = "", user=None) -> RagSession:
    key = session_key or new_session_key()
    now = timezone.now()
    expires_at = now + timezone.timedelta(days=max(1, settings.RAG_SESSION_RETENTION_DAYS))
    session = RagSession.objects.filter(session_key=key).first()
    if session is not None and session.user_id and session.user_id != getattr(user, "id", None):
        session = None
        key = new_session_key()
    if session is None:
        session = RagSession.objects.create(session_key=key, title=title[:160], user=user, expires_at=expires_at)
    else:
        update_fields = ["updated_at"]
        if user is not None and session.user_id is None:
            session.user = user
            update_fields.append("user")
        session.expires_at = expires_at
        update_fields.append("expires_at")
        session.save(update_fields=update_fields)
    if not session.title and title:
        session.title = title[:160]
        session.save(update_fields=["title", "updated_at"])
    return session


def save_explicit_memory(user, content: str, source_session: RagSession | None = None) -> MemoryEntry:
    clean_content = (content or "").strip()[:1000]
    if not clean_content:
        raise ValueError("memory content is required")
    now = timezone.now()
    return MemoryEntry.objects.create(
        user=user,
        source_session=source_session,
        content=clean_content,
        consented_at=now,
        expires_at=now + timezone.timedelta(days=max(1, settings.MEMORY_RETENTION_DAYS)),
    )


def cleanup_expired_memory(now=None) -> dict[str, int]:
    now = now or timezone.now()
    memory_deleted, _ = MemoryEntry.objects.filter(expires_at__lte=now).delete()
    session_deleted, _ = RagSession.objects.filter(expires_at__lte=now).delete()
    return {"memory_deleted": memory_deleted, "session_deleted": session_deleted}


def rebuild_rag_chunks(limit: int | None = None, sync_meili: bool = True) -> dict:
    queryset = (
        ContentItem.objects.filter(status=ContentItem.Status.PUBLISHED, is_public=True)
        .select_related("source", "category")
        .order_by("-source_published_at", "-created_at")
    )
    if limit:
        queryset = queryset[:limit]

    seen_item_ids = []
    created = 0
    updated = 0
    documents = []
    chunk_chars = settings.RAG_CHUNK_CHARS
    overlap = min(settings.RAG_CHUNK_OVERLAP_CHARS, chunk_chars // 2)

    for item in queryset:
        seen_item_ids.append(item.id)
        body = "\n".join(part for part in [item.title, item.summary, item.content_text] if part).strip()
        if not body:
            continue
        chunks = _chunk_text(body, chunk_chars, overlap)
        for index, text in enumerate(chunks):
            document_id = f"item-{item.id}-{index}"
            chunk, was_created = ContentChunk.objects.update_or_create(
                content_item=item,
                chunk_index=index,
                defaults={"text": text, "search_document_id": document_id},
            )
            created += int(was_created)
            updated += int(not was_created)
            documents.append(_chunk_to_search_doc(chunk))
        ContentChunk.objects.filter(content_item=item, chunk_index__gte=len(chunks)).delete()

    if limit is None:
        ContentChunk.objects.exclude(content_item_id__in=seen_item_ids).delete()

    meili_synced = 0
    if sync_meili and documents:
        meili_synced = sync_chunks_to_meilisearch(documents)

    return {"created": created, "updated": updated, "meili_synced": meili_synced}


def upsert_rag_chunks_for_item(item_id: int, sync_meili: bool = True) -> dict:
    item = ContentItem.objects.select_related("source", "category").get(id=item_id)
    existing_ids = list(item.rag_chunks.values_list("search_document_id", flat=True))
    if item.status != ContentItem.Status.PUBLISHED or not item.is_public:
        item.rag_chunks.all().delete()
        if sync_meili and existing_ids:
            _delete_meili_documents(existing_ids)
        return {"chunk_count": 0, "removed": True, "meili_synced": 0}

    body = "\n".join(part for part in [item.title, item.summary, item.content_text] if part).strip()
    chunks = _chunk_text(
        body,
        settings.RAG_CHUNK_CHARS,
        min(settings.RAG_CHUNK_OVERLAP_CHARS, settings.RAG_CHUNK_CHARS // 2),
    )
    documents = []
    active_ids = []
    for index, text in enumerate(chunks):
        document_id = f"item-{item.id}-{index}"
        chunk, _ = ContentChunk.objects.update_or_create(
            content_item=item,
            chunk_index=index,
            defaults={"text": text, "search_document_id": document_id},
        )
        active_ids.append(document_id)
        documents.append(_chunk_to_search_doc(chunk))
    stale_ids = [document_id for document_id in existing_ids if document_id not in active_ids]
    item.rag_chunks.exclude(search_document_id__in=active_ids).delete()
    if sync_meili and stale_ids:
        _delete_meili_documents(stale_ids)
    meili_synced = sync_chunks_to_meilisearch(documents) if sync_meili and documents else 0
    return {"chunk_count": len(documents), "removed": False, "meili_synced": meili_synced}


def sync_chunks_to_meilisearch(documents: list[dict]) -> int:
    if not settings.MEILISEARCH_URL:
        return 0
    try:
        import meilisearch
    except ImportError:
        return 0
    client = meilisearch.Client(settings.MEILISEARCH_URL, settings.MEILISEARCH_MASTER_KEY or None)
    index = client.index(settings.MEILISEARCH_RAG_INDEX)
    try:
        index.update_searchable_attributes(["title", "summary", "text", "source", "category"])
        index.update_filterable_attributes(["item_id", "source", "category", "published_at"])
    except Exception:
        pass
    index.add_documents(documents)
    return len(documents)


def _delete_meili_documents(document_ids: list[str]) -> None:
    if not settings.MEILISEARCH_URL or not document_ids:
        return
    try:
        import meilisearch

        client = meilisearch.Client(settings.MEILISEARCH_URL, settings.MEILISEARCH_MASTER_KEY or None)
        client.index(settings.MEILISEARCH_RAG_INDEX).delete_documents(document_ids)
    except Exception:
        return


def retrieve_contexts(query: str, limit: int | None = None) -> list[RagContext]:
    limit = limit or settings.RAG_MAX_CONTEXT_CHUNKS
    query = (query or "").strip()
    if not query:
        return []
    contexts = _retrieve_contexts_from_meili(query, limit)
    if contexts:
        return contexts
    return _retrieve_contexts_from_db(query, limit)


def answer_question_events(question: str, session_key: str | None = None, user=None) -> Iterable[dict]:
    question = (question or "").strip()[:1000]
    session = None
    run = None
    retrieval_step = None
    graph_step = None
    generation_step = None
    usage_event = None
    contexts: list[RagContext] = []
    try:
        session = get_or_create_session(session_key, question, user=user)
        run = AgentRun.objects.create(kind=AgentRun.Kind.RAG, trigger="ask_page")
        retrieval_step = AgentStep.objects.create(
            run=run,
            name="retrieve_context",
            tool_name="rag.retrieve",
            input_summary=question,
        )
        contexts = retrieve_contexts(question)
        retrieval_step.finish(AgentStep.Status.SUCCEEDED, output_summary=f"{len(contexts)} context chunk(s)")
        graph_step = AgentStep.objects.create(
            run=run,
            name="rag_state_graph",
            tool_name="langgraph.StateGraph",
            input_summary=f"contexts={len(contexts)}",
        )
        try:
            graph = build_rag_graph()
            if graph is not None:
                graph.invoke({"question": question, "context_count": len(contexts)})
                graph_step.finish(AgentStep.Status.SUCCEEDED, output_summary="LangGraph RAG state graph invoked")
            else:
                graph_step.finish(AgentStep.Status.SKIPPED, output_summary="LangGraph unavailable")
        except Exception as exc:
            graph_step.finish(AgentStep.Status.SKIPPED, error_message=str(exc))
        yield {"type": "session", "session_key": session.session_key}
        for context in contexts:
            yield {
                "type": "citation",
                "title": context.item.title,
                "source": context.item.source.name,
                "url": context.item.canonical_url,
                "detail_url": reverse("aggregator:item_detail", args=[context.item.id]),
            }

        prompt = build_rag_prompt(question, contexts)
        estimate = estimate_deepseek_usage(prompt, settings.RAG_MAX_OUTPUT_TOKENS)
        usage_event = LLMUsageEvent.objects.create(
            session=session,
            provider="deepseek",
            model=settings.DEEPSEEK_MODEL,
            input_tokens=estimate.input_tokens,
            output_tokens=estimate.output_tokens,
            cost_cny=estimate.cost_cny,
            budget_remaining_cny=estimate.budget_remaining_cny,
            status=LLMUsageEvent.Status.ESTIMATED if estimate.allowed else LLMUsageEvent.Status.BLOCKED,
        )
        yield {
            "type": "usage_estimate",
            "input_tokens": estimate.input_tokens,
            "output_tokens": estimate.output_tokens,
            "cost_cny": str(estimate.cost_cny),
            "budget_remaining_cny": str(estimate.budget_remaining_cny),
            "allowed": estimate.allowed,
        }
        UsageReportSchema(
            input_tokens=estimate.input_tokens,
            output_tokens=estimate.output_tokens,
            cost_cny=estimate.cost_cny,
            budget_remaining_cny=estimate.budget_remaining_cny,
            status="estimated" if estimate.allowed else "blocked",
        )

        user_message = RagMessage.objects.create(
            session=session,
            role=RagMessage.Role.USER,
            content=question,
            input_tokens=estimate.input_tokens,
            model=settings.DEEPSEEK_MODEL,
        )
        generation_step = AgentStep.objects.create(
            run=run,
            name="generate_answer",
            tool_name="llm.deepseek",
            input_summary=f"{len(contexts)} contexts",
        )
        answer, usage_payload, fallback_reason = _generate_answer(prompt, contexts, estimate)
        if not answer.strip():
            answer = _fallback_answer(contexts, no_paid_model=not bool(usage_payload))
            fallback_reason = fallback_reason or "empty_model_answer"

        if fallback_reason:
            status = AgentStep.Status.FAILED if fallback_reason == "empty_model_answer" else AgentStep.Status.SKIPPED
            generation_step.finish(status, output_summary=f"fallback: {fallback_reason}")
        else:
            generation_step.finish(AgentStep.Status.SUCCEEDED, output_summary="deepseek response")

        for part in _stream_chunks(answer):
            yield {"type": "delta", "text": part}

        final_input_tokens, final_output_tokens, final_cost = _final_usage_values(prompt, answer, usage_payload, estimate)
        assistant_message = RagMessage.objects.create(
            session=session,
            role=RagMessage.Role.ASSISTANT,
            content=answer,
            input_tokens=final_input_tokens,
            output_tokens=final_output_tokens,
            cost_cny=final_cost,
            model=settings.DEEPSEEK_MODEL if not fallback_reason else "rules",
        )
        for context in contexts:
            RagCitation.objects.create(
                message=assistant_message,
                content_item=context.item,
                title=context.item.title,
                source_name=context.item.source.name,
                url=context.item.canonical_url,
                snippet=context.text[:300],
            )
        RagAnswerSchema(
            answer=answer,
            citations=[
                {
                    "title": context.item.title,
                    "source": context.item.source.name,
                    "url": context.item.canonical_url,
                    "snippet": context.text[:300],
                }
                for context in contexts
            ],
            model=assistant_message.model,
        )

        session.total_input_tokens += final_input_tokens
        session.total_output_tokens += final_output_tokens
        session.total_cost_cny += final_cost
        session.save(
            update_fields=["total_input_tokens", "total_output_tokens", "total_cost_cny", "updated_at"]
        )
        usage_event.message = assistant_message
        usage_event.input_tokens = final_input_tokens
        usage_event.output_tokens = final_output_tokens
        usage_event.cost_cny = final_cost
        usage_event.status = LLMUsageEvent.Status.FINAL if not fallback_reason else LLMUsageEvent.Status.FALLBACK
        usage_event.save(
            update_fields=["message", "input_tokens", "output_tokens", "cost_cny", "status", "updated_at"]
        )
        run.total_cost_cny = final_cost
        run.save(update_fields=["total_cost_cny", "updated_at"])
        run.finish(AgentRun.Status.SUCCEEDED, metrics={"contexts": len(contexts), "fallback": bool(fallback_reason)})

        yield {
            "type": "usage_final",
            "input_tokens": final_input_tokens,
            "output_tokens": final_output_tokens,
            "cost_cny": str(final_cost),
            "session_input_tokens": session.total_input_tokens,
            "session_output_tokens": session.total_output_tokens,
            "session_cost_cny": str(session.total_cost_cny),
            "model": assistant_message.model,
        }
        yield {"type": "done"}
    except Exception as exc:
        _finish_step_if_running(generation_step, AgentStep.Status.FAILED, str(exc))
        _finish_step_if_running(graph_step, AgentStep.Status.FAILED, str(exc))
        _finish_step_if_running(retrieval_step, AgentStep.Status.FAILED, str(exc))
        if usage_event is not None and usage_event.status == LLMUsageEvent.Status.ESTIMATED:
            usage_event.status = LLMUsageEvent.Status.FALLBACK
            usage_event.output_tokens = estimate_tokens("问答生成中断，请稍后重试或换个问法。")
            usage_event.cost_cny = Decimal("0")
            usage_event.save(update_fields=["status", "output_tokens", "cost_cny", "updated_at"])
        if run is not None and run.status == AgentRun.Status.RUNNING:
            run.finish(AgentRun.Status.FAILED, error_message=str(exc), metrics={"contexts": len(contexts)})
        yield {"type": "error", "message": "问答生成中断，请稍后重试或换个问法。"}
        yield {"type": "done"}


def build_rag_prompt(question: str, contexts: list[RagContext]) -> str:
    context_text = "\n\n".join(
        f"[{index}] 标题：{context.item.title}\n来源：{context.item.source.name}\n正文片段：{context.text}"
        for index, context in enumerate(contexts, start=1)
    )
    return (
        "你是校园公开信息问答助手。只允许基于给定资料回答；资料不足时明确说不知道。"
        "回答必须简洁，并在关键结论后标注引用编号，例如 [1]。\n\n"
        f"资料：\n{context_text or '无可用资料'}\n\n问题：{question}\n回答："
    )


def _finish_step_if_running(step: AgentStep | None, status: str, error_message: str) -> None:
    if step is not None and step.status == AgentStep.Status.RUNNING:
        step.finish(status, error_message=error_message)


def estimate_deepseek_usage(prompt: str, max_output_tokens: int) -> UsageEstimate:
    input_tokens = estimate_tokens(prompt)
    output_tokens = max_output_tokens
    cost = estimate_cost_cny(input_tokens, output_tokens)
    remaining = max(Decimal("0"), _daily_budget_cny() - _today_cost_cny())
    allowed = bool(settings.DEEPSEEK_API_KEY) and cost <= remaining and _monthly_budget_allows(cost)
    return UsageEstimate(input_tokens, output_tokens, cost, remaining, allowed)


def estimate_tokens(text: str) -> int:
    compact = re.sub(r"\s+", "", text or "")
    return max(1, len(compact))


def estimate_cost_cny(input_tokens: int, output_tokens: int) -> Decimal:
    usd = (
        Decimal(input_tokens) * _decimal_setting("DEEPSEEK_INPUT_CACHE_MISS_USD_PER_MILLION")
        + Decimal(output_tokens) * _decimal_setting("DEEPSEEK_OUTPUT_USD_PER_MILLION")
    ) / Decimal("1000000")
    return (usd * _decimal_setting("DEEPSEEK_USD_TO_CNY")).quantize(Decimal("0.000001"), ROUND_HALF_UP)


def run_self_heal(dry_run: bool = True, limit: int | None = None) -> dict:
    if not settings.SELF_HEAL_ENABLED:
        return {"enabled": False, "actions": []}
    limit = limit or settings.SELF_HEAL_DAILY_ACTION_LIMIT
    actions = []
    run = AgentRun.objects.create(kind=AgentRun.Kind.SELF_HEAL, trigger="management_command")

    stale_before = timezone.now() - timezone.timedelta(minutes=settings.SELF_HEAL_STALE_JOB_MINUTES)
    stale_jobs = CrawlJob.objects.filter(status=CrawlJob.Status.RUNNING, started_at__lt=stale_before)[:limit]
    for job in stale_jobs:
        actions.append(f"mark stale crawl job {job.id} as failed")
        if not dry_run:
            job.status = CrawlJob.Status.FAILED
            job.error_message = "Marked failed by low-cost self heal after timeout."
            job.finished_at = timezone.now()
            job.save(update_fields=["status", "error_message", "finished_at", "updated_at"])

    due_failures = (
        CrawlFailure.objects.filter(resolved_at__isnull=True, permanent=False)
        .filter(Q(next_retry_at__isnull=True) | Q(next_retry_at__lte=timezone.now()))
        .select_related("source")
        .order_by("source_id", "-created_at")[: max(0, limit - len(actions))]
    )
    seen_sources = set()
    for failure in due_failures:
        if failure.source_id in seen_sources:
            continue
        seen_sources.add(failure.source_id)
        actions.append(f"queue retry for source {failure.source_id}")
        if not dry_run:
            from aggregator.tasks import crawl_source

            crawl_source.delay(failure.source_id)

    missing_chunks = (
        ContentItem.objects.filter(status=ContentItem.Status.PUBLISHED, is_public=True)
        .filter(rag_chunks__isnull=True)
        .count()
    )
    if missing_chunks:
        actions.append(f"rebuild missing rag chunks for {missing_chunks} item(s)")
        if not dry_run:
            rebuild_rag_chunks(limit=min(missing_chunks, 200))

    AgentStep.objects.create(
        run=run,
        name="low_cost_self_heal",
        tool_name="agent.self_heal",
        status=AgentStep.Status.SUCCEEDED,
        output_summary="\n".join(actions[:20]) or "no action needed",
    )
    run.finish(AgentRun.Status.SUCCEEDED, metrics={"dry_run": dry_run, "actions": len(actions)})
    plan = SelfHealPlanSchema(dry_run=dry_run, actions=actions, consumes_llm_budget=False)
    return {"enabled": True, **plan.model_dump()}


def run_agent_eval(record: bool = True) -> dict:
    run = None
    step = None
    if record:
        run = AgentRun.objects.create(kind=AgentRun.Kind.EVAL, trigger="management_command")
        step = AgentStep.objects.create(
            run=run,
            name="retrieval_eval",
            tool_name="agent.eval",
            input_summary=f"{len(AGENT_EVAL_CASES)} fixed campus questions",
        )
    try:
        cases = []
        hit_count = 0
        expected_keyword_hits = 0
        citation_ready_cases = 0
        total_contexts = 0
        for case in AGENT_EVAL_CASES:
            question = case["question"]
            expected_terms = case["expected_terms"]
            contexts = retrieve_contexts(question)
            context_count = len(contexts)
            total_contexts += context_count
            hit = context_count > 0
            hit_count += int(hit)
            joined_text = " ".join(
                f"{context.item.title} {context.item.summary} {context.text}" for context in contexts
            )
            keyword_hit = all(term in joined_text for term in expected_terms) if contexts else False
            expected_keyword_hits += int(keyword_hit)
            citation_ready = any(context.item.canonical_url for context in contexts)
            citation_ready_cases += int(citation_ready)
            cases.append(
                {
                    "question": question,
                    "expected_terms": expected_terms,
                    "context_count": context_count,
                    "hit": hit,
                    "expected_keyword_hit": keyword_hit,
                    "citation_ready": citation_ready,
                    "top_titles": [context.item.title for context in contexts[:3]],
                    "top_sources": [context.item.source.name for context in contexts[:3]],
                }
            )

        case_count = len(AGENT_EVAL_CASES)
        metrics = {
            "case_count": case_count,
            "retrieval_hit_rate": _rate(hit_count, case_count),
            "expected_keyword_hit_rate": _rate(expected_keyword_hits, case_count),
            "citation_coverage_rate": _rate(citation_ready_cases, case_count),
            "average_contexts": round(total_contexts / case_count, 2) if case_count else 0,
            "paid_llm_calls": 0,
            "fallback_rate": 0,
            "total_cost_cny": "0",
        }
        if step is not None:
            step.finish(
                AgentStep.Status.SUCCEEDED,
                output_summary=(
                    f"retrieval_hit_rate={metrics['retrieval_hit_rate']:.2%}; "
                    f"expected_keyword_hit_rate={metrics['expected_keyword_hit_rate']:.2%}"
                ),
            )
        if run is not None:
            run.finish(AgentRun.Status.SUCCEEDED, metrics=metrics)
        return {**metrics, "cases": cases}
    except Exception as exc:
        _finish_step_if_running(step, AgentStep.Status.FAILED, str(exc))
        if run is not None and run.status == AgentRun.Status.RUNNING:
            run.finish(AgentRun.Status.FAILED, error_message=str(exc))
        raise


def _generate_answer(
    prompt: str,
    contexts: list[RagContext],
    estimate: UsageEstimate,
) -> tuple[str, dict, str]:
    if not estimate.allowed:
        return _fallback_answer(contexts), {}, "budget_or_key_unavailable"
    reservation = reserve_deepseek_budget(
        settings.DEEPSEEK_MODEL,
        estimated_prompt_tokens=estimate.input_tokens,
        estimated_completion_tokens=estimate.output_tokens,
    )
    if reservation is None:
        return _fallback_answer(contexts), {}, "daily_budget_exhausted"
    finalized = False
    try:
        payload = _litellm_completion(prompt)
        usage = payload.get("usage", {})
        finalize_deepseek_budget(reservation, usage)
        finalized = True
        return payload["choices"][0]["message"]["content"].strip(), usage, ""
    except Exception:
        if not finalized:
            release_deepseek_budget(reservation)
        return _fallback_answer(contexts), {}, "provider_error"


def _litellm_completion(prompt: str) -> dict:
    try:
        import litellm

        response = litellm.completion(
            model=f"deepseek/{settings.DEEPSEEK_MODEL}",
            messages=[{"role": "user", "content": prompt}],
            api_key=settings.DEEPSEEK_API_KEY,
            api_base=settings.DEEPSEEK_BASE_URL.rstrip("/"),
            temperature=0.2,
            max_tokens=settings.RAG_MAX_OUTPUT_TOKENS,
            timeout=45,
            drop_params=True,
        )
        if hasattr(response, "model_dump"):
            return response.model_dump()
        return dict(response)
    except Exception:
        response = httpx.post(
            f"{settings.DEEPSEEK_BASE_URL.rstrip('/')}/chat/completions",
            headers={"Authorization": f"Bearer {settings.DEEPSEEK_API_KEY}"},
            json={
                "model": settings.DEEPSEEK_MODEL,
                "messages": [{"role": "user", "content": prompt}],
                "temperature": 0.2,
                "max_tokens": settings.RAG_MAX_OUTPUT_TOKENS,
                "thinking": {"type": "disabled"},
            },
            timeout=45,
        )
        response.raise_for_status()
        return response.json()


def _fallback_answer(contexts: list[RagContext], no_paid_model: bool = True) -> str:
    if not contexts:
        return "没有在已发布的公开信息中检索到足够资料，暂时无法回答。"
    lines = ["以下是根据已发布公开信息检索到的相关内容："]
    for index, context in enumerate(contexts[:3], start=1):
        snippet = context.text[:180].strip()
        lines.append(f"[{index}] {context.item.title}：{snippet}")
    if no_paid_model:
        lines.append("以上为检索式回答，未消耗付费模型预算。")
    else:
        lines.append("以上为检索式回答，原模型本次未返回有效文本。")
    return "\n".join(lines)


def _final_usage_values(
    prompt: str,
    answer: str,
    usage_payload: dict,
    estimate: UsageEstimate,
) -> tuple[int, int, Decimal]:
    if usage_payload:
        prompt_tokens = int(usage_payload.get("prompt_tokens") or 0)
        prompt_cache_hit_tokens = int(usage_payload.get("prompt_cache_hit_tokens") or 0)
        prompt_cache_miss_tokens = int(usage_payload.get("prompt_cache_miss_tokens") or 0)
        if prompt_tokens and prompt_cache_hit_tokens == 0 and prompt_cache_miss_tokens == 0:
            prompt_cache_miss_tokens = prompt_tokens
        completion_tokens = int(usage_payload.get("completion_tokens") or 0)
        usd = (
            Decimal(prompt_cache_hit_tokens) * _decimal_setting("DEEPSEEK_INPUT_CACHE_HIT_USD_PER_MILLION")
            + Decimal(prompt_cache_miss_tokens) * _decimal_setting("DEEPSEEK_INPUT_CACHE_MISS_USD_PER_MILLION")
            + Decimal(completion_tokens) * _decimal_setting("DEEPSEEK_OUTPUT_USD_PER_MILLION")
        ) / Decimal("1000000")
        cost = (usd * _decimal_setting("DEEPSEEK_USD_TO_CNY")).quantize(Decimal("0.000001"), ROUND_HALF_UP)
        return prompt_cache_hit_tokens + prompt_cache_miss_tokens, completion_tokens, cost
    return estimate_tokens(prompt), estimate_tokens(answer), Decimal("0")


def _retrieve_contexts_from_meili(query: str, limit: int) -> list[RagContext]:
    if not settings.MEILISEARCH_URL:
        return []
    try:
        import meilisearch
    except ImportError:
        return []
    try:
        client = meilisearch.Client(settings.MEILISEARCH_URL, settings.MEILISEARCH_MASTER_KEY or None)
        result = client.index(settings.MEILISEARCH_RAG_INDEX).search(query, {"limit": limit})
    except Exception:
        return []
    contexts = []
    for hit in result.get("hits", []):
        item_id = hit.get("item_id")
        try:
            item = ContentItem.objects.select_related("source", "category").get(
                id=item_id,
                status=ContentItem.Status.PUBLISHED,
                is_public=True,
            )
        except ContentItem.DoesNotExist:
            continue
        text = hit.get("text", "")
        score = _score_text(query, f"{hit.get('title', '')} {text}")
        if score <= 0:
            continue
        contexts.append(RagContext(chunk=None, item=item, text=text, score=score))
    return sorted(contexts, key=lambda context: context.score, reverse=True)[:limit]


def _retrieve_contexts_from_db(query: str, limit: int) -> list[RagContext]:
    terms = _query_terms(query)
    chunks = ContentChunk.objects.select_related("content_item", "content_item__source", "content_item__category")
    if terms:
        predicate = Q()
        for term in terms[:6]:
            predicate |= Q(text__icontains=term) | Q(content_item__title__icontains=term)
        chunks = chunks.filter(predicate)
    chunks = chunks.filter(content_item__status=ContentItem.Status.PUBLISHED, content_item__is_public=True)[:200]
    ranked = sorted(
        (RagContext(chunk=chunk, item=chunk.content_item, text=chunk.text, score=_score_chunk(query, chunk)) for chunk in chunks),
        key=lambda context: context.score,
        reverse=True,
    )
    if ranked:
        return ranked[:limit]
    fallback_items = (
        ContentItem.objects.filter(status=ContentItem.Status.PUBLISHED, is_public=True)
        .filter(Q(title__icontains=query) | Q(summary__icontains=query) | Q(content_text__icontains=query))
        .select_related("source", "category")[:limit]
    )
    return [RagContext(chunk=None, item=item, text=(item.summary or item.content_text)[: settings.RAG_CHUNK_CHARS]) for item in fallback_items]


def _score_chunk(query: str, chunk: ContentChunk) -> float:
    haystack = f"{chunk.content_item.title} {chunk.text}".lower()
    return _score_text(query, haystack) + (chunk.content_item.importance_score / 1000)


def _score_text(query: str, haystack: str) -> float:
    terms = [term.lower() for term in _query_terms(query)]
    return sum(haystack.lower().count(term) for term in terms)


def _query_terms(query: str) -> list[str]:
    terms = [term for term in re.split(r"\s+", query or "") if term]
    cjk = "".join(re.findall(r"[\u4e00-\u9fff]+", query or ""))
    for size in (2, 3, 4):
        for index in range(0, max(0, len(cjk) - size + 1)):
            terms.append(cjk[index : index + size])
    seen = set()
    unique_terms = []
    for term in terms:
        if term in seen or term in QUERY_STOP_TERMS:
            continue
        seen.add(term)
        unique_terms.append(term)
    return unique_terms[:80]


def _rate(numerator: int, denominator: int) -> float:
    return round(numerator / denominator, 4) if denominator else 0.0


def _chunk_text(text: str, chunk_chars: int, overlap: int) -> list[str]:
    cleaned = re.sub(r"\s+", " ", text).strip()
    if not cleaned:
        return []
    chunks = []
    start = 0
    while start < len(cleaned):
        end = min(len(cleaned), start + chunk_chars)
        chunks.append(cleaned[start:end])
        if end == len(cleaned):
            break
        start = max(end - overlap, start + 1)
    return chunks


def _chunk_to_search_doc(chunk: ContentChunk) -> dict:
    item = chunk.content_item
    return {
        "id": chunk.search_document_id,
        "item_id": item.id,
        "chunk_index": chunk.chunk_index,
        "title": item.title,
        "summary": item.summary,
        "text": chunk.text,
        "source": item.source.name,
        "category": item.category.name if item.category else "",
        "url": item.canonical_url,
        "published_at": item.source_published_at.isoformat() if item.source_published_at else "",
    }


def _stream_chunks(answer: str) -> Iterable[str]:
    for paragraph in answer.splitlines(keepends=True):
        if not paragraph:
            continue
        yield paragraph


def _today_cost_cny() -> Decimal:
    usage = AIUsageDaily.objects.filter(provider="deepseek", usage_date=timezone.localdate()).aggregate(total=Sum("cost_cny"))
    return usage["total"] or Decimal("0")


def _monthly_budget_allows(cost: Decimal) -> bool:
    budget = _decimal_setting("DEEPSEEK_MONTHLY_BUDGET_CNY")
    today = timezone.localdate()
    month_start = today.replace(day=1)
    used = (
        AIUsageDaily.objects.filter(provider="deepseek", usage_date__gte=month_start)
        .aggregate(total=Sum("cost_cny"))
        .get("total")
        or Decimal("0")
    )
    return used + cost <= budget


def _daily_budget_cny() -> Decimal:
    return _decimal_setting("DEEPSEEK_DAILY_BUDGET_CNY")


def _decimal_setting(name: str) -> Decimal:
    return Decimal(str(getattr(settings, name))).quantize(Decimal("0.000001"), ROUND_HALF_UP)


def sse_event(payload: dict) -> str:
    return f"data: {json.dumps(payload, ensure_ascii=False)}\n\n"
