import pytest
from django.core.cache import cache
from django.urls import reverse

from django.utils import timezone

from aggregator.models import Category, ContentItem, ContentSource, CrawlFailure, CrawlJob, Source


@pytest.fixture(autouse=True)
def clear_page_cache():
    cache.clear()


@pytest.mark.django_db
def test_homepage_lists_published_items(client):
    source = Source.objects.create(
        name="中北大学官网",
        url="https://www.nuc.edu.cn/",
        source_type=Source.SourceType.OFFICIAL_SITE,
    )
    category = Category.objects.create(name="通知", slug="notice")
    ContentItem.objects.create(
        source=source,
        category=category,
        title="中北大学发布重要通知",
        canonical_url="https://www.nuc.edu.cn/info/1001/1234.htm",
        summary="这是一条来自中北大学官网的摘要。",
        content_text="全文仅用于检索和去重。",
        status=ContentItem.Status.PUBLISHED,
        source_published_at=timezone.datetime(2026, 1, 2, tzinfo=timezone.get_current_timezone()),
    )

    response = client.get(reverse("aggregator:home"))

    assert response.status_code == 200
    assert "中北大学发布重要通知" in response.content.decode()
    assert "原文" in response.content.decode()


@pytest.mark.django_db
def test_public_navigation_hides_admin_and_points_to_agent_project(client):
    response = client.get(reverse("aggregator:home"))
    html = response.content.decode()

    assert response.status_code == 200
    assert 'href="/admin/"' not in html
    assert 'href="/agent/"' in html
    assert "Agent 项目" in html


@pytest.mark.django_db
def test_homepage_displays_source_published_at(client):
    source = Source.objects.create(
        name="中北大学官网",
        url="https://www.nuc.edu.cn/",
        source_type=Source.SourceType.OFFICIAL_SITE,
    )
    ContentItem.objects.create(
        source=source,
        title="显示原文时间",
        canonical_url="https://www.nuc.edu.cn/info/1001/time.htm",
        summary="摘要",
        content_text="正文",
        status=ContentItem.Status.PUBLISHED,
        is_public=True,
        published_at=timezone.datetime(2026, 5, 25, 18, 0, tzinfo=timezone.get_current_timezone()),
        source_published_at=timezone.datetime(2026, 5, 20, 9, 30, tzinfo=timezone.get_current_timezone()),
    )

    response = client.get(reverse("aggregator:home"))
    html = response.content.decode()

    assert "2026-05-20 09:30" in html
    assert "2026-05-25 18:00" not in html


@pytest.mark.django_db
def test_homepage_displays_year_only_dates_as_uncertain(client):
    source = Source.objects.create(
        name="中北大学官网",
        url="https://www.nuc.edu.cn/",
        source_type=Source.SourceType.OFFICIAL_SITE,
    )
    ContentItem.objects.create(
        source=source,
        title="年份级日期",
        canonical_url="https://www.nuc.edu.cn/info/1001/year.htm",
        summary="摘要",
        content_text="正文",
        status=ContentItem.Status.PUBLISHED,
        is_public=True,
        date_confidence=ContentItem.DateConfidence.YEAR_ONLY,
        source_published_at=timezone.datetime(2026, 1, 1, tzinfo=timezone.get_current_timezone()),
    )

    response = client.get(reverse("aggregator:home"))
    html = response.content.decode()

    assert "2026 年（日期待确认）" in html
    assert "2026-01-01 00:00" not in html


@pytest.mark.django_db
def test_unpublished_items_are_hidden(client):
    source = Source.objects.create(
        name="中北大学官网",
        url="https://www.nuc.edu.cn/",
        source_type=Source.SourceType.OFFICIAL_SITE,
    )
    ContentItem.objects.create(
        source=source,
        title="内部待处理内容",
        canonical_url="https://www.nuc.edu.cn/info/1001/9999.htm",
        summary="不应公开",
        content_text="不应公开",
        status=ContentItem.Status.CLEANED,
    )

    response = client.get(reverse("aggregator:home"))

    assert response.status_code == 200
    assert "内部待处理内容" not in response.content.decode()


