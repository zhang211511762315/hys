import asyncio
import json
import math
import time

from django.conf import settings
from django.contrib.auth import login, logout
from django.contrib.auth.decorators import login_required
from django.contrib.auth.forms import PasswordChangeForm
from django.core.cache import cache
from django.db import connection
from django.db.models import Count, Max, Sum
from django.http import HttpResponse, JsonResponse, StreamingHttpResponse
from django.shortcuts import redirect, render
from django.utils import timezone
from django.views.decorators.http import require_GET, require_http_methods, require_POST

from aggregator.models import AIUsageDaily, ContentItem, CrawlFailure, Source

from .forms import SignupForm
from .models import (
    AgentRun,
    ContentChunk,
    EvaluationRun,
    LLMUsageEvent,
    MemoryEntry,
    RagMessage,
    RagSession,
    ToolInvocation,
)
from .evaluation.runner import evaluate_promotion_gate
from .evaluation.strategies import MULTI_AGENT_EXPERIMENTAL, SINGLE_AGENT
from .research.runtime import cancel_research_run, create_research_run, replay_research_run
from .research.schemas import CreateResearchRunInput
from .services import answer_question_events, cleanup_expired_memory, new_session_key, save_explicit_memory, sse_event
from .tasks import execute_research_run_task
from zhongbei_info.observability import log_legacy_rag_runtime_created

RAG_SESSION_COOKIE = "rag_session_key"
RAG_SESSION_COOKIE_MAX_AGE = 60 * 60 * 24 * 30


@require_GET
def ask(request):
    user = request.user if request.user.is_authenticated else None
    if request.GET.get("new") == "1":
        session_key = new_session_key()
    else:
        session_key = request.GET.get("session") or request.COOKIES.get(RAG_SESSION_COOKIE) or new_session_key()

    current_session = RagSession.objects.filter(session_key=session_key, user=user).first()
    if user is not None and current_session is None:
        session_key = new_session_key()
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


@require_POST
async def ask_stream(request):
    try:
        payload = json.loads(request.body or "{}")
    except (TypeError, ValueError):
        payload = {}
    question = str(payload.get("question", "")).strip()
    session_key = str(payload.get("session", "")).strip() or None
    if not question:
        return JsonResponse({"error": "missing question"}, status=400)

    def next_payload(iterator):
        try:
            return next(iterator)
        except StopIteration:
            return None

    async def stream():
        def on_run_created(run):
            request.agent_run_id = str(run.public_id)
            log_legacy_rag_runtime_created(request.request_id, request.agent_run_id)

        try:
            iterator = answer_question_events(
                question,
                session_key,
                user=request.user if request.user.is_authenticated else None,
                request_id=request.request_id,
                on_run_created=on_run_created,
            )
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


@require_http_methods(["GET", "POST"])
def signup(request):
    if request.user.is_authenticated:
        return redirect("agent_runtime:account_privacy")
    form = SignupForm(request.POST or None)
    if request.method == "POST" and form.is_valid():
        user = form.save()
        login(request, user)
        return redirect("agent_runtime:account_privacy")
    return render(request, "agent_runtime/signup.html", {"form": form})


@require_POST
def account_logout(request):
    logout(request)
    return redirect("aggregator:home")


@login_required
@require_http_methods(["GET", "POST"])
def account_password_change(request):
    form = PasswordChangeForm(request.user, request.POST or None)
    if request.method == "POST" and form.is_valid():
        user = form.save()
        login(request, user)
        return redirect("agent_runtime:account_privacy")
    return render(request, "agent_runtime/password_change.html", {"form": form})


@login_required
@require_GET
def account_privacy(request):
    return render(
        request,
        "agent_runtime/account_privacy.html",
        {
            "memories": MemoryEntry.objects.filter(user=request.user),
            "sessions": RagSession.objects.filter(user=request.user).order_by("-updated_at")[:20],
            "memory_retention_days": settings.MEMORY_RETENTION_DAYS,
        },
    )


@login_required
@require_POST
def account_memory_save(request):
    session_key = str(request.POST.get("session", "")).strip()
    session = RagSession.objects.filter(session_key=session_key, user=request.user).first() if session_key else None
    try:
        save_explicit_memory(request.user, request.POST.get("content", ""), source_session=session)
    except ValueError:
        return redirect("agent_runtime:account_privacy")
    return redirect("agent_runtime:account_privacy")


@login_required
@require_GET
def account_memory_export(request):
    memories = MemoryEntry.objects.filter(user=request.user).order_by("-created_at")
    payload = {
        "memories": [
            {
                "id": str(memory.public_id),
                "content": memory.content,
                "consented_at": memory.consented_at.isoformat(),
                "expires_at": memory.expires_at.isoformat(),
            }
            for memory in memories
        ]
    }
    response = HttpResponse(json.dumps(payload, ensure_ascii=False), content_type="application/json")
    response["Content-Disposition"] = 'attachment; filename="memory-export.json"'
    response["Cache-Control"] = "no-store, private"
    return response


