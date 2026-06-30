from datetime import timedelta

import httpx
import pytest
from django.utils import timezone

from aggregator.services.ai import AIAnalysis, DeepSeekAIProvider, RuleBasedAIProvider
from aggregator.services.dedupe import content_fingerprint, is_near_duplicate, title_fingerprint
from aggregator.services.employment import EmploymentAPIError, fetch_employment_documents
from aggregator.services.extraction import ExtractionError, _parse_published_at, extract_document_from_html
from aggregator.services.fetching import FetchResult, fetch_url
from aggregator.services.pipeline import _combine_ocr_text, _record_crawl_failure, ingest_extracted_document, ingest_source
from aggregator.services.importance import score_importance
from aggregator.services.scheduling import recommended_crawl_interval_minutes
from aggregator.services.urls import normalize_url
from aggregator.models import AIUsageDaily, Category, ContentItem, CrawlFailure, CrawlJob, Source


def test_normalize_url_removes_tracking_and_fragment():
    url = "HTTPS://www.nuc.edu.cn/info/1001/1234.htm?utm_source=x&b=2&a=1#top"

    assert normalize_url(url) == "https://www.nuc.edu.cn/info/1001/1234.htm?a=1&b=2"


def test_content_fingerprint_is_stable_for_whitespace_changes():
    first = content_fingerprint(" 中北大学   计算机学院\n发布通知 ")
    second = content_fingerprint("中北大学 计算机学院 发布通知")

    assert first == second


def test_near_duplicate_detects_reposted_notice():
    original = "中北大学软件学院发布实验室开放通知，报名时间为本周五下午三点。"
    repost = "中北大学软件学院发布实验室开放通知。报名时间：本周五下午三点！"

    assert is_near_duplicate(original, repost) is True


def test_rule_based_ai_provider_returns_summary_category_and_tags():
    provider = RuleBasedAIProvider()

    result = provider.analyze(
        "关于2026年研究生招生复试安排的通知，考生需按时提交材料。",
        categories=["招生", "科研", "社团"],
    )

    assert result.category == "招生"
    assert result.summary.startswith("关于2026年研究生招生复试安排")
    assert "研究生" in result.tags


@pytest.mark.django_db
def test_deepseek_provider_records_usage_and_disables_thinking(monkeypatch, settings):
    settings.DEEPSEEK_API_KEY = "test-key"
    settings.DEEPSEEK_MODEL = "deepseek-v4-flash"
    settings.DEEPSEEK_DAILY_BUDGET_CNY = "0.5"
    settings.DEEPSEEK_MAX_OUTPUT_TOKENS = 500
    calls = []

    class Response:
        def raise_for_status(self):
            return None

        def json(self):
            return {
                "choices": [{"message": {"content": '{"summary":"摘要","category":"通知","tags":["通知"]}'}}],
                "usage": {
                    "prompt_cache_hit_tokens": 10,
                    "prompt_cache_miss_tokens": 90,
                    "completion_tokens": 20,
                },
            }

    def fake_post(url, headers, json, timeout):
        calls.append({"url": url, "headers": headers, "json": json, "timeout": timeout})
        return Response()

    monkeypatch.setattr("aggregator.services.ai.httpx.post", fake_post)

    result = DeepSeekAIProvider().analyze("关于教学安排的通知", ["通知", "招生"])

    assert result.provider == "deepseek"
    assert result.summary == "摘要"
    assert calls[0]["json"]["model"] == "deepseek-v4-flash"
    assert calls[0]["json"]["thinking"] == {"type": "disabled"}
    assert calls[0]["json"]["max_tokens"] == 500
    usage = AIUsageDaily.objects.get(provider="deepseek", model="deepseek-v4-flash")
    assert usage.request_count == 1
    assert usage.prompt_cache_hit_tokens == 10
    assert usage.prompt_cache_miss_tokens == 90
    assert usage.completion_tokens == 20
    assert usage.cost_cny > 0


