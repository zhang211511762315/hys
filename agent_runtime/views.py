import asyncio

from django.conf import settings
from django.db.models import Count, Sum
from django.http import HttpResponse, JsonResponse, StreamingHttpResponse
from django.shortcuts import render
from django.utils import timezone
from django.views.decorators.http import require_GET

from aggregator.models import AIUsageDaily, ContentItem, CrawlFailure, Source

from .models import AgentRun, ContentChunk, LLMUsageEvent, RagMessage, RagSession
from .services import answer_question_events, new_session_key, sse_event

RAG_SESSION_COOKIE = "rag_session_key"
RAG_SESSION_COOKIE_MAX_AGE = 60 * 60 * 24 * 30


@require_GET
def ask(request):
    if request.GET.get("new") == "1":
        session_key = new_session_key()
    else:
        session_key = request.GET.get("session") or request.COOKIES.get(RAG_SESSION_COOKIE) or new_session_key()

    current_session = RagSession.objects.filter(session_key=session_key).first()
    history_messages = []
    history_questions = []
    if current_session is not None:
        history_messages = list(current_session.messages.order_by("created_at")[:100])
        history_questions = [
            message for message in history_messages if message.role == RagMessage.Role.USER
        ]

    response = render(
        request,
        "agent_runtime/ask.html",
        {
            "session_key": session_key,
            "current_session": current_session,
            "history_messages": history_messages,
            "history_questions": history_questions,
            "daily_budget_cny": settings.DEEPSEEK_DAILY_BUDGET_CNY,
        },
    )
    response.set_cookie(
        RAG_SESSION_COOKIE,
        session_key,
        max_age=RAG_SESSION_COOKIE_MAX_AGE,
        samesite="Lax",
    )
    return response


@require_GET
async def ask_stream(request):
    question = request.GET.get("q", "").strip()
    session_key = request.GET.get("session", "").strip() or None
    if not question:
        return JsonResponse({"error": "missing question"}, status=400)

    def next_payload(iterator):
        try:
            return next(iterator)
        except StopIteration:
            return None

    async def stream():
        try:
            iterator = answer_question_events(question, session_key)
        except Exception:
            yield sse_event({"type": "error", "message": "问答生成中断，请稍后重试或换个问法。"})
            yield sse_event({"type": "done"})
            return
        while True:
            try:
                payload = await asyncio.to_thread(next_payload, iterator)
            except Exception:
                yield sse_event({"type": "error", "message": "问答生成中断，请稍后重试或换个问法。"})
                yield sse_event({"type": "done"})
                return
            if payload is None:
                break
            yield sse_event(payload)

    response = StreamingHttpResponse(stream(), content_type="text/event-stream; charset=utf-8")
    response["Cache-Control"] = "no-cache"
    response["X-Accel-Buffering"] = "no"
    return response


@require_GET
def agent_dashboard(request):
    today = timezone.localdate()
    usage_today = (
        AIUsageDaily.objects.filter(provider="deepseek", usage_date=today)
        .aggregate(cost=Sum("cost_cny"), requests=Sum("request_count"))
    )
    usage_total = AIUsageDaily.objects.filter(provider="deepseek").aggregate(
        cost=Sum("cost_cny"),
        requests=Sum("request_count"),
    )
    runs_by_kind = AgentRun.objects.values("kind").annotate(count=Count("id")).order_by("kind")
    latest_runs = AgentRun.objects.prefetch_related("steps").order_by("-created_at")[:10]
    latest_usage = LLMUsageEvent.objects.order_by("-created_at")[:10]
    latest_eval = AgentRun.objects.filter(kind=AgentRun.Kind.EVAL).order_by("-created_at").first()
    latest_self_heal = AgentRun.objects.filter(kind=AgentRun.Kind.SELF_HEAL).order_by("-created_at").first()
    open_failure_count = CrawlFailure.objects.filter(resolved_at__isnull=True).count()
    latest_eval_metrics = _display_eval_metrics(latest_eval.metrics_json if latest_eval else {})
    return render(
        request,
        "agent_runtime/agent_dashboard.html",
        {
            "source_count": Source.objects.count(),
            "published_count": ContentItem.objects.filter(status=ContentItem.Status.PUBLISHED, is_public=True).count(),
            "chunk_count": ContentChunk.objects.count(),
            "retry_queue_count": open_failure_count,
            "open_failure_count": open_failure_count,
            "usage_today": usage_today,
            "usage_total": usage_total,
            "runs_by_kind": runs_by_kind,
            "latest_runs": latest_runs,
            "latest_usage": latest_usage,
            "latest_eval": latest_eval,
            "latest_eval_metrics": latest_eval_metrics,
            "latest_self_heal": latest_self_heal,
            "daily_budget_cny": settings.DEEPSEEK_DAILY_BUDGET_CNY,
            "monthly_budget_cny": settings.DEEPSEEK_MONTHLY_BUDGET_CNY,
        },
    )


@require_GET
def healthz(request):
    payload = {
        "ok": True,
        "time": timezone.now().isoformat(),
        "published_items": ContentItem.objects.filter(status=ContentItem.Status.PUBLISHED, is_public=True).count(),
        "rag_chunks": ContentChunk.objects.count(),
        "open_failures": CrawlFailure.objects.filter(resolved_at__isnull=True).count(),
    }
    return JsonResponse(payload)


def _display_eval_metrics(metrics: dict) -> dict:
    def percent(key: str) -> str:
        try:
            return f"{float(metrics.get(key, 0)) * 100:.1f}%"
        except (TypeError, ValueError):
            return "0.0%"

    return {
        "retrieval_hit_rate": percent("retrieval_hit_rate"),
        "expected_keyword_hit_rate": percent("expected_keyword_hit_rate"),
        "paid_llm_calls": metrics.get("paid_llm_calls", 0),
    }
