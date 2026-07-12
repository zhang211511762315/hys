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


class DiagnoseSourceInput(BaseModel):
    source_id: int = Field(gt=0)


class DiagnoseSourceOutput(BaseModel):
    source_id: int
    enabled: bool
    failure_count: int
    open_failures: int
    healthy: bool


class ReindexItemsInput(BaseModel):
    item_ids: list[int] = Field(min_length=1, max_length=100)


class ReindexItemsOutput(BaseModel):
    queued_item_ids: list[int]


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
    registry.register(
        ToolSpec(
            name="diagnose_source",
            version="1",
            input_model=DiagnoseSourceInput,
            output_model=DiagnoseSourceOutput,
            risk_level=RiskLevel.HIGH,
            permission=ToolPermission.STAFF,
            timeout_seconds=5,
            max_retries=0,
            idempotent=True,
            executor=_diagnose_source,
        )
    )
    registry.register(
        ToolSpec(
            name="reindex_items",
            version="1",
            input_model=ReindexItemsInput,
            output_model=ReindexItemsOutput,
            risk_level=RiskLevel.HIGH,
            permission=ToolPermission.STAFF,
            timeout_seconds=10,
            max_retries=0,
            idempotent=True,
            executor=_reindex_items,
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


def _diagnose_source(payload: DiagnoseSourceInput, _context: ToolContext) -> dict:
    from aggregator.models import CrawlFailure

    source = Source.objects.get(id=payload.source_id)
    open_failures = CrawlFailure.objects.filter(source=source, resolved_at__isnull=True).count()
    return {
        "source_id": source.id,
        "enabled": source.enabled and source.crawl_enabled,
        "failure_count": source.failure_count,
        "open_failures": open_failures,
        "healthy": bool(source.enabled and source.crawl_enabled and source.failure_count == 0 and open_failures == 0),
    }


def _reindex_items(payload: ReindexItemsInput, _context: ToolContext) -> dict:
    from agent_runtime.tasks import index_content_item_rag

    item_ids = list(dict.fromkeys(payload.item_ids))
    for item_id in item_ids:
        index_content_item_rag.delay(item_id)
    return {"queued_item_ids": item_ids}
