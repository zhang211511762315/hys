from celery import shared_task

from .models import AgentRun
from .research.runtime import execute_research_run


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