@pytest.mark.django_db
def test_deepseek_provider_falls_back_when_budget_is_exhausted(monkeypatch, settings):
    settings.DEEPSEEK_API_KEY = "test-key"
    settings.DEEPSEEK_MODEL = "deepseek-v4-flash"
    settings.DEEPSEEK_DAILY_BUDGET_CNY = "0.000001"

    def fail_if_called(*args, **kwargs):
        raise AssertionError("DeepSeek API should not be called after budget is exhausted")

    monkeypatch.setattr("aggregator.services.ai.httpx.post", fail_if_called)

    result = DeepSeekAIProvider().analyze("关于2026年研究生招生复试安排的通知", ["招生", "科研"])

    assert result.provider == "rules"
    assert result.category == "招生"


@pytest.mark.django_db
def test_deepseek_provider_releases_budget_on_request_failure(monkeypatch, settings):
    settings.DEEPSEEK_API_KEY = "test-key"
    settings.DEEPSEEK_MODEL = "deepseek-v4-flash"
    settings.DEEPSEEK_DAILY_BUDGET_CNY = "0.5"

    def fake_post(*args, **kwargs):
        raise RuntimeError("network unavailable")

    monkeypatch.setattr("aggregator.services.ai.httpx.post", fake_post)

    result = DeepSeekAIProvider().analyze("关于2026年研究生招生复试安排的通知", ["招生", "科研"])

    assert result.provider == "rules"
    usage = AIUsageDaily.objects.get(provider="deepseek", model="deepseek-v4-flash")
    assert usage.request_count == 0
    assert usage.cost_cny == 0


def test_fetch_url_uses_relay_after_direct_connect_error(monkeypatch, settings):
    settings.CRAWL_DIRECT_FIRST = True
    settings.CRAWL_RELAY_URL = "https://relay.example/fetch"
    settings.CRAWL_RELAY_TOKEN = "relay-token"
    settings.CRAWL_RELAY_ON_ERRORS = "connect,timeout,dns,5xx,429"
    settings.CRAWL_USER_AGENT = "TestBot/1.0"
    settings.FETCH_TIMEOUT_SECONDS = 1
    settings.FETCH_CONNECT_TIMEOUT_SECONDS = 1
    settings.CRAWL_RELAY_TIMEOUT_SECONDS = 2
    calls = []

    def fake_get(*args, **kwargs):
        raise httpx.ConnectError("connect failed")

    class Response:
        def raise_for_status(self):
            return None

        def json(self):
            return {
                "status_code": 200,
                "final_url": "https://www.nuc.edu.cn/info/1.htm",
                "body": "<html>ok</html>",
                "headers": {"content-type": "text/html"},
            }

    def fake_post(url, headers, json, timeout):
        calls.append({"url": url, "headers": headers, "json": json, "timeout": timeout})
        return Response()

    monkeypatch.setattr("aggregator.services.fetching.httpx.get", fake_get)
    monkeypatch.setattr("aggregator.services.fetching.httpx.post", fake_post)

    result = fetch_url("https://www.nuc.edu.cn/info/1.htm")

    assert result.via == "relay"
    assert result.text == "<html>ok</html>"
    assert calls[0]["url"] == "https://relay.example/fetch"
    assert calls[0]["headers"]["Authorization"] == "Bearer relay-token"
    assert calls[0]["json"] == {"url": "https://www.nuc.edu.cn/info/1.htm"}