@pytest.mark.django_db
def test_items_that_are_not_public_are_hidden(client):
    source = Source.objects.create(
        name="NUC",
        url="https://www.nuc.edu.cn/",
        source_type=Source.SourceType.OFFICIAL_SITE,
    )
    ContentItem.objects.create(
        source=source,
        title="Hidden candidate",
        canonical_url="https://www.nuc.edu.cn/info/1001/hidden.htm",
        summary="Hidden",
        content_text="Hidden",
        status=ContentItem.Status.PUBLISHED,
        is_public=False,
        source_published_at=timezone.datetime(2026, 1, 2, tzinfo=timezone.get_current_timezone()),
    )

    response = client.get(reverse("aggregator:home"))

    assert response.status_code == 200
    assert "Hidden candidate" not in response.content.decode()


@pytest.mark.django_db
def test_items_before_public_since_date_are_hidden(client):
    source = Source.objects.create(
        name="NUC",
        url="https://www.nuc.edu.cn/",
        source_type=Source.SourceType.OFFICIAL_SITE,
    )
    ContentItem.objects.create(
        source=source,
        title="Old public item",
        canonical_url="https://www.nuc.edu.cn/info/1001/old.htm",
        summary="Old",
        content_text="Old",
        status=ContentItem.Status.PUBLISHED,
        is_public=True,
        source_published_at=timezone.datetime(2025, 12, 31, tzinfo=timezone.get_current_timezone()),
    )

    response = client.get(reverse("aggregator:home"))

    assert response.status_code == 200
    assert "Old public item" not in response.content.decode()


@pytest.mark.django_db
def test_future_source_dates_are_hidden(client):
    source = Source.objects.create(
        name="NUC",
        url="https://www.nuc.edu.cn/",
        source_type=Source.SourceType.OFFICIAL_SITE,
    )
    ContentItem.objects.create(
        source=source,
        title="Future public item",
        canonical_url="https://www.nuc.edu.cn/info/1001/future.htm",
        summary="Future",
        content_text="Future",
        status=ContentItem.Status.PUBLISHED,
        is_public=True,
        source_published_at=timezone.now() + timezone.timedelta(days=1),
    )

    response = client.get(reverse("aggregator:home"))

    assert response.status_code == 200
    assert "Future public item" not in response.content.decode()


@pytest.mark.django_db
def test_detail_page_lists_all_content_sources(client):
    first = Source.objects.create(name="Official", url="https://www.nuc.edu.cn/", source_type=Source.SourceType.OFFICIAL_SITE)
    second = Source.objects.create(name="College", url="https://cst.nuc.edu.cn/", source_type=Source.SourceType.COLLEGE_SITE)
    item = ContentItem.objects.create(
        source=first,
        title="Shared notice",
        canonical_url="https://www.nuc.edu.cn/info/1001/shared.htm",
        summary="Shared",
        content_text="Shared body",
        status=ContentItem.Status.PUBLISHED,
        is_public=True,
        source_published_at=timezone.datetime(2026, 1, 2, tzinfo=timezone.get_current_timezone()),
    )
    ContentSource.objects.create(content_item=item, source=first, url="https://www.nuc.edu.cn/info/1001/shared.htm")
    ContentSource.objects.create(content_item=item, source=second, url="https://cst.nuc.edu.cn/info/2001/shared.htm")

    response = client.get(reverse("aggregator:item_detail", args=[item.id]))
    html = response.content.decode()

    assert response.status_code == 200
    assert "Official" in html
    assert "College" in html
    assert "https://cst.nuc.edu.cn/info/2001/shared.htm" in html


