from datetime import datetime
from unittest.mock import Mock

import httpx
import pytest
from django.core.cache import caches
from django.utils import timezone

from aggregator import tasks_wewe_rss as rss
from aggregator.models import Category, ContentItem, CrawlFailure, CrawlJob, Source

pytestmark = pytest.mark.django_db


@pytest.fixture
def source():
    return Source.objects.create(name="fixture", url="https://example.test/feed", source_type="manual_url")


def item(source, number, category=None, day=2):
    return ContentItem.objects.create(source=source, category=category, title=f"通知 fixture {number}",
        canonical_url=f"https://mp.weixin.qq.com/s/fixture-{number}", content_text="通知内容",
        status="published", is_public=True,
        source_published_at=timezone.make_aware(datetime(2026, 5, day)))


def feed(*urls):
    return '<feed xmlns="http://www.w3.org/2005/Atom">' + ''.join(
        f'<entry><title>fixture</title><link href="{url}"/><updated>2026-05-02T00:00:00Z</updated></entry>'
        for url in urls) + '</feed>'


def response(text, url="https://example.test/feed", status=200):
    return httpx.Response(status, text=text, request=httpx.Request("GET", url))


def test_search_keeps_matches_outside_truncated_engine_results(client, monkeypatch, source):
    category = Category.objects.create(name="通知", slug="notice")
    stale = [item(source, i, category) for i in range(35)]
    wanted = item(source, 100, category, day=20)
    observed = []
    def engine(query, filters):
        observed.append(filters)
        return [{"id": x.pk} for x in stale[:30]]
    monkeypatch.setattr("aggregator.views.meili_search", engine)
    caches["pages"].clear()
    r = client.get('/search/', {"q": "通知", "category": "notice", "date_from": "2026-05-20", "date_to": "2026-05-20"})
    assert r.status_code == 200
    assert [x.pk for x in r.context["page"]] == [wanted.pk]
    assert observed[0]["category_slug"] == "notice"
    assert observed[0]["published_to"] > observed[0]["published_from"]


def test_search_fallback_preserves_category_and_date_order(client, monkeypatch, source):
    a = Category.objects.create(name="甲", slug="a")
    b = Category.objects.create(name="乙", slug="b")
    older = item(source, 1, a, 2)
    newer = item(source, 2, a, 3)
    item(source, 3, b, 4)
    monkeypatch.setattr("aggregator.views.meili_search", lambda *a: [])
    caches["pages"].clear()
    r = client.get('/search/', {"q": "通知", "category": "a", "sort": "date"})
    assert [x.pk for x in r.context["page"]] == [newer.pk, older.pk]


def test_source_page_shows_freshness_without_history(client, source):
    caches["pages"].clear()
    r = client.get(f'/sources/{source.pk}/')
    assert r.status_code == 200
    assert '尚无成功更新' in r.content.decode()


def test_empty_feed_is_success(monkeypatch):
    monkeypatch.setattr(rss, '_get_with_retry', lambda *a, **k: response(feed()))
    assert rss.fetch_wewe_rss() == 0
    assert CrawlJob.objects.get().status == 'succeeded'
    assert Source.objects.get().last_success_at is not None


def test_malformed_feed_records_failure_without_success(monkeypatch):
    monkeypatch.setattr(rss, '_get_with_retry', lambda *a, **k: response('<feed'))
    assert rss.fetch_wewe_rss() == 0
    assert CrawlJob.objects.get().status == 'failed'
    assert CrawlFailure.objects.get().url == rss.WEWE_RSS_FEED
    assert Source.objects.get().last_success_at is None


