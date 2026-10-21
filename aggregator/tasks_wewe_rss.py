import logging
import time
import re
import xml.etree.ElementTree as ET
from datetime import datetime, timezone

import httpx
from bs4 import BeautifulSoup
from celery import shared_task
from django.conf import settings
from django.db import transaction
from django.db.models import Q
from django.utils import timezone as django_timezone

from .models import ContentItem, ContentSource, Source, CrawlJob, CrawlFailure
from .services.extraction import ExtractedDocument, extract_document_from_html
from .services.pipeline import ingest_extracted_document, _record_crawl_failure, _mark_crawl_failure_resolved

logger = logging.getLogger(__name__)

WEWE_RSS_FEED = getattr(settings, "WEWE_RSS_FEED_URL", "http://localhost:4000/feeds/all.atom")
WEWE_RSS_AUTH = getattr(settings, "WEWE_RSS_AUTH_CODE", "")
WEWE_RSS_SOURCE_NAME = getattr(settings, "WEWE_RSS_SOURCE_NAME", "微信公众号")

CHROME_UA = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
    "AppleWebKit/537.36 (KHTML, like Gecko) "
    "Chrome/125.0.0.0 Safari/537.36"
)

ATOM_NS = "http://www.w3.org/2005/Atom"

MAX_ARTICLES_PER_RUN = 9999
RSS_LIMIT = 9999


def _parse_atom_entries(xml_text: str) -> list[dict]:
    root = ET.fromstring(xml_text)
    entries = []
    for entry in root.findall(f"{{{ATOM_NS}}}entry"):
        title_el = entry.find(f"{{{ATOM_NS}}}title")
        link_el = entry.find(f"{{{ATOM_NS}}}link")
        updated_el = entry.find(f"{{{ATOM_NS}}}updated")
        author_el = entry.find(f"{{{ATOM_NS}}}author")
        name_el = author_el.find(f"{{{ATOM_NS}}}name") if author_el is not None else None

        url = link_el.get("href", "").strip() if link_el is not None else ""
        entries.append({
            "title": (title_el.text or "").strip() if title_el is not None else "",
            "url": url,
            "published": (updated_el.text or "").strip() if updated_el is not None else "",
            "author": (name_el.text or "").strip() if name_el is not None else "",
        })
    return entries


def _extract_wechat_title(html: str) -> str:
    soup = BeautifulSoup(html, "html.parser")
    og_title = soup.find("meta", property="og:title")
    if og_title and og_title.get("content"):
        return og_title["content"].strip()
    h1 = soup.find("h1")
    if h1:
        return h1.get_text(strip=True)[:300]
    if soup.title:
        text = soup.title.get_text(strip=True)
        if text:
            return text[:300]
    return ""


def _extract_wechat_publish_time(html: str) -> datetime | None:
    match = re.search(r'var\s+(?:create_time|ct)\s*=\s*["\']?(\d{10})["\']?', html)
    if match:
        ts = int(match.group(1))
        return datetime.fromtimestamp(ts, tz=timezone.utc)
    return None


def _make_extracted_document(
    url: str, final_url: str, html: str, status_code: int, published_at: datetime | None
) -> ExtractedDocument:
    doc = extract_document_from_html(url, final_url, html, status_code=status_code)
    title = _extract_wechat_title(html)
    if title and not doc.title:
        doc = ExtractedDocument(
            url=doc.url, final_url=doc.final_url, title=title,
            html=doc.html, text=doc.text, image_urls=doc.image_urls,
            published_at=doc.published_at or published_at,
            date_confidence="exact" if (doc.published_at or published_at) else doc.date_confidence,
            fetch_via=doc.fetch_via, status_code=doc.status_code,
        )
    if published_at and not doc.published_at:
        doc = ExtractedDocument(
            url=doc.url, final_url=doc.final_url, title=doc.title,
            html=doc.html, text=doc.text, image_urls=doc.image_urls,
            published_at=published_at, date_confidence="exact",
            fetch_via=doc.fetch_via, status_code=doc.status_code,
        )
    return doc


def _get_with_retry(url, **kwargs):
    """Retry safe GETs only; errors are recorded once by the caller."""
    for attempt in range(3):
        try:
            response = httpx.get(url, timeout=30, **kwargs)
            response.raise_for_status()
            return response
        except (httpx.TransportError, httpx.HTTPStatusError) as exc:
            status = exc.response.status_code if isinstance(exc, httpx.HTTPStatusError) else None
            if attempt == 2 or (status is not None and status != 429 and status < 500):
                raise
            delay = 2 ** attempt
            if status == 429:
                try:
                    delay = min(30, max(delay, int(exc.response.headers.get("Retry-After", delay))))
                except ValueError:
                    pass
            time.sleep(delay)