def test_fetch_url_retries_direct_and_forces_ipv4(monkeypatch, settings):
    settings.CRAWL_RELAY_URL = ""
    settings.CRAWL_DIRECT_FIRST = True
    settings.CRAWL_DIRECT_RETRY_ATTEMPTS = 2
    settings.CRAWL_FORCE_IPV4_DOMAINS = [".nuc.edu.cn"]
    settings.CRAWL_USER_AGENT = "TestBot/1.0"
    settings.FETCH_TIMEOUT_SECONDS = 1
    settings.FETCH_CONNECT_TIMEOUT_SECONDS = 1
    calls = []

    def fake_getaddrinfo(host, port, family=0, type=0, proto=0, flags=0):
        return [
            (2, 1, 6, "", ("202.207.177.42", port)),
            (10, 1, 6, "", ("2001:250:c00:888::333", port, 0, 0)),
        ]

    class Response:
        status_code = 200
        text = "<html>ok</html>"
        headers = {}
        url = "http://www.nuc.edu.cn/"

        def raise_for_status(self):
            return None

    def fake_get(url, **kwargs):
        import socket

        calls.append(socket.getaddrinfo("www.nuc.edu.cn", 80))
        if len(calls) == 1:
            raise httpx.ReadTimeout("timed out")
        return Response()

    monkeypatch.setattr("aggregator.services.fetching.socket.getaddrinfo", fake_getaddrinfo)
    monkeypatch.setattr("aggregator.services.fetching.httpx.get", fake_get)

    result = fetch_url("http://www.nuc.edu.cn/")

    assert result.text == "<html>ok</html>"
    assert len(calls) == 2
    assert all(entry[0] == 2 for entry in calls[0])


def test_employment_documents_are_built_from_json_api(monkeypatch, settings):
    settings.CRAWL_EMPLOYMENT_NOTICE_TYPE_IDS = ["10831"]
    settings.CRAWL_EMPLOYMENT_PAGE_SIZE = 2
    payload = {
        "code": 1,
        "data": [
            {
                "notice_id": "1788425",
                "notice_name": "就业新闻",
                "create_time": "2026-05-18",
                "content": "<p>就业新闻正文</p>",
                "content_source_url": "",
            }
        ],
    }

    def fake_fetch(url):
        import json

        return FetchResult(url=url, final_url=url, text=json.dumps(payload), status_code=200, headers={}, via="direct")

    monkeypatch.setattr("aggregator.services.employment.fetch_url", fake_fetch)

    documents, fetches, failures = fetch_employment_documents("http://zbjy.nuc.edu.cn/", 10)

    assert len(fetches) == 1
    assert failures == []
    assert len(documents) == 1
    assert documents[0].title == "就业新闻"
    assert documents[0].published_at.year == 2026
    assert documents[0].date_confidence == "exact"
    assert documents[0].final_url == "http://zbjy.nuc.edu.cn/detail/news?id=1788425&menu_id=23298&type_id=10831"


def test_employment_api_non_json_response_is_recorded_and_other_types_continue(monkeypatch, settings):
    settings.CRAWL_EMPLOYMENT_NOTICE_TYPE_IDS = ["broken", "10831"]
    settings.CRAWL_EMPLOYMENT_PAGE_SIZE = 2
    calls = []

    def fake_fetch(url):
        import json

        calls.append(url)
        if "type_id=broken" in url:
            return FetchResult(url=url, final_url=url, text="", status_code=200, headers={}, via="direct")
        payload = {
            "code": 1,
            "data": [
                {
                    "notice_id": "1788425",
                    "notice_name": "就业新闻",
                    "create_time": "2026-05-18",
                    "content": "<p>就业新闻正文</p>",
                    "content_source_url": "",
                }
            ],
        }
        return FetchResult(url=url, final_url=url, text=json.dumps(payload), status_code=200, headers={}, via="direct")

    monkeypatch.setattr("aggregator.services.employment.fetch_url", fake_fetch)

    documents, fetches, failures = fetch_employment_documents("http://zbjy.nuc.edu.cn/", 10)

    assert len(fetches) == 2
    assert len(failures) == 1
    assert "non-JSON" in str(failures[0].exc)
    assert len(documents) == 1
    assert documents[0].title == "就业新闻"
    assert "type_id=10831" in calls[-1]