@login_required
@require_POST
def account_memory_delete(request, memory_id):
    deleted, _ = MemoryEntry.objects.filter(public_id=memory_id, user=request.user).delete()
    if not deleted:
        return HttpResponse(status=404)
    return redirect("agent_runtime:account_privacy")


@login_required
@require_POST
def account_delete(request):
    user = request.user
    logout(request)
    user.delete()
    return redirect("aggregator:home")


def _memory_user_or_error(request):
    if request.user.is_authenticated:
        return request.user, None
    return None, JsonResponse({"error": "authentication required"}, status=403)


@require_http_methods(["GET", "POST"])
def memory_collection(request):
    user, error = _memory_user_or_error(request)
    if error:
        return error
    if request.method == "GET":
        memories = [
            {"id": str(memory.public_id), "content": memory.content}
            for memory in MemoryEntry.objects.filter(user=user)
        ]
        return JsonResponse({"memories": memories})
    try:
        payload = json.loads(request.body or "{}")
        content = str(payload.get("content", ""))
        session_key = str(payload.get("session", ""))
    except (TypeError, ValueError):
        return JsonResponse({"error": "invalid request"}, status=400)
    session = RagSession.objects.filter(session_key=session_key, user=user).first() if session_key else None
    try:
        memory = save_explicit_memory(user, content, source_session=session)
    except ValueError:
        return JsonResponse({"error": "memory content is required"}, status=400)
    return JsonResponse({"id": str(memory.public_id), "content": memory.content}, status=201)


@require_http_methods(["DELETE"])
def memory_detail(request, memory_id):
    user, error = _memory_user_or_error(request)
    if error:
        return error
    deleted, _ = MemoryEntry.objects.filter(public_id=memory_id, user=user).delete()
    if not deleted:
        return JsonResponse({"error": "not found"}, status=404)
    return HttpResponse(status=204)


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
    latest_evalops_comparison = _latest_evalops_comparison()
    latest_self_heal = AgentRun.objects.filter(kind=AgentRun.Kind.SELF_HEAL).order_by("-created_at").first()
    tool_durations = list(
        ToolInvocation.objects.filter(status=ToolInvocation.Status.SUCCEEDED, duration_ms__gt=0)
        .order_by("duration_ms")
        .values_list("duration_ms", flat=True)[:5000]
    )
    latest_public_item_at = ContentItem.objects.filter(
        status=ContentItem.Status.PUBLISHED,
        is_public=True,
    ).aggregate(value=Max("source_published_at"))["value"]
    last_crawl_success_at = Source.objects.aggregate(value=Max("last_success_at"))["value"]
    actionable_failures = CrawlFailure.objects.filter(resolved_at__isnull=True, acknowledged_at__isnull=True)
    failure_breakdown = dict(
        actionable_failures
        .values("failure_class")
        .annotate(count=Count("id"))
        .values_list("failure_class", "count")
    )
    open_failure_count = CrawlFailure.objects.filter(resolved_at__isnull=True).count()
    actionable_failure_count = actionable_failures.count()
    acknowledged_permanent_failure_count = CrawlFailure.objects.filter(
        resolved_at__isnull=True,
        acknowledged_at__isnull=False,
        failure_class=CrawlFailure.FailureClass.PERMANENT,
        permanent=True,
        acknowledged_status__in=[404, 410],
    ).count()
    latest_eval_metrics = _display_eval_metrics(latest_eval.metrics_json if latest_eval else {})
    return render(
        request,
        "agent_runtime/agent_dashboard.html",
        {
            "source_count": Source.objects.count(),
            "published_count": ContentItem.objects.filter(status=ContentItem.Status.PUBLISHED, is_public=True).count(),
            "chunk_count": ContentChunk.objects.count(),
            "retry_queue_count": actionable_failure_count,
            "open_failure_count": open_failure_count,
            "actionable_failure_count": actionable_failure_count,
            "acknowledged_permanent_failure_count": acknowledged_permanent_failure_count,
            "usage_today": usage_today,
            "usage_total": usage_total,
            "runs_by_kind": runs_by_kind,
            "latest_runs": latest_runs,
            "latest_usage": latest_usage,
            "latest_eval": latest_eval,
            "latest_eval_metrics": latest_eval_metrics,
            "latest_evalops_comparison": latest_evalops_comparison,
            "latest_self_heal": latest_self_heal,
            "daily_budget_cny": settings.DEEPSEEK_DAILY_BUDGET_CNY,
            "monthly_budget_cny": settings.DEEPSEEK_MONTHLY_BUDGET_CNY,
            "tool_latency_p50_ms": _percentile(tool_durations, 0.50),
            "tool_latency_p95_ms": _percentile(tool_durations, 0.95),
            "latest_public_item_at": latest_public_item_at,
            "last_crawl_success_at": last_crawl_success_at,
            "failure_breakdown": failure_breakdown,
        },
    )