@pytest.mark.django_db
def test_homepage_orders_by_importance_before_recency(client):
    source = Source.objects.create(
        name="中北大学官网",
        url="https://www.nuc.edu.cn/",
        source_type=Source.SourceType.OFFICIAL_SITE,
    )
    category = Category.objects.create(name="通知", slug="notice")
    ContentItem.objects.create(
        source=source,
        category=category,
        title="普通新闻",
        canonical_url="https://www.nuc.edu.cn/info/1001/1.htm",
        summary="普通新闻",
        content_text="普通新闻",
        status=ContentItem.Status.PUBLISHED,
        importance_score=10,
        source_published_at=timezone.datetime(2026, 1, 2, tzinfo=timezone.get_current_timezone()),
    )
    ContentItem.objects.create(
        source=source,
        category=category,
        title="重要通知",
        canonical_url="https://www.nuc.edu.cn/info/1001/2.htm",
        summary="重要通知",
        content_text="重要通知",
        status=ContentItem.Status.PUBLISHED,
        importance_score=90,
        source_published_at=timezone.datetime(2026, 1, 2, tzinfo=timezone.get_current_timezone()),
    )

    response = client.get(reverse("aggregator:home"))
    html = response.content.decode()

    assert html.index("重要通知") < html.index("普通新闻")


@pytest.mark.django_db
def test_new_social_source_defaults_to_daily_crawl():
    source = Source.objects.create(
        name="抖音中北账号",
        url="https://www.douyin.com/user/example",
        source_type=Source.SourceType.SOCIAL_LINK,
    )

    assert source.crawl_interval_minutes == 1440


@pytest.mark.django_db
def test_search_with_meili_hits_uses_sort_context(client, monkeypatch):
    source = Source.objects.create(
        name="创新创业学院",
        url="https://cxcy.nuc.edu.cn/",
        source_type=Source.SourceType.COLLEGE_SITE,
    )
    item = ContentItem.objects.create(
        source=source,
        title="关于创新创业学院举办教学沙龙的通知",
        canonical_url="https://cxcy.nuc.edu.cn/info/1001/search.htm",
        summary="创新创业学院通知",
        content_text="教学沙龙",
        status=ContentItem.Status.PUBLISHED,
        is_public=True,
        source_published_at=timezone.datetime(2026, 6, 20, tzinfo=timezone.get_current_timezone()),
    )

    monkeypatch.setattr("aggregator.views.meili_search", lambda query, filters=None: [{"id": item.id}])

    response = client.get(reverse("aggregator:search"), {"q": "创新创业学院"})

    assert response.status_code == 200
    assert "关于创新创业学院举办教学沙龙的通知" in response.content.decode()


@pytest.mark.django_db
def test_robots_txt_points_to_sitemap(client, settings):
    settings.PUBLIC_SITE_BASE_URL = "http://testserver"

    response = client.get("/robots.txt")

    assert response.status_code == 200
    assert response["Content-Type"].startswith("text/plain")
    assert "Disallow: /admin/" in response.content.decode()
    assert "Sitemap: http://testserver/sitemap-index.xml" in response.content.decode()


def test_favicon_returns_image(client):
    response = client.get("/favicon.ico")

    assert response.status_code == 200
    assert response["Content-Type"].startswith("image/svg+xml")


@pytest.mark.django_db
def test_sitemap_xml_includes_homepage(client, settings):
    settings.PUBLIC_SITE_BASE_URL = "http://testserver"

    response = client.get("/sitemap.xml")

    assert response.status_code == 200
    assert response["Content-Type"].startswith("application/xml")
    assert "<loc>http://testserver/</loc>" in response.content.decode()


