from dataclasses import dataclass
from datetime import datetime
import re

from django.utils import timezone
from bs4 import BeautifulSoup

from .dedupe import normalize_text
from .fetching import fetch_url
from .urls import normalize_url


EXPIRED_PAGE_MARKERS = (
    "该信息不存在或已过期",
    "信息不存在或已过期",
    "页面不存在",
)


class ExtractionError(ValueError):
    pass


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
    fetch_via: str = "direct"
    status_code: int = 200


def fetch_and_extract(url: str) -> ExtractedDocument:
    normalized = normalize_url(url)
    response = fetch_url(normalized)
    return extract_document_from_html(
        normalized,
        response.final_url,
        response.text,
        fetch_via=response.via,
        status_code=response.status_code,
    )


def extract_document_from_html(
    url: str,
    final_url: str,
    html: str,
    fetch_via: str = "direct",
    status_code: int = 200,
) -> ExtractedDocument:
    normalized = normalize_url(url)
    final = normalize_url(final_url or url)
    soup = BeautifulSoup(html, "html.parser")
    title = normalize_text(soup.title.get_text(" ")) if soup.title else final
    text = _extract_text(html)
    if any(marker in text for marker in EXPIRED_PAGE_MARKERS):
        raise ExtractionError("page is missing or expired")
    published_at, date_confidence = _parse_published_at_from_page(soup, text)
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
        fetch_via=fetch_via,
        status_code=status_code,
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
    if not soup.find():
        return normalize_text(html)
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


def _parse_published_at_from_page(soup: BeautifulSoup, extracted_text: str) -> tuple[datetime | None, str]:
    candidates = []
    candidates.extend(_meta_date_values(soup))
    candidates.extend(_visible_date_node_values(soup))
    candidates.append(extracted_text)
    candidates.append(_full_visible_text(soup))
    for candidate in candidates:
        published_at, confidence = _parse_published_at_with_confidence(candidate or "")
        if published_at is not None:
            return published_at, confidence
    return None, "unknown"


def _meta_date_values(soup: BeautifulSoup) -> list[str]:
    keys = {
        "article:published_time",
        "article:modified_time",
        "date",
        "dc.date",
        "dc.date.issued",
        "dcterms.created",
        "dcterms.modified",
        "pubdate",
        "publishdate",
        "publish_time",
        "published_time",
        "publication_date",
        "release_date",
    }
    values = []
    for tag in soup.find_all("meta"):
        name = (tag.get("name") or tag.get("property") or tag.get("itemprop") or "").strip().lower()
        if name in keys:
            values.append(tag.get("content") or "")
    for tag in soup.find_all(["time"]):
        values.append(tag.get("datetime") or tag.get_text(" "))
    return values


def _visible_date_node_values(soup: BeautifulSoup) -> list[str]:
    selectors = (
        ".arti_metas",
        ".article-date",
        ".article-time",
        ".article-info",
        ".article_info",
        ".article-meta",
        ".article_meta",
        ".article_about",
        ".article_about_l",
        ".con_time",
        ".con_date",
        ".creat-date",
        ".create-date",
        ".createTime",
        ".createdate",
        ".date",
        ".date-post",
        ".detail_date",
        ".detail-time",
        ".detail_time",
        ".detail-info",
        ".detail_info",
        ".info",
        ".info-date",
        ".info-date-time",
        ".meta-date",
        ".news-date",
        ".news-time",
        ".news-info",
        ".news_info",
        ".news_about",
        ".news_meta",
        ".news_title_other",
        ".page-date",
        ".page-time",
        ".post-date",
        ".post-time",
        ".pub-date",
        ".pub-time",
        ".pubtime",
        ".publish",
        ".release-date",
        ".release-time",
        ".time-info",
        ".time-date",
        ".update-date",
        ".update-time",
        ".source",
        ".time",
        ".v_news_info",
        "#pubtime",
        "#publishTime",
        "#publish_time",
        "#pub_date",
        "#publish_date",
        "#PublishTime",
        "#createtime",
        "#createTime",
        "#release_date",
    )
    values = []
    for selector in selectors:
        for node in soup.select(selector):
            values.append(node.get_text(" "))
    return values


def _full_visible_text(soup: BeautifulSoup) -> str:
    soup = BeautifulSoup(str(soup), "html.parser")
    for node in soup(["script", "style", "noscript"]):
        node.decompose()
    return normalize_text(soup.get_text(" "))


def _parse_published_at_with_confidence(text: str) -> tuple[datetime | None, str]:
    patterns = [
        r"(?:发布时间|发布日期|发布于|更新时间|时间|日期|Date|Published)[:：\s]*(20\d{2})\s*[年./-]\s*(\d{1,2})\s*[月./-]\s*(\d{1,2})",
        r"(20\d{2})\s*年\s*(\d{1,2})\s*月\s*(\d{1,2})\s*日?",
        r"\b(20\d{2})-(\d{1,2})-(\d{1,2})(?:[T\s]\d{1,2}:\d{1,2}(?::\d{1,2})?(?:Z|[+-]\d{2}:?\d{2})?)?\b",
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
    return None, "unknown"