@shared_task
def fetch_wewe_rss():
    source, _ = Source.objects.get_or_create(
        name=WEWE_RSS_SOURCE_NAME,
        defaults={"url": WEWE_RSS_FEED, "source_type": Source.SourceType.MANUAL_URL,
                  "crawl_interval_minutes": 360, "enabled": True, "crawl_enabled": True},
    )
    with transaction.atomic():
        source = Source.objects.select_for_update().get(pk=source.pk)
        if not source.enabled or not source.crawl_enabled:
            return 0
        if CrawlJob.objects.filter(source=source, status=CrawlJob.Status.RUNNING).exists():
            return 0
        job = CrawlJob.objects.create(source=source, target_url=WEWE_RSS_FEED,
                                      status=CrawlJob.Status.RUNNING, started_at=django_timezone.now())
        source.last_crawled_at = django_timezone.now()
        source.save(update_fields=["last_crawled_at", "updated_at"])
    count = 0
    try:
        headers = {"Authorization": WEWE_RSS_AUTH} if WEWE_RSS_AUTH else {}
        response = _get_with_retry(WEWE_RSS_FEED, params={"limit": RSS_LIMIT}, headers=headers)
        entries = _parse_atom_entries(response.text)
        _mark_crawl_failure_resolved(source, WEWE_RSS_FEED)
        # Keep failed URLs retryable even if they have fallen out of the current feed.
        current = {e["url"]: e for e in reversed(entries) if e["url"].startswith("https://mp.weixin.qq.com/")}
        due = CrawlFailure.objects.filter(source=source, resolved_at__isnull=True, permanent=False).filter(
            Q(next_retry_at__isnull=True) | Q(next_retry_at__lte=django_timezone.now()))
        for url in due.values_list("url", flat=True):
            if url.startswith("https://mp.weixin.qq.com/"):
                current.setdefault(url, {"url": url, "published": ""})
        urls = list(current)
        seen = set()
        blocked = set()
        for offset in range(0, len(urls), 300):
            batch = urls[offset:offset+300]
            seen.update(ContentItem.objects.filter(canonical_url__in=batch).values_list("canonical_url", flat=True))
            seen.update(ContentSource.objects.filter(url__in=batch).values_list("url", flat=True))
            blocked.update(CrawlFailure.objects.filter(source=source, url__in=batch, resolved_at__isnull=True).filter(
                Q(permanent=True) | Q(next_retry_at__gt=django_timezone.now())).values_list("url", flat=True))
        job.discovered_count = len(current)
        job.duplicate_skip_count = len(seen)
        job.save(update_fields=["discovered_count", "duplicate_skip_count", "updated_at"])
        for url, entry in current.items():
            if url in seen:
                _mark_crawl_failure_resolved(source, url)
                continue
            if url in blocked:
                continue
            try:
                html = _get_with_retry(url, headers={"User-Agent": CHROME_UA}, follow_redirects=True)
                published_at = _extract_wechat_publish_time(html.text)
                if published_at is None and entry.get("published"):
                    try:
                        published_at = datetime.fromisoformat(entry["published"].replace("Z", "+00:00"))
                    except (ValueError, TypeError):
                        pass
                doc = _make_extracted_document(url, str(html.url), html.text, html.status_code, published_at)
                ingest_extracted_document(source, doc, job)
            except Exception as exc:
                _record_crawl_failure(job, source, url, exc)
                continue
            _mark_crawl_failure_resolved(source, url)
            count += 1
        job.success_count = count
        unresolved = CrawlFailure.objects.filter(source=source, resolved_at__isnull=True, permanent=False).exists()
        job.status = CrawlJob.Status.FAILED if job.failed_url_count or unresolved else CrawlJob.Status.SUCCEEDED
        job.error_message = "Some articles failed; pending retries are retained." if job.status == CrawlJob.Status.FAILED else ""
    except Exception as exc:
        _record_crawl_failure(job, source, WEWE_RSS_FEED, exc)
        job.status = CrawlJob.Status.FAILED
        job.error_message = type(exc).__name__ + ": feed fetch or parsing failed"
    job.finished_at = django_timezone.now()
    job.save(update_fields=["success_count", "status", "error_message", "finished_at", "updated_at"])
    source.refresh_from_db()
    if job.status == CrawlJob.Status.SUCCEEDED:
        source.last_success_at = job.finished_at
        source.failure_count = 0
    else:
        source.last_error_at = job.finished_at
        source.failure_count += 1
    source.save(update_fields=["last_success_at", "last_error_at", "failure_count", "updated_at"])
    logger.info("WeWe RSS import finished: status=%s imported=%d", job.status, count)
    return count