@pytest.mark.django_db
def test_sitemap_index_and_chunks_cover_more_than_one_page(client, settings):
    settings.PUBLIC_SITE_BASE_URL = "http://testserver"
    source = Source.objects.create(
        name="站点地图来源",
        url="https://sitemap.example.edu/",
        source_type=Source.SourceType.OFFICIAL_SITE,
    )
    ContentItem.objects.bulk_create(
        [
            ContentItem(
                source=source,
                title=f"地图内容 {index}",
                canonical_url=f"https://sitemap.example.edu/items/{index}",
                summary="摘要",
                content_text="正文",
                status=ContentItem.Status.PUBLISHED,
                is_public=True,
                source_published_at=timezone.datetime(2026, 7, 1, tzinfo=timezone.get_current_timezone()),
            )
            for index in range(501)
        ]
    )

    index_response = client.get("/sitemap-index.xml")
    first_chunk = client.get("/sitemap.xml")
    second_chunk = client.get("/sitemap-items-2.xml")

    assert index_response.status_code == 200
    assert "sitemap-items-2.xml" in index_response.content.decode()
    assert first_chunk.status_code == 200
    assert second_chunk.status_code == 200
    assert first_chunk.content.decode().count("<url>") <= 500
    assert second_chunk.content.decode().count("<url>") <= 500
    assert "/items/501/" in second_chunk.content.decode()


@pytest.mark.django_db
def test_healthz_reports_freshness_fields(client):
    source = Source.objects.create(
        name="健康检查来源",
        url="https://health.example.edu/",
        source_type=Source.SourceType.OFFICIAL_SITE,
        last_success_at=timezone.datetime(2026, 7, 12, 8, 0, tzinfo=timezone.get_current_timezone()),
    )
    ContentItem.objects.create(
        source=source,
        title="最新公开内容",
        canonical_url="https://health.example.edu/latest",
        summary="摘要",
        content_text="正文",
        status=ContentItem.Status.PUBLISHED,
        is_public=True,
        source_published_at=timezone.datetime(2026, 7, 12, 9, 0, tzinfo=timezone.get_current_timezone()),
    )

    response = client.get("/healthz")
    payload = response.json()

    assert response.status_code == 200
    assert payload["latest_public_item_at"]
    assert payload["last_crawl_success_at"]


@pytest.mark.django_db
def test_healthz_marks_stale_or_excessive_source_failures_as_unhealthy(settings, client):
    settings.SOURCE_FRESHNESS_HOURS = 1
    settings.SOURCE_OPEN_FAILURE_THRESHOLD = 0
    source = Source.objects.create(
        name="过期来源",
        url="https://stale.example.edu/",
        source_type=Source.SourceType.OFFICIAL_SITE,
        last_success_at=timezone.now() - timezone.timedelta(hours=2),
    )
    job = CrawlJob.objects.create(source=source, target_url=source.url)
    CrawlFailure.objects.create(crawl_job=job, source=source, url=source.url)

    payload = client.get("/healthz").json()

    assert payload["source_health_ok"] is False
    assert set(payload["source_health_alerts"]) == {"crawl_stale", "open_failures"}


@pytest.mark.django_db
def test_healthz_gates_only_actionable_failures_and_keeps_open_failure_count_compatible(settings, client):
    settings.SOURCE_FRESHNESS_HOURS = 24
    settings.SOURCE_OPEN_FAILURE_THRESHOLD = 0
    source = Source.objects.create(
        name="已确认永久失败来源",
        url="https://acknowledged-health.example.edu/",
        source_type=Source.SourceType.OFFICIAL_SITE,
        last_success_at=timezone.now(),
    )
    job = CrawlJob.objects.create(source=source, target_url=source.url)
    CrawlFailure.objects.create(
        crawl_job=job,
        source=source,
        url=source.url,
        failure_class=CrawlFailure.FailureClass.PERMANENT,
        permanent=True,
        http_status=404,
        acknowledged_at=timezone.now(),
        acknowledged_status=404,
        acknowledged_note="Confirmed by operator",
    )

    payload = client.get("/healthz").json()

    assert payload["source_health_ok"] is True
    assert payload["open_failures"] == 1
    assert payload["actionable_failures"] == 0
    assert payload["acknowledged_permanent_failures"] == 1


@pytest.mark.django_db
def test_invalid_date_filter_is_user_safe(client):
    response = client.get(reverse("aggregator:search"), {"date_from": "not-a-date"})

    assert response.status_code == 200
    assert "日期格式无效" in response.content.decode()
