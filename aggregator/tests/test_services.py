from datetime import timedelta

from django.utils import timezone

from aggregator.services.ai import RuleBasedAIProvider
from aggregator.services.dedupe import content_fingerprint, is_near_duplicate
from aggregator.services.extraction import _parse_published_at
from aggregator.services.pipeline import _combine_ocr_text, ingest_source
from aggregator.services.importance import score_importance
from aggregator.services.scheduling import recommended_crawl_interval_minutes
from aggregator.services.urls import normalize_url
from aggregator.models import Source


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


def test_parse_published_at_infers_year_without_class_year():
    value = _parse_published_at("山西省2023年普通高校招生工作规定")
    class_year = _parse_published_at("中北大学2026届毕业生春季推荐简章")

    assert value.year == 2023
    assert value.month == 1
    assert value.day == 1
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