def test_employment_api_html_response_uses_explicit_error(monkeypatch, settings):
    settings.CRAWL_EMPLOYMENT_NOTICE_TYPE_IDS = ["broken"]
    settings.CRAWL_EMPLOYMENT_PAGE_SIZE = 2

    def fake_fetch(url):
        return FetchResult(
            url=url,
            final_url=url,
            text="<!DOCTYPE html><html><body>login</body></html>",
            status_code=200,
            headers={},
            via="direct",
        )

    monkeypatch.setattr("aggregator.services.employment.fetch_url", fake_fetch)

    documents, fetches, failures = fetch_employment_documents("http://zbjy.nuc.edu.cn/", 10)

    assert documents == []
    assert len(fetches) == 1
    assert len(failures) == 1
    assert isinstance(failures[0].exc, EmploymentAPIError)
    assert "HTML instead of JSON" in str(failures[0].exc)


def test_ingest_source_uses_discovered_article_links(monkeypatch):
    class Source:
        url = "https://www.nuc.edu.cn/"

    class Document:
        html = '<a href="info/1013/53873.htm">学校新闻</a><a href="info/1014/51483.htm">招聘公告</a>'

    called_urls = []

    monkeypatch.setattr("aggregator.services.pipeline.fetch_and_extract", lambda url: Document())
    monkeypatch.setattr("aggregator.services.pipeline.ingest_url", lambda source, url, crawl_job=None: called_urls.append(url))

    count = ingest_source(Source())

    assert count == 2
    assert called_urls == [
        "https://www.nuc.edu.cn/info/1013/53873.htm",
        "https://www.nuc.edu.cn/info/1014/51483.htm",
    ]


def test_ingest_source_discovers_articles_from_listing_pages(monkeypatch):
    class Source:
        url = "https://www.nuc.edu.cn/"
        source_type = "official_site"
        crawl_depth = 2
        max_list_pages_per_run = 3
        max_articles_per_run = 10

    class Document:
        def __init__(self, html):
            self.html = html

    pages = {
        "https://www.nuc.edu.cn/": Document('<a href="xwdt.htm">News</a>'),
        "https://www.nuc.edu.cn/xwdt.htm": Document(
            '<a href="info/1013/53873.htm">A</a><a href="info/1013/53773.htm">B</a>'
        ),
    }
    called_urls = []

    monkeypatch.setattr("aggregator.services.pipeline.fetch_and_extract", lambda url: pages[url])
    monkeypatch.setattr("aggregator.services.pipeline.ingest_url", lambda source, url, crawl_job=None: called_urls.append(url))

    count = ingest_source(Source())

    assert count == 2
    assert called_urls == [
        "https://www.nuc.edu.cn/info/1013/53873.htm",
        "https://www.nuc.edu.cn/info/1013/53773.htm",
    ]


@pytest.mark.django_db
def test_ingest_source_retries_failed_urls_before_newly_discovered_urls(monkeypatch, settings):
    settings.CRAWL_RETRY_FAILED_URLS_PER_RUN = 10
    source = Source.objects.create(
        name="NUC",
        url="https://www.nuc.edu.cn/",
        source_type=Source.SourceType.OFFICIAL_SITE,
    )
    job = CrawlJob.objects.create(source=source, target_url=source.url, status=CrawlJob.Status.FAILED)
    CrawlFailure.objects.create(
        crawl_job=job,
        source=source,
        url="https://www.nuc.edu.cn/info/1013/old.htm",
        error_type="ReadTimeout",
    )

    class Document:
        html = '<a href="info/1013/new.htm">新通知</a>'

    called_urls = []

    monkeypatch.setattr("aggregator.services.pipeline.fetch_and_extract", lambda url: Document())
    monkeypatch.setattr("aggregator.services.pipeline.ingest_url", lambda source, url, crawl_job=None: called_urls.append(url))

    count = ingest_source(source)

    failure = CrawlFailure.objects.get()
    assert failure.resolved_at is not None
    assert count == 2
    assert called_urls == [
        "https://www.nuc.edu.cn/info/1013/old.htm",
        "https://www.nuc.edu.cn/info/1013/new.htm",
    ]


