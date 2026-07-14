from io import StringIO

import httpx
import pytest
from django.core.management import call_command

from aggregator.models import CrawlFailure, CrawlJob, Source


def _failure(source, url):
    job = CrawlJob.objects.create(source=source, target_url=url)
    return CrawlFailure.objects.create(
        crawl_job=job,
        source=source,
        url=url,
        error_type="ReadTimeout",
        error_message="timed out",
        failure_class=CrawlFailure.FailureClass.NETWORK,
    )


@pytest.mark.django_db
def test_recheck_crawl_failures_is_dry_run_by_default(monkeypatch):
    source = Source.objects.create(name="重检源", url="https://retry.example.edu/")
    failure = _failure(source, "https://retry.example.edu/item")
    monkeypatch.setattr(
        "aggregator.management.commands.recheck_crawl_failures.ingest_url",
        lambda *args, **kwargs: pytest.fail("dry-run must not fetch"),
    )
    output = StringIO()

    call_command("recheck_crawl_failures", str(failure.id), stdout=output)

    failure.refresh_from_db()
    assert failure.resolved_at is None
    assert "Would recheck 1 URL(s)" in output.getvalue()


@pytest.mark.django_db
def test_recheck_crawl_failures_resolves_a_successful_url(monkeypatch):
    source = Source.objects.create(name="重检源", url="https://retry.example.edu/")
    failure = _failure(source, "https://retry.example.edu/item")
    monkeypatch.setattr(
        "aggregator.management.commands.recheck_crawl_failures.ingest_url",
        lambda source, url, job: object(),
    )

    call_command("recheck_crawl_failures", str(failure.id), "--apply")

    failure.refresh_from_db()
    assert failure.resolved_at is not None
    recheck_job = CrawlJob.objects.exclude(id=failure.crawl_job_id).get()
    assert recheck_job.status == CrawlJob.Status.SUCCEEDED


@pytest.mark.django_db
def test_recheck_crawl_failures_records_observed_http_status(monkeypatch):
    source = Source.objects.create(name="重检源", url="https://retry.example.edu/")
    failure = _failure(source, "https://retry.example.edu/missing")
    request = httpx.Request("GET", failure.url)
    response = httpx.Response(404, request=request)

    def fail(*args, **kwargs):
        raise httpx.HTTPStatusError("not found", request=request, response=response)

    monkeypatch.setattr("aggregator.management.commands.recheck_crawl_failures.ingest_url", fail)

    call_command("recheck_crawl_failures", str(failure.id), "--apply")

    failure.refresh_from_db()
    assert failure.http_status == 404
    assert failure.permanent is True
    assert failure.failure_class == CrawlFailure.FailureClass.PERMANENT
