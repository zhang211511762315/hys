from celery import shared_task
from django.utils import timezone

from .models import AgentRun
from .research.runtime import execute_research_run, finish_cancellation, append_event
from .services import cleanup_expired_memory, cleanup_stale_research_admission_keys, upsert_rag_chunks_for_item


@shared_task(
    bind=True,
    acks_late=True,
    reject_on_worker_lost=True,
    soft_time_limit=90,
    time_limit=100,
)
def execute_research_run_task(self, public_id: str):
    run = AgentRun.objects.get(public_id=public_id)
    active = [AgentRun.Status.PLANNING, AgentRun.Status.EXECUTING, AgentRun.Status.VERIFYING,
              AgentRun.Status.RUNNING, AgentRun.Status.CANCELLING]
    if run.status in active:
        delivery = getattr(self.request, "delivery_info", {}) or {}
        if delivery.get("redelivered") or self.request.retries:
            # Hard task limit is 100s. Never repeat an uncertain paid operation.
            started = (run.dispatch_meta or {}).get("execution_started")
            if started is None:
                return {"status": run.status, "recovery": "manual_review"}
            remaining = 130 - (timezone.now().timestamp() - started)
            if remaining > 0:
                raise self.retry(countdown=remaining + 1, max_retries=3)
            if run.status == AgentRun.Status.CANCELLING:
                return finish_cancellation(run)
            terminal = AgentRun.Status.FAILED
            changed = AgentRun.objects.filter(pk=run.pk, status=run.status).update(
                status=terminal, error_message="worker interrupted; explicit retry required", finished_at=timezone.now())
            if changed:
                append_event(run, "run.failed", {"message": "worker interrupted; explicit retry required"})
            return {"status": terminal}
        return {"status": run.status}
    return execute_research_run(run.id)


@shared_task(
    autoretry_for=(Exception,),
    retry_backoff=True,
    retry_jitter=True,
    retry_kwargs={"max_retries": 3},
    acks_late=True,
    reject_on_worker_lost=True,
    soft_time_limit=60,
    time_limit=75,
)
def index_content_item_rag(item_id: int):
    return upsert_rag_chunks_for_item(item_id)


@shared_task
def cleanup_expired_memory_task():
    result = cleanup_expired_memory()
    result["admission_key_deleted"] = cleanup_stale_research_admission_keys()
    return result