@pytest.mark.django_db
def test_ingest_existing_content_hash_skips_ai(monkeypatch):
    source = Source.objects.create(name="NUC", url="https://www.nuc.edu.cn/", source_type=Source.SourceType.OFFICIAL_SITE)
    category = Category.objects.create(name="通知", slug="notice")
    text = "来源：招生办 发布时间：2026年05月08日 关于教学安排的重要通知。"
    document = extract_document_from_html(
        "https://www.nuc.edu.cn/info/1001/1234.htm",
        "https://www.nuc.edu.cn/info/1001/1234.htm",
        f"<html><head><title>通知</title></head><body><div class='v_news_content'>{text}</div></body></html>",
    )
    existing = ContentItem.objects.create(
        source=source,
        category=category,
        title="通知",
        canonical_url=document.final_url,
        summary="已有摘要",
        content_text=text,
        content_hash=content_fingerprint(text),
        ai_provider="deepseek",
        status=ContentItem.Status.PUBLISHED,
        is_public=True,
        source_published_at=document.published_at,
    )
    job = CrawlJob.objects.create(source=source, target_url=source.url, status=CrawlJob.Status.RUNNING)

    def fail_if_called():
        raise AssertionError("AI provider should not be loaded for duplicate content")

    monkeypatch.setattr("aggregator.services.pipeline.get_ai_provider", fail_if_called)

    item = ingest_extracted_document(source, document, job)

    job.refresh_from_db()
    assert item.id == existing.id
    assert job.ai_skip_count == 1
    assert job.duplicate_skip_count == 1


@pytest.mark.django_db
def test_ingest_near_duplicate_skips_ai(monkeypatch):
    source = Source.objects.create(name="JWC", url="https://jwc.nuc.edu.cn/", source_type=Source.SourceType.DEPARTMENT_SITE)
    other_source = Source.objects.create(name="NUC", url="https://www.nuc.edu.cn/", source_type=Source.SourceType.OFFICIAL_SITE)
    category = Category.objects.create(name="通知", slug="notice")
    text = "来源：教务部 发布时间：2026年05月20日 关于2026年上半年高校教师资格认定工作的通知，请按时完成网上报名和现场确认。"
    ContentItem.objects.create(
        source=source,
        category=category,
        title="关于2026年上半年高校教师资格认定工作的通知-中北大学-教务部",
        title_fingerprint=title_fingerprint("关于2026年上半年高校教师资格认定工作的通知-中北大学-教务部"),
        canonical_url="https://jwc.nuc.edu.cn/info/1295/12874.htm",
        summary="已有摘要",
        content_text=text,
        content_hash=content_fingerprint(text),
        ai_provider="deepseek",
        status=ContentItem.Status.PUBLISHED,
        is_public=True,
        source_published_at=timezone.datetime(2026, 5, 20, tzinfo=timezone.get_current_timezone()),
    )
    document = extract_document_from_html(
        "https://www.nuc.edu.cn/info/1014/54833.htm",
        "https://www.nuc.edu.cn/info/1014/54833.htm",
        "<html><head><title>关于2026年上半年高校教师资格认定工作的通知-中北大学</title></head>"
        f"<body><div class='v_news_content'>{text}。</div></body></html>",
    )
    job = CrawlJob.objects.create(source=other_source, target_url=other_source.url, status=CrawlJob.Status.RUNNING)

    def fail_if_called():
        raise AssertionError("AI provider should not be loaded for near duplicate content")

    monkeypatch.setattr("aggregator.services.pipeline.get_ai_provider", fail_if_called)

    item = ingest_extracted_document(other_source, document, job)

    job.refresh_from_db()
    assert item.canonical_url == "https://jwc.nuc.edu.cn/info/1295/12874.htm"
    assert job.near_duplicate_skip_count == 1
    assert job.ai_skip_count == 1


