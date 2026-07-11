from celery import shared_task

from .models import AgentRun
from .research.runtime import execute_research_run
from .services import upsert_rag_chunks_for_item


@shared_task(
    bind=True,
    acks_late=True,
    reject_on_worker_lost=True,
    soft_time_limit=90,
    time_limit=100,
)
def execute_research_run_task(self, public_id: str):
    run = AgentRun.objects.get(public_id=public_id)
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
