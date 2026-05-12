from dataclasses import dataclass
from urllib.parse import urljoin, urlsplit, urlunsplit

from bs4 import BeautifulSoup

from .urls import normalize_url


@dataclass(frozen=True)
class CrawlPlan:
    index_url: str
    article_urls: list[str]


def discover_article_links(html: str, base_url: str, max_links: int = 30) -> list[str]:
    soup = BeautifulSoup(html, "html.parser")
    base_host = urlsplit(base_url).hostname or ""
    links: list[str] = []
    seen = set()
    for anchor in soup.find_all("a", href=True):
        href = anchor["href"].strip()
        absolute = normalize_url(urljoin(base_url, href))
        if absolute in seen:
            continue
        if not _same_or_child_domain(base_host, absolute):
            continue
        if not _looks_like_article_url(absolute):
            continue
        seen.add(absolute)
        links.append(absolute)
        if len(links) >= max_links:
            break
    return links


def discover_listing_links(html: str, base_url: str, max_links: int = 12) -> list[str]:
    soup = BeautifulSoup(html, "html.parser")
    base_host = urlsplit(base_url).hostname or ""
    links: list[str] = []
    seen = {normalize_url(base_url)}
    for anchor in soup.find_all("a", href=True):
        href = anchor["href"].strip()
        absolute = normalize_url(urljoin(base_url, href))
        text = " ".join(anchor.get_text(" ", strip=True).split()).lower()
        if absolute in seen:
            continue
        if not _same_or_child_domain(base_host, absolute):
            continue
        if _looks_like_article_url(absolute):
            continue
        if not _looks_like_listing_url(absolute, text):
            continue
        seen.add(absolute)
        links.append(absolute)
        if len(links) >= max_links:
            break
    return links


def discover_school_sources(html: str, base_url: str) -> list[tuple[str, str]]:
    soup = BeautifulSoup(html, "html.parser")
    sources: list[tuple[str, str]] = []
    seen = set()
    for anchor in soup.find_all("a", href=True):
        name = " ".join(anchor.get_text(" ", strip=True).split())
        if not name or "学院" not in name:
            continue
        absolute = _canonical_site_url(urljoin(base_url, anchor["href"].strip()))
        host = urlsplit(absolute).hostname or ""
        if not host.endswith(".nuc.edu.cn") and host != "nuc.edu.cn":
            continue
        if absolute in seen:
            continue
        seen.add(absolute)
        sources.append((name, absolute))
    return sources


def is_article_url(url: str) -> bool:
    return _looks_like_article_url(url)


def is_listing_url(url: str, text: str = "") -> bool:
    return _looks_like_listing_url(url, text)


def _looks_like_article_url(url: str) -> bool:
    parsed = urlsplit(url)
    path = parsed.path.lower()
    query = parsed.query.lower()
    if "/info/" in path and path.endswith((".htm", ".html")):
        return True
    if path.rstrip("/") == "/detail/news" and "id=" in query:
        return True
    if path.endswith("/content.jsp") and "wbnewsid=" in query:
        return True
    return False


def _looks_like_listing_url(url: str, text: str) -> bool:
    parsed = urlsplit(url)
    href_key = parsed.path.lower()
    if parsed.scheme not in {"http", "https"}:
        return False
    if href_key.endswith((".jpg", ".jpeg", ".png", ".gif", ".pdf", ".doc", ".docx", ".xls", ".xlsx", ".zip")):
        return False
    signals = (
        "xwdt",
        "tzgg",
        "news",
        "notice",
        "list",
        "jwdt",
        "xyxw",
        "xygg",
        "bks",
        "yjs",
        "zs",
        "jy",
        "ky",
        "通知",
        "公告",
        "新闻",
        "动态",
        "招生",
        "就业",
        "科研",
        "学术",
    )
    combined = f"{href_key} {text}"
    return any(signal in combined for signal in signals)


def _same_or_child_domain(base_host: str, url: str) -> bool:
    host = urlsplit(url).hostname or ""
    return host == base_host or host.endswith(f".{base_host}")


def _canonical_site_url(url: str) -> str:
    parsed = urlsplit(normalize_url(url))
    path = parsed.path
    if path in ("", "/"):
        return urlunsplit((parsed.scheme, parsed.netloc, "/", "", ""))
    return urlunsplit((parsed.scheme, parsed.netloc, path, "", ""))
