from datetime import timedelta
import socket
from urllib.parse import urlsplit

from celery import shared_task
from django.conf import settings
from django.db import transaction
from django.utils import timezone

from .models import CrawlJob, CrawlNetworkEvent, Source
from .services.pipeline import ingest_source


@shared_task
def crawl_source(source_id: int):
    source = Source.objects.get(id=source_id)
    job = (
        CrawlJob.objects.filter(source=source, status=CrawlJob.Status.QUEUED)
        .order_by("created_at")
        .first()
    )
    if not source.enabled or not source.crawl_enabled:
        if job is not None:
            job.status = CrawlJob.Status.FAILED
            job.error_message = "Skipped because source is disabled."
            job.finished_at = timezone.now()
            job.save(update_fields=["status", "error_message", "finished_at", "updated_at"])
        return 0
    if job is None:
        if CrawlJob.objects.filter(source=source, status=CrawlJob.Status.RUNNING).exists():
            return 0
        job = CrawlJob.objects.create(source=source, target_url=source.url)
    elif CrawlJob.objects.filter(source=source, status=CrawlJob.Status.RUNNING).exclude(id=job.id).exists():
        job.status = CrawlJob.Status.FAILED
        job.error_message = "Skipped because another crawl job is already running for this source."
        job.finished_at = timezone.now()
        job.save(update_fields=["status", "error_message", "finished_at", "updated_at"])
        return 0
    job.status = CrawlJob.Status.RUNNING
    job.started_at = timezone.now()
    job.save(update_fields=["status", "started_at", "updated_at"])
    try:
        item_count = ingest_source(source, job)
    except Exception as exc:
        job.status = CrawlJob.Status.FAILED
        job.error_message = str(exc)
        now = timezone.now()
        source.failure_count += 1
        source.last_crawled_at = now
        source.last_error_at = now
        source.next_crawl_at = now + timedelta(minutes=_backoff_minutes(source.failure_count))
        source.save(
            update_fields=[
                "failure_count",
                "last_crawled_at",
                "last_error_at",
                "next_crawl_at",
                "updated_at",
            ]
        )
        raise
    else:
        job.status = CrawlJob.Status.SUCCEEDED
        if item_count == 0 and not job.warning_message:
            job.warning_message = "No articles were discovered or ingested."
        now = timezone.now()
        source.failure_count = 0
        source.last_crawled_at = now
        source.last_success_at = now
        source.next_crawl_at = now + timedelta(minutes=source.crawl_interval_minutes)
        source.save(
            update_fields=[
                "failure_count",
                "last_crawled_at",
                "last_success_at",
                "next_crawl_at",
                "updated_at",
            ]
        )
    finally:
        job.finished_at = timezone.now()
        job.save(update_fields=["status", "error_message", "warning_message", "finished_at", "updated_at"])
    return item_count


@shared_task
def enqueue_due_sources():
    sources = list(
        Source.objects.filter(enabled=True, crawl_enabled=True, next_crawl_at__lte=timezone.now()).only("id", "url")
    )
    if _all_probe_sources_unreachable(sources, ""):
        return 0
    queued = 0
    for source in sources:
        if _queue_source_if_idle(source.id):
            crawl_source.delay(source.id)
            queued += 1
    return queued


@shared_task
def enqueue_schedule_group(schedule_group: str):
    sources = list(
        Source.objects.filter(
            enabled=True,
            crawl_enabled=True,
            schedule_group=schedule_group,
            next_crawl_at__lte=timezone.now(),
        ).only("id", "url")
    )
    if _all_probe_sources_unreachable(sources, schedule_group):
        return 0
    queued = 0
    for source in sources:
        if _queue_source_if_idle(source.id):
            crawl_source.delay(source.id)
            queued += 1
    return queued


def _queue_source_if_idle(source_id: int) -> bool:
    with transaction.atomic():
        source = Source.objects.select_for_update().get(id=source_id)
        if not source.enabled or not source.crawl_enabled or source.next_crawl_at > timezone.now():
            return False
        has_open_job = CrawlJob.objects.filter(
            source=source,
            status__in=[CrawlJob.Status.QUEUED, CrawlJob.Status.RUNNING],
        ).exists()
        if has_open_job:
            return False
        CrawlJob.objects.create(source=source, target_url=source.url, status=CrawlJob.Status.QUEUED)
    return True


def _backoff_minutes(failure_count: int) -> int:
    return min(1440, 15 * (2 ** max(0, failure_count - 1)))


def _all_probe_sources_unreachable(sources: list[Source], schedule_group: str = "") -> bool:
    min_sources = getattr(settings, "CRAWL_GROUP_PROBE_MIN_SOURCES", 3)
    if len(sources) < min_sources:
        return False
    probe = _probe_sources(sources)
    if probe["reachable_count"] > 0:
        return False
    CrawlNetworkEvent.objects.create(
        schedule_group=schedule_group,
        checked_count=probe["checked_count"],
        reachable_count=probe["reachable_count"],
        reason="all probe sources unreachable",
        probe_urls=probe["probe_urls"],
    )
    return True


def _probe_sources(sources: list[Source]) -> dict:
    probe_size = getattr(settings, "CRAWL_GROUP_PROBE_SIZE", 3)
    probe_sources = sources[:probe_size]
    reachable_count = 0
    probe_urls = []
    for source in probe_sources:
        probe_urls.append(source.url)
        if _tcp_reachable(source.url):
            reachable_count += 1
    return {
        "checked_count": len(probe_sources),
        "reachable_count": reachable_count,
        "probe_urls": probe_urls,
    }


def _tcp_reachable(url: str, timeout: float = 3.0) -> bool:
    parsed = urlsplit(url)
    host = parsed.hostname
    if not host:
        return False
    port = parsed.port or (443 if parsed.scheme == "https" else 80)
    try:
        addresses = socket.getaddrinfo(host, port, type=socket.SOCK_STREAM)
    except OSError:
        return False
    for family, socktype, proto, _canonname, sockaddr in addresses:
        try:
            with socket.socket(family, socktype, proto) as sock:
                sock.settimeout(timeout)
                sock.connect(sockaddr)
                return True
        except OSError:
            continue
    return False
