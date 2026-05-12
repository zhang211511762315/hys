from datetime import timedelta

from celery import shared_task
from django.utils import timezone

from .models import CrawlJob, Source
from .services.pipeline import ingest_source


@shared_task
def crawl_source(source_id: int):
    source = Source.objects.get(id=source_id)
    job = CrawlJob.objects.create(source=source, target_url=source.url, status=CrawlJob.Status.RUNNING, started_at=timezone.now())
    try:
        item_count = ingest_source(source, job)
    except Exception as exc:
        job.status = CrawlJob.Status.FAILED
        job.error_message = str(exc)
        source.failure_count += 1
        source.next_crawl_at = timezone.now() + timedelta(minutes=_backoff_minutes(source.failure_count))
        source.save(update_fields=["failure_count", "next_crawl_at", "updated_at"])
        raise
    else:
        job.status = CrawlJob.Status.SUCCEEDED
        source.failure_count = 0
        source.last_crawled_at = timezone.now()
        source.next_crawl_at = source.last_crawled_at + timedelta(minutes=source.crawl_interval_minutes)
        source.save(update_fields=["failure_count", "last_crawled_at", "next_crawl_at", "updated_at"])
    finally:
        job.finished_at = timezone.now()
        job.save(update_fields=["status", "error_message", "finished_at", "updated_at"])
    return item_count


@shared_task
def enqueue_due_sources():
    source_ids = list(
        Source.objects.filter(enabled=True, crawl_enabled=True, next_crawl_at__lte=timezone.now()).values_list("id", flat=True)
    )
    for source_id in source_ids:
        crawl_source.delay(source_id)
    return len(source_ids)


@shared_task
def enqueue_schedule_group(schedule_group: str):
    source_ids = list(
        Source.objects.filter(
            enabled=True,
            crawl_enabled=True,
            schedule_group=schedule_group,
        ).values_list("id", flat=True)
    )
    for source_id in source_ids:
        crawl_source.delay(source_id)
    return len(source_ids)


def _backoff_minutes(failure_count: int) -> int:
    return min(1440, 15 * (2 ** max(0, failure_count - 1)))
