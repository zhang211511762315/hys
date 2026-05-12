from dataclasses import dataclass
from datetime import datetime
import re

import httpx
from django.conf import settings
from django.utils import timezone
from bs4 import BeautifulSoup

from .dedupe import normalize_text
from .urls import normalize_url


@dataclass(frozen=True)
class ExtractedDocument:
    url: str
    final_url: str
    title: str
    html: str
    text: str
    image_urls: list[str]
    published_at: datetime | None = None
    date_confidence: str = "exact"


def fetch_and_extract(url: str) -> ExtractedDocument:
    normalized = normalize_url(url)
    response = httpx.get(
        normalized,
        headers={"User-Agent": "ZhongbeiInfoBot/0.1 (+https://example.local)"},
        follow_redirects=True,
        timeout=httpx.Timeout(settings.FETCH_TIMEOUT_SECONDS, connect=5.0),
    )
    response.raise_for_status()
    return extract_document_from_html(normalized, str(response.url), response.text)


def extract_document_from_html(url: str, final_url: str, html: str) -> ExtractedDocument:
    normalized = normalize_url(url)
    final = normalize_url(final_url or url)
    soup = BeautifulSoup(html, "html.parser")
    title = normalize_text(soup.title.get_text(" ")) if soup.title else final
    text = _extract_text(html)
    published_at, date_confidence = _parse_published_at_with_confidence(text)
    images = [normalize_url(src) for src in _extract_image_urls(soup, final)]
    return ExtractedDocument(
        url=normalized,
        final_url=final,
        title=title[:300],
        html=html,
        text=text,
        image_urls=images,
        published_at=published_at,
        date_confidence=date_confidence,
    )


def _extract_text(html: str) -> str:
    soup = BeautifulSoup(html, "html.parser")
    for selector in (".v_news_content", "#vsb_content", ".article", ".content", ".detail"):
        container = soup.select_one(selector)
        if not container:
            continue
        text = normalize_text(container.get_text(" "))
        if len(text) >= 30:
            return text
    try:
        import trafilatura

        extracted = trafilatura.extract(html, include_comments=False, include_tables=True)
        if extracted:
            return normalize_text(extracted)
    except Exception:
        pass
    for node in soup(["script", "style", "noscript"]):
        node.decompose()
    return normalize_text(soup.get_text(" "))


def _extract_image_urls(soup: BeautifulSoup, base_url: str) -> list[str]:
    from urllib.parse import urljoin

    image_urls = []
    for img in soup.find_all("img"):
        src = img.get("src") or img.get("data-src")
        if src:
            image_urls.append(urljoin(base_url, src))
    return image_urls


def _parse_published_at(text: str) -> datetime | None:
    value, _confidence = _parse_published_at_with_confidence(text)
    return value


def _parse_published_at_with_confidence(text: str) -> tuple[datetime | None, str]:
    patterns = [
        r"(?:发布时间|发布日期|时间)[:：\s]*(20\d{2})[年./-](\d{1,2})[月./-](\d{1,2})",
        r"\b(20\d{2})-(\d{1,2})-(\d{1,2})\b",
        r"\b(20\d{2})\.(\d{1,2})\.(\d{1,2})\b",
        r"\b(20\d{2})/(\d{1,2})/(\d{1,2})\b",
    ]
    for pattern in patterns:
        match = re.search(pattern, text)
        if not match:
            continue
        year, month, day = (int(value) for value in match.groups()[:3])
        try:
            return timezone.make_aware(datetime(year, month, day), timezone.get_current_timezone()), "exact"
        except ValueError:
            continue
    year_match = re.search(r"(20\d{2})年(?!届)", text)
    if year_match:
        year = int(year_match.group(1))
        return timezone.make_aware(datetime(year, 1, 1), timezone.get_current_timezone()), "year_only"
    return None, "unknown"
