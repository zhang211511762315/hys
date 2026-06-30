import pytest
from django.utils import timezone

from aggregator.models import CrawlJob, CrawlNetworkEvent, Source
from aggregator.tasks import crawl_source, enqueue_schedule_group


def make_source(name="Source", **kwargs):
    defaults = {
        "name": name,
        "url": f"https://{name.lower()}.nuc.edu.cn/",
        "source_type": Source.SourceType.OFFICIAL_SITE,
        "schedule_group": Source.ScheduleGroup.WEB_TWICE_DAILY,
    }
    defaults.update(kwargs)
    return Source.objects.create(**defaults)


@pytest.mark.django_db
def test_schedule_group_only_queues_due_sources(monkeypatch):
    due = make_source("Due", next_crawl_at=timezone.now() - timezone.timedelta(minutes=1))
    make_source("Later", next_crawl_at=timezone.now() + timezone.timedelta(hours=1))
    queued = []

    monkeypatch.setattr(crawl_source, "delay", lambda source_id: queued.append(source_id))

    count = enqueue_schedule_group(Source.ScheduleGroup.WEB_TWICE_DAILY)

    assert count == 1
    assert queued == [due.id]
    assert CrawlJob.objects.filter(source=due, status=CrawlJob.Status.QUEUED).count() == 1


@pytest.mark.django_db
def test_schedule_group_skips_source_with_open_job(monkeypatch):
    source = make_source("Open", next_crawl_at=timezone.now() - timezone.timedelta(minutes=1))
    CrawlJob.objects.create(source=source, target_url=source.url, status=CrawlJob.Status.RUNNING)
    queued = []

    monkeypatch.setattr(crawl_source, "delay", lambda source_id: queued.append(source_id))

    count = enqueue_schedule_group(Source.ScheduleGroup.WEB_TWICE_DAILY)

    assert count == 0
    assert queued == []


@pytest.mark.django_db
def test_schedule_group_records_network_event_when_probe_sources_unreachable(monkeypatch):
    for index in range(3):
        make_source(f"Probe{index}", next_crawl_at=timezone.now() - timezone.timedelta(minutes=1))
    queued = []

    monkeypatch.setattr("aggregator.tasks._tcp_reachable", lambda url: False)
    monkeypatch.setattr(crawl_source, "delay", lambda source_id: queued.append(source_id))

    count = enqueue_schedule_group(Source.ScheduleGroup.WEB_TWICE_DAILY)

    event = CrawlNetworkEvent.objects.get()
    assert count == 0
    assert queued == []
    assert event.schedule_group == Source.ScheduleGroup.WEB_TWICE_DAILY
    assert event.checked_count == 3
    assert event.reachable_count == 0


@pytest.mark.django_db
def test_crawl_source_updates_success_state(monkeypatch):
    source = make_source("Success", next_crawl_at=timezone.now() - timezone.timedelta(minutes=1))

    monkeypatch.setattr("aggregator.tasks.ingest_source", lambda source, job: 3)

    assert crawl_source(source.id) == 3

    source.refresh_from_db()
    job = CrawlJob.objects.get(source=source)
    assert job.status == CrawlJob.Status.SUCCEEDED
    assert source.last_success_at is not None
    assert source.failure_count == 0
    assert source.next_crawl_at > source.last_success_at


@pytest.mark.django_db
def test_crawl_source_updates_failure_state(monkeypatch):
    source = make_source("Failure", next_crawl_at=timezone.now() - timezone.timedelta(minutes=1))

    def fail(source, job):
        raise RuntimeError("network unavailable")

    monkeypatch.setattr("aggregator.tasks.ingest_source", fail)

    with pytest.raises(RuntimeError):
        crawl_source(source.id)

    source.refresh_from_db()
    job = CrawlJob.objects.get(source=source)
    assert job.status == CrawlJob.Status.FAILED
    assert source.last_error_at is not None
    assert source.last_crawled_at is not None
    assert source.failure_count == 1
    assert source.next_crawl_at > source.last_error_at
