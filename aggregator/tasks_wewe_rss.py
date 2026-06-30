import logging
import re
import xml.etree.ElementTree as ET
from datetime import datetime, timezone

import httpx
from bs4 import BeautifulSoup
from celery import shared_task
from django.conf import settings

from .models import ContentItem, Source
from .services.extraction import ExtractedDocument, extract_document_from_html
from .services.pipeline import ingest_extracted_document

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


@shared_task
def fetch_wewe_rss():
    feed_url = WEWE_RSS_FEED
    auth_code = WEWE_RSS_AUTH
    source_name = WEWE_RSS_SOURCE_NAME

    source, _ = Source.objects.get_or_create(
        name=source_name,
        defaults={
            "url": feed_url,
            "source_type": Source.SourceType.MANUAL_URL,
            "crawl_interval_minutes": 360,
            "enabled": True,
            "crawl_enabled": True,
        },
    )

    headers = {}
    if auth_code:
        headers["Authorization"] = auth_code

    try:
        resp = httpx.get(feed_url + f"?limit={RSS_LIMIT}", headers=headers, timeout=30)
        resp.raise_for_status()
    except Exception as exc:
        logger.error("Failed to fetch WeWe RSS feed %s: %s", feed_url, exc)
        return 0

    entries = _parse_atom_entries(resp.text)
    if not entries:
        logger.info("WeWe RSS feed returned 0 entries")
        return 0

    seen_urls = set(
        ContentItem.objects.filter(
            canonical_url__startswith="https://mp.weixin.qq.com/"
        ).values_list("canonical_url", flat=True)
    )

    count = 0
    for entry in entries:
        if count >= MAX_ARTICLES_PER_RUN:
            break
        url = entry["url"]
        if not url or not url.startswith("https://mp.weixin.qq.com/"):
            continue
        if url in seen_urls:
            continue
        seen_urls.add(url)

        try:
            html_resp = httpx.get(
                url,
                headers={"User-Agent": CHROME_UA},
                follow_redirects=True,
                timeout=30,
            )
            html_resp.raise_for_status()
        except Exception as exc:
            logger.warning("Failed to fetch WeChat article %s: %s", url, exc)
            continue

        try:
            published_at = _extract_wechat_publish_time(html_resp.text)
            doc = _make_extracted_document(
                url, str(html_resp.url), html_resp.text,
                html_resp.status_code, published_at,
            )
        except Exception as exc:
            logger.warning("Failed to extract WeChat article %s: %s", url, exc)
            continue

        if entry["published"] and not doc.published_at:
            try:
                parsed = datetime.fromisoformat(entry["published"].replace("Z", "+00:00"))
                doc = ExtractedDocument(
                    url=doc.url, final_url=doc.final_url, title=doc.title,
                    html=doc.html, text=doc.text, image_urls=doc.image_urls,
                    published_at=parsed, date_confidence="exact",
                    fetch_via=doc.fetch_via, status_code=doc.status_code,
                )
            except (ValueError, TypeError):
                pass

        try:
            ingest_extracted_document(source, doc, None)
            count += 1
        except Exception as exc:
            logger.error("Failed to ingest %s: %s", url, exc)
            continue

    logger.info("WeWe RSS: ingested %d new articles", count)
    return count
