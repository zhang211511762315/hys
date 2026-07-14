from datetime import timedelta
from io import StringIO

import pytest
from django.core.management import call_command
from django.utils import timezone

from aggregator.models import CrawlJob, Source


@pytest.mark.django_db
def test_recover_stale_crawl_jobs_is_dry_run_by_default():
    source = Source.objects.create(name="陈旧任务源", url="https://stale.example.edu/")
    job = CrawlJob.objects.create(source=source, target_url=source.url, status=CrawlJob.Status.RUNNING)
    CrawlJob.objects.filter(id=job.id).update(started_at=timezone.now() - timedelta(hours=2))
    output = StringIO()

    call_command("recover_stale_crawl_jobs", "--older-than-minutes", "60", stdout=output)

    job.refresh_from_db()
    assert job.status == CrawlJob.Status.RUNNING
    assert "Would recover 1 stale crawl job(s)" in output.getvalue()


@pytest.mark.django_db
def test_recover_stale_crawl_jobs_marks_only_old_open_jobs_failed():
    source = Source.objects.create(name="陈旧任务源", url="https://stale.example.edu/")
    stale_running = CrawlJob.objects.create(
        source=source,
        target_url=source.url,
        status=CrawlJob.Status.RUNNING,
    )
    stale_queued = CrawlJob.objects.create(
        source=source,
        target_url=source.url,
        status=CrawlJob.Status.QUEUED,
    )
    fresh = CrawlJob.objects.create(source=source, target_url=source.url, status=CrawlJob.Status.RUNNING)
    cutoff_time = timezone.now() - timedelta(hours=2)
    CrawlJob.objects.filter(id=stale_running.id).update(started_at=cutoff_time)
    CrawlJob.objects.filter(id=stale_queued.id).update(created_at=cutoff_time)
    output = StringIO()

    call_command("recover_stale_crawl_jobs", "--older-than-minutes", "60", "--apply", stdout=output)

    stale_running.refresh_from_db()
    stale_queued.refresh_from_db()
    fresh.refresh_from_db()
    assert stale_running.status == CrawlJob.Status.FAILED
    assert stale_queued.status == CrawlJob.Status.FAILED
    assert stale_running.finished_at is not None
    assert stale_queued.finished_at is not None
    assert "Recovered stale crawl job" in stale_running.error_message
    assert fresh.status == CrawlJob.Status.RUNNING
    assert "Recovered 2 stale crawl job(s)" in output.getvalue()
