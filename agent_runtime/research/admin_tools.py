from __future__ import annotations

from pydantic import BaseModel, Field
from django.db import transaction

from aggregator.models import CrawlJob, Source
from aggregator.tasks import crawl_source

from .tools import RiskLevel, ToolContext, ToolPermission, ToolSpec, build_default_registry


class RetrySourceInput(BaseModel):
    source_id: int = Field(gt=0)


class RetrySourceOutput(BaseModel):
    queued: bool
    job_id: int


def build_admin_registry():
    registry = build_default_registry()
    registry.register(
        ToolSpec(
            name="retry_source",
            version="1",
            input_model=RetrySourceInput,
            output_model=RetrySourceOutput,
            risk_level=RiskLevel.HIGH,
            permission=ToolPermission.STAFF,
            timeout_seconds=10,
            max_retries=0,
            idempotent=True,
            executor=_retry_source,
        )
    )
    return registry


def _retry_source(payload: RetrySourceInput, _context: ToolContext) -> dict:
    with transaction.atomic():
        source = Source.objects.select_for_update().get(id=payload.source_id)
        job = (
            CrawlJob.objects.filter(
                source=source,
                status__in=[CrawlJob.Status.QUEUED, CrawlJob.Status.RUNNING],
            )
            .order_by("created_at")
            .first()
        )
        if job is not None:
            return {"queued": False, "job_id": job.id}
        job = CrawlJob.objects.create(
            source=source,
            target_url=source.url,
            status=CrawlJob.Status.QUEUED,
        )
    crawl_source.delay(source.id)
    return {"queued": True, "job_id": job.id}