def test_duplicate_feed_urls_and_existing_articles_are_skipped(monkeypatch, source):
    old = item(source, 1)
    new = 'https://mp.weixin.qq.com/s/new-fixture'
    calls = []
    def get(url, **kwargs):
        calls.append(url)
        return response(feed(old.canonical_url, new, new)) if url == rss.WEWE_RSS_FEED else response('<h1>fixture</h1><p>text</p>', url)
    monkeypatch.setattr(rss, '_get_with_retry', get)
    ingest = Mock()
    monkeypatch.setattr(rss, 'ingest_extracted_document', ingest)
    assert rss.fetch_wewe_rss() == 1
    assert calls.count(new) == 1
    assert old.canonical_url not in calls
    ingest.assert_called_once()


def test_partial_failure_is_retained_then_recovered(monkeypatch):
    good, bad = 'https://mp.weixin.qq.com/s/good', 'https://mp.weixin.qq.com/s/bad'
    broken = [True]
    def get(url, **kwargs):
        if url == rss.WEWE_RSS_FEED:
            return response(feed(good, bad))
        if url == bad and broken[0]:
            raise httpx.ReadTimeout('synthetic timeout')
        return response('<h1>fixture</h1><p>text</p>', url)
    monkeypatch.setattr(rss, '_get_with_retry', get)
    monkeypatch.setattr(rss, 'ingest_extracted_document', Mock())
    assert rss.fetch_wewe_rss() == 1
    f = CrawlFailure.objects.get()
    assert f.failure_class == 'network' and not f.permanent
    assert CrawlJob.objects.latest('pk').status == 'failed'
    broken[0] = False
    CrawlFailure.objects.update(next_retry_at=timezone.now())
    assert rss.fetch_wewe_rss() == 2
    f.refresh_from_db()
    assert f.resolved_at is not None
    assert CrawlJob.objects.latest('pk').status == 'succeeded'


@pytest.mark.parametrize('status,expected', [(404, 1), (429, 3), (503, 3)])
def test_http_retry_policy_is_bounded(monkeypatch, status, expected):
    get = Mock(return_value=response('synthetic', status=status))
    monkeypatch.setattr(rss.httpx, 'get', get)
    monkeypatch.setattr(rss.time, 'sleep', lambda _: None)
    with pytest.raises(httpx.HTTPStatusError):
        rss._get_with_retry('https://example.test')
    assert get.call_count == expected


def test_running_feed_job_prevents_duplicate_worker(monkeypatch):
    source = Source.objects.create(name=rss.WEWE_RSS_SOURCE_NAME, url=rss.WEWE_RSS_FEED, source_type='manual_url')
    CrawlJob.objects.create(source=source, target_url=source.url, status='running')
    get = Mock()
    monkeypatch.setattr(rss, '_get_with_retry', get)
    assert rss.fetch_wewe_rss() == 0
    get.assert_not_called()


@pytest.mark.django_db(transaction=True)
def test_mysql_two_workers_claim_one_feed_job(monkeypatch):
    from concurrent.futures import ThreadPoolExecutor
    import threading
    from django.db import connection, connections, close_old_connections
    if connection.vendor != 'mysql':
        pytest.skip('requires isolated MySQL connections')
    Source.objects.create(name=rss.WEWE_RSS_SOURCE_NAME, url=rss.WEWE_RSS_FEED, source_type='manual_url')
    started = threading.Event()
    finish = threading.Event()
    calls = []
    def get(*args, **kwargs):
        calls.append(1)
        started.set()
        assert finish.wait(5)
        return response(feed())
    monkeypatch.setattr(rss, '_get_with_retry', get)
    def worker():
        close_old_connections()
        try:
            return rss.fetch_wewe_rss()
        finally:
            connections.close_all()
    with ThreadPoolExecutor(2) as pool:
        first = pool.submit(worker)
        try:
            assert started.wait(5)
            second = pool.submit(worker)
            assert second.result(timeout=4) == 0
            assert len(calls) == 1
        finally:
            finish.set()
        assert first.result(timeout=5) == 0
    assert CrawlJob.objects.count() == 1
    assert CrawlJob.objects.get().status == 'succeeded'
