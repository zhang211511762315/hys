import asyncio
import json
import math
import time

from django.conf import settings
from django.core.cache import cache
from django.db.models import Count, Sum
from django.http import HttpResponse, JsonResponse, StreamingHttpResponse
from django.shortcuts import render
from django.utils import timezone
from django.views.decorators.http import require_GET, require_POST

from aggregator.models import AIUsageDaily, ContentItem, CrawlFailure, Source

from .models import AgentRun, ContentChunk, LLMUsageEvent, RagMessage, RagSession, ToolInvocation
from .research.runtime import cancel_research_run, create_research_run
from .research.schemas import CreateResearchRunInput
from .services import answer_question_events, new_session_key, sse_event
from .tasks import execute_research_run_task

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
def research(request):
    return render(request, "agent_runtime/research.html")


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
    tool_durations = list(
        ToolInvocation.objects.filter(status=ToolInvocation.Status.SUCCEEDED, duration_ms__gt=0)
        .order_by("duration_ms")
        .values_list("duration_ms", flat=True)[:5000]
    )
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
            "tool_latency_p50_ms": _percentile(tool_durations, 0.50),
            "tool_latency_p95_ms": _percentile(tool_durations, 0.95),
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


@require_POST
def research_runs(request):
    try:
        payload = CreateResearchRunInput.model_validate_json(request.body)
    except Exception:
        return JsonResponse({"error": "invalid request"}, status=400)
    existing = AgentRun.objects.filter(client_request_id=payload.client_request_id).first()
    if existing is not None:
        run, created = existing, False
    else:
        client_ip = _client_ip(request)
        if not _consume_daily_research_quota(client_ip):
            return JsonResponse({"error": "daily limit exceeded"}, status=429)
        active_statuses = [
            AgentRun.Status.QUEUED,
            AgentRun.Status.PLANNING,
            AgentRun.Status.EXECUTING,
            AgentRun.Status.VERIFYING,
            AgentRun.Status.RUNNING,
        ]
        if AgentRun.objects.filter(trigger=f"research_api:{client_ip}", status__in=active_statuses).count() >= settings.RESEARCH_AGENT_CONCURRENT_LIMIT:
            return JsonResponse({"error": "concurrent limit exceeded"}, status=429)
        run, created = create_research_run(payload.goal, payload.client_request_id)
        run.trigger = f"research_api:{client_ip}"
        run.save(update_fields=["trigger", "updated_at"])
    if created:
        execute_research_run_task.delay(str(run.public_id))
    return JsonResponse(
        {
            "run_id": str(run.public_id),
            "status": run.status,
            "events_url": f"/api/v1/research-runs/{run.public_id}/events",
        },
        status=202 if created else 200,
    )


@require_POST
def cancel_research_run_view(request, run_id):
    run = AgentRun.objects.filter(public_id=run_id).first()
    if run is None:
        return JsonResponse({"error": "not found"}, status=404)
    cancelled = cancel_research_run(run)
    run.refresh_from_db()
    return JsonResponse({"run_id": str(run.public_id), "status": run.status, "cancelled": cancelled})


@require_GET
def research_run_detail(request, run_id):
    run = AgentRun.objects.filter(public_id=run_id).first()
    if run is None:
        return JsonResponse({"error": "not found"}, status=404)
    return JsonResponse(
        {
            "run_id": str(run.public_id),
            "status": run.status,
            "current_node": run.current_node,
            "answer": (run.state_json or {}).get("answer"),
            "metrics": run.metrics_json,
        }
    )


@require_GET
def research_run_events(request, run_id):
    run = AgentRun.objects.filter(public_id=run_id).first()
    if run is None:
        return JsonResponse({"error": "not found"}, status=404)
    try:
        after = max(0, int(request.headers.get("Last-Event-ID") or request.GET.get("after") or 0))
    except ValueError:
        after = 0

    snapshot_only = request.GET.get("snapshot") == "1"

    def stream():
        last_sequence = after
        deadline = time.monotonic() + 105
        terminal = {AgentRun.Status.SUCCEEDED, AgentRun.Status.FAILED, AgentRun.Status.CANCELLED}
        while True:
            events = list(run.events.filter(sequence__gt=last_sequence).order_by("sequence")[:100])
            for event in events:
                last_sequence = event.sequence
                yield f"id: {event.sequence}\nevent: {event.event_type}\ndata: {json.dumps(event.payload_json, ensure_ascii=False)}\n\n"
            current_status = AgentRun.objects.filter(id=run.id).values_list("status", flat=True).first()
            if snapshot_only or (current_status in terminal and not events) or time.monotonic() >= deadline:
                break
            if not events:
                time.sleep(0.25)

    response = StreamingHttpResponse(stream(), content_type="text/event-stream; charset=utf-8")
    response["Cache-Control"] = "no-cache"
    response["X-Accel-Buffering"] = "no"
    return response


def _client_ip(request) -> str:
    forwarded = request.META.get("HTTP_X_FORWARDED_FOR", "")
    if forwarded:
        return forwarded.split(",", 1)[0].strip()[:64]
    return (request.META.get("REMOTE_ADDR") or "unknown")[:64]


def _consume_daily_research_quota(client_ip: str) -> bool:
    limit = max(0, int(settings.RESEARCH_AGENT_DAILY_LIMIT))
    if limit == 0:
        return False
    key = f"research-agent:daily:{timezone.localdate().isoformat()}:{client_ip}"
    if cache.add(key, 1, timeout=60 * 60 * 26):
        return True
    count = cache.incr(key)
    if count <= limit:
        return True
    try:
        cache.decr(key)
    except ValueError:
        pass
    return False


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


def _percentile(values: list[int], percentile: float) -> int:
    if not values:
        return 0
    index = max(0, min(len(values) - 1, math.ceil(len(values) * percentile) - 1))
    return int(values[index])