@pytest.mark.django_db
def test_ingest_handles_tag_slug_collisions(monkeypatch):
    source = Source.objects.create(name="NUC", url="https://www.nuc.edu.cn/", source_type=Source.SourceType.OFFICIAL_SITE)
    document = extract_document_from_html(
        "https://www.nuc.edu.cn/info/1001/tags.htm",
        "https://www.nuc.edu.cn/info/1001/tags.htm",
        "<html><head><title>标签冲突</title></head><body><div class='v_news_content'>发布时间：2026年05月20日 正文足够长。</div></body></html>",
    )

    class Provider:
        def analyze(self, text, categories):
            return AIAnalysis(summary="摘要", category="通知", tags=["2025届", "2025"], provider="rules")

    monkeypatch.setattr("aggregator.services.pipeline.get_ai_provider", lambda: Provider())

    item = ingest_extracted_document(source, document)

    assert item.tags.count() == 2
    assert item.tags.filter(name="2025届").exists()
    assert item.tags.filter(name="2025").exists()


@pytest.mark.django_db
def test_record_crawl_failure_classifies_permanent_and_network_errors(settings):
    settings.CRAWL_FAILURE_RETRY_BASE_MINUTES = 30
    source = Source.objects.create(name="NUC", url="https://www.nuc.edu.cn/", source_type=Source.SourceType.OFFICIAL_SITE)
    job = CrawlJob.objects.create(source=source, target_url=source.url, status=CrawlJob.Status.RUNNING)

    _record_crawl_failure(job, source, "https://www.nuc.edu.cn/missing.htm", ExtractionError("page is missing or expired"))
    _record_crawl_failure(job, source, "https://www.nuc.edu.cn/timeout.htm", httpx.ReadTimeout("timed out"))

    permanent = CrawlFailure.objects.get(url="https://www.nuc.edu.cn/missing.htm")
    network = CrawlFailure.objects.get(url="https://www.nuc.edu.cn/timeout.htm")
    assert permanent.permanent is True
    assert permanent.next_retry_at is None
    assert network.failure_class == CrawlFailure.FailureClass.NETWORK
    assert network.permanent is False
    assert network.next_retry_at is not None


@pytest.mark.django_db
def test_record_crawl_failure_updates_existing_unresolved_url(settings):
    settings.CRAWL_FAILURE_RETRY_BASE_MINUTES = 30
    source = Source.objects.create(name="NUC", url="https://www.nuc.edu.cn/", source_type=Source.SourceType.OFFICIAL_SITE)
    job = CrawlJob.objects.create(source=source, target_url=source.url, status=CrawlJob.Status.RUNNING)
    url = "https://www.nuc.edu.cn/timeout.htm"

    _record_crawl_failure(job, source, url, httpx.ReadTimeout("first timeout"))
    _record_crawl_failure(job, source, url, httpx.ReadTimeout("second timeout"))

    failures = CrawlFailure.objects.filter(source=source, url=url, resolved_at__isnull=True)
    assert failures.count() == 1
    failure = failures.get()
    assert failure.retry_count == 1
    assert "second timeout" in failure.error_message


def test_expired_pages_raise_extraction_error():
    with pytest.raises(ExtractionError):
        extract_document_from_html(
            "http://zbjy.nuc.edu.cn/detail/news?id=399369",
            "http://zbjy.nuc.edu.cn/detail/news?id=399369",
            "该信息不存在或已过期，即将跳回首页，请浏览其他信息",
        )


def test_combine_ocr_text_skips_ocr_when_text_is_already_substantial(monkeypatch, settings):
    settings.OCR_MIN_TEXT_LENGTH = 20
    calls = []

    def record_call(url):
        calls.append(url)
        return type("OCRResult", (), {"text": "图片文字"})()

    monkeypatch.setattr("aggregator.services.pipeline.ocr_image_url", record_call)

    result = _combine_ocr_text("这是一段已经足够长的正文内容，不需要再跑图片OCR。", ["https://www.nuc.edu.cn/a.png"])

    assert result == "这是一段已经足够长的正文内容，不需要再跑图片OCR。"
    assert calls == []