@require_GET
def healthz(request):
    latest_public_item_at = ContentItem.objects.filter(
        status=ContentItem.Status.PUBLISHED,
        is_public=True,
    ).aggregate(value=Max("source_published_at"))["value"]
    last_crawl_success_at = Source.objects.aggregate(value=Max("last_success_at"))["value"]
    now = timezone.now()
    open_failures = CrawlFailure.objects.filter(resolved_at__isnull=True).count()
    actionable_failures = CrawlFailure.objects.filter(resolved_at__isnull=True, acknowledged_at__isnull=True).count()
    acknowledged_permanent_failures = CrawlFailure.objects.filter(
        resolved_at__isnull=True,
        acknowledged_at__isnull=False,
        failure_class=CrawlFailure.FailureClass.PERMANENT,
        permanent=True,
        acknowledged_status__in=[404, 410],
    ).count()
    alerts = []
    if last_crawl_success_at is None or last_crawl_success_at < now - timezone.timedelta(hours=settings.SOURCE_FRESHNESS_HOURS):
        alerts.append("crawl_stale")
    if actionable_failures > settings.SOURCE_OPEN_FAILURE_THRESHOLD:
        alerts.append("open_failures")
    payload = {
        "ok": True,
        "time": now.isoformat(),
        "published_items": ContentItem.objects.filter(status=ContentItem.Status.PUBLISHED, is_public=True).count(),
        "rag_chunks": ContentChunk.objects.count(),
        "open_failures": open_failures,
        "actionable_failures": actionable_failures,
        "acknowledged_permanent_failures": acknowledged_permanent_failures,
        "latest_public_item_at": latest_public_item_at.isoformat() if latest_public_item_at else None,
        "last_crawl_success_at": last_crawl_success_at.isoformat() if last_crawl_success_at else None,
        "source_health_ok": not alerts,
        "source_health_alerts": alerts,
    }
    return JsonResponse(payload)


@require_GET
def readyz(request):
    try:
        connection.ensure_connection()
        cache.set("readiness:probe", "ok", timeout=5)
        if cache.get("readiness:probe") != "ok":
            raise RuntimeError("cache probe failed")
    except Exception:
        return JsonResponse({"ok": False}, status=503)
    return JsonResponse({"ok": True})


@require_GET
def internal_metrics(request):
    remote_addr = request.META.get("REMOTE_ADDR", "")
    internal_proxy = request.META.get("HTTP_X_INTERNAL_METRICS") == "1"
    if remote_addr not in {"127.0.0.1", "::1"} and not internal_proxy:
        return HttpResponse(status=404)
    published_items = ContentItem.objects.filter(status=ContentItem.Status.PUBLISHED, is_public=True).count()
    open_failures = CrawlFailure.objects.filter(resolved_at__isnull=True).count()
    actionable_failures = CrawlFailure.objects.filter(resolved_at__isnull=True, acknowledged_at__isnull=True).count()
    acknowledged_permanent_failures = CrawlFailure.objects.filter(
        resolved_at__isnull=True,
        acknowledged_at__isnull=False,
        failure_class=CrawlFailure.FailureClass.PERMANENT,
        permanent=True,
        acknowledged_status__in=[404, 410],
    ).count()
    lines = [
        "# HELP hys_published_items Number of public content items.",
        "# TYPE hys_published_items gauge",
        f"hys_published_items {published_items}",
        "# HELP hys_rag_chunks Number of indexed RAG chunks.",
        "# TYPE hys_rag_chunks gauge",
        f"hys_rag_chunks {ContentChunk.objects.count()}",
        "# HELP hys_open_crawl_failures Number of unresolved crawl failures.",
        "# TYPE hys_open_crawl_failures gauge",
        f"hys_open_crawl_failures {open_failures}",
        "# HELP hys_actionable_crawl_failures Number of unresolved, unacknowledged crawl failures.",
        "# TYPE hys_actionable_crawl_failures gauge",
        f"hys_actionable_crawl_failures {actionable_failures}",
        "# HELP hys_acknowledged_permanent_crawl_failures Number of acknowledged permanent HTTP failures.",
        "# TYPE hys_acknowledged_permanent_crawl_failures gauge",
        f"hys_acknowledged_permanent_crawl_failures {acknowledged_permanent_failures}",
    ]
    return HttpResponse("\n".join(lines) + "\n", content_type="text/plain; version=0.0.4; charset=utf-8")