def test_combine_ocr_text_skips_ocr_for_official_web_sources_by_default(monkeypatch, settings):
    settings.OCR_ENABLE_FOR_WEB = False
    source = type("SourceObj", (), {"source_type": Source.SourceType.OFFICIAL_SITE})()
    calls = []

    def record_call(url):
        calls.append(url)
        return type("OCRResult", (), {"text": "图片文字"})()

    monkeypatch.setattr("aggregator.services.pipeline.ocr_image_url", record_call)

    result = _combine_ocr_text("短正文", ["https://www.nuc.edu.cn/a.png"], source)

    assert result == "短正文"
    assert calls == []


def test_recommended_crawl_intervals_match_source_type_policy():
    assert recommended_crawl_interval_minutes(Source.SourceType.OFFICIAL_SITE) == 5
    assert recommended_crawl_interval_minutes(Source.SourceType.SOCIAL_LINK) == 1440
    assert recommended_crawl_interval_minutes(Source.SourceType.WECHAT_LINK) == 1440


def test_importance_score_prioritizes_official_deadline_notices():
    source = type("SourceObj", (), {"priority": Source.Priority.HIGH, "source_type": Source.SourceType.OFFICIAL_SITE})()

    score = score_importance(source, "研究生复试报名截止通知", "请考生按时提交材料。", "招生")

    assert score >= 80


def test_parse_published_at_from_chinese_article_text():
    value = _parse_published_at("来源：招生办 发布时间：2026年05月08日 浏览：")

    assert value.year == 2026
    assert value.month == 5
    assert value.day == 8


def test_extract_document_parses_date_from_meta_when_article_body_has_no_date():
    document = extract_document_from_html(
        "https://www.nuc.edu.cn/info/1001/1234.htm",
        "https://www.nuc.edu.cn/info/1001/1234.htm",
        """
        <html>
          <head>
            <title>通知</title>
            <meta name="publishdate" content="2026-06-23 10:14:11">
          </head>
          <body><div class="v_news_content">正文没有发布时间，但内容足够长用于质量判断。</div></body>
        </html>
        """,
    )

    assert document.published_at.year == 2026
    assert document.published_at.month == 6
    assert document.published_at.day == 23
    assert document.date_confidence == "exact"


def test_extract_document_parses_date_from_page_info_outside_article_body():
    document = extract_document_from_html(
        "https://www.nuc.edu.cn/info/1001/1234.htm",
        "https://www.nuc.edu.cn/info/1001/1234.htm",
        """
        <html>
          <head><title>通知</title></head>
          <body>
            <div class="article-info">来源：学院 发布日期：2026年06月22日</div>
            <div class="v_news_content">正文容器里没有日期，但这是需要公开的文章正文。</div>
          </body>
        </html>
        """,
    )

    assert document.published_at.year == 2026
    assert document.published_at.month == 6
    assert document.published_at.day == 22


def test_parse_published_at_does_not_infer_bare_years():
    value = _parse_published_at("山西省2023年普通高校招生工作规定")
    class_year = _parse_published_at("中北大学2026届毕业生春季推荐简章")

    assert value is None
    assert class_year is None


def test_importance_score_penalizes_stale_articles():
    source = type("SourceObj", (), {"priority": Source.Priority.HIGH, "source_type": Source.SourceType.OFFICIAL_SITE})()
    recent = timezone.now() - timedelta(days=5)
    stale = timezone.now() - timedelta(days=900)

    recent_score = score_importance(source, "招生报名截止通知", "请考生按时提交材料。", "招生", recent)
    stale_score = score_importance(source, "招生报名截止通知", "请考生按时提交材料。", "招生", stale)

    assert recent_score > stale_score


def test_importance_score_never_goes_below_zero_for_old_low_signal_pages():
    source = type("SourceObj", (), {"priority": Source.Priority.LOW, "source_type": Source.SourceType.COLLEGE_SITE})()
    old_date = timezone.now() - timedelta(days=1000)

    score = score_importance(source, "Generic page", "Generic body", "", old_date)

    assert score == 0