@require_POST
def research_runs(request):
    try:
        payload = CreateResearchRunInput.model_validate_json(request.body)
    except Exception:
        return JsonResponse({"error": "invalid request"}, status=400)
    client_ip = _client_ip(request)
    existing = AgentRun.objects.filter(client_request_id=payload.client_request_id).first()
    if existing is None:
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
    run, created = create_research_run(
        payload.goal,
        payload.client_request_id,
        request_id=request.request_id,
    )
    if created:
        run.trigger = f"research_api:{client_ip}"
        run.save(update_fields=["trigger", "updated_at"])
    request.agent_run_id = str(run.public_id)
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
    request.agent_run_id = str(run.public_id)
    cancelled = cancel_research_run(run)
    run.refresh_from_db()
    return JsonResponse({"run_id": str(run.public_id), "status": run.status, "cancelled": cancelled})


@require_POST
def replay_research_run_view(request, run_id):
    source = AgentRun.objects.filter(public_id=run_id).first()
    if source is None:
        return JsonResponse({"error": "not found"}, status=404)
    replay = replay_research_run(source, request_id=request.request_id)
    request.agent_run_id = str(replay.public_id)
    execute_research_run_task.delay(str(replay.public_id))
    return JsonResponse(
        {
            "run_id": str(replay.public_id),
            "source_run_id": str(source.public_id),
            "status": replay.status,
            "events_url": f"/api/v1/research-runs/{replay.public_id}/events",
        },
        status=202,
    )


@require_GET
def research_run_detail(request, run_id):
    run = AgentRun.objects.filter(public_id=run_id).first()
    if run is None:
        return JsonResponse({"error": "not found"}, status=404)
    request.agent_run_id = str(run.public_id)
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
    request.agent_run_id = str(run.public_id)
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


def _latest_evalops_comparison() -> dict | None:
    latest_run = (
        EvaluationRun.objects.filter(comparison_id__isnull=False)
        .order_by("-created_at", "-id")
        .first()
    )
    if latest_run is None:
        return None

    runs = list(
        EvaluationRun.objects.filter(comparison_id=latest_run.comparison_id).order_by("id")
    )
    if len(runs) != 2:
        return _not_ready_evalops_comparison(latest_run)

    runs_by_strategy = {run.strategy: run for run in runs}
    if (
        len(runs_by_strategy) != 2
        or set(runs_by_strategy) != {SINGLE_AGENT, MULTI_AGENT_EXPERIMENTAL}
    ):
        return _not_ready_evalops_comparison(latest_run)

    baseline = runs_by_strategy[SINGLE_AGENT]
    candidate = runs_by_strategy[MULTI_AGENT_EXPERIMENTAL]
    if (
        baseline.status != EvaluationRun.Status.SUCCEEDED
        or candidate.status != EvaluationRun.Status.SUCCEEDED
        or baseline.dataset_version != candidate.dataset_version
        or baseline.mode != candidate.mode
    ):
        return _not_ready_evalops_comparison(latest_run)

    promotion = evaluate_promotion_gate(baseline.metrics_json or {}, candidate.metrics_json or {})
    if {
        "invalid_baseline_metrics",
        "invalid_candidate_metrics",
        "case_count_mismatch",
    }.intersection(promotion["reasons"]):
        return _not_ready_evalops_comparison(latest_run)

    return {
        "comparison_id": str(latest_run.comparison_id),
        "dataset_version": baseline.dataset_version,
        "ready": True,
        "promotion": promotion,
        "baseline": _display_evalops_strategy_metrics(baseline.metrics_json or {}),
        "candidate": _display_evalops_strategy_metrics(candidate.metrics_json or {}),
    }


def _not_ready_evalops_comparison(latest_run: EvaluationRun) -> dict:
    return {
        "comparison_id": str(latest_run.comparison_id),
        "dataset_version": latest_run.dataset_version,
        "ready": False,
        "promotion": {
            "status": "blocked",
            "eligible": False,
            "reasons": ["comparison_not_ready"],
            "p95_latency_limit_ms": None,
        },
    }


def _display_evalops_strategy_metrics(metrics: dict) -> dict:
    def percent(key: str) -> str:
        try:
            return f"{float(metrics.get(key, 0)) * 100:.1f}%"
        except (TypeError, ValueError):
            return "0.0%"

    return {
        "plan_valid_rate": percent("plan_valid_rate"),
        "tool_selection_accuracy": percent("tool_selection_accuracy"),
        "unsafe_tool_selection_count": metrics.get("unsafe_tool_selection_count", 0),
        "total_cost_cny": metrics.get("total_cost_cny", "0"),
        "p95_latency_ms": metrics.get("p95_latency_ms", 0),
    }


def _percentile(values: list[int], percentile: float) -> int:
    if not values:
        return 0
    index = max(0, min(len(values) - 1, math.ceil(len(values) * percentile) - 1))
    return int(values[index])
