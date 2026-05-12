import re
from urllib.parse import urlsplit

from aggregator.models import Source
from aggregator.services.urls import normalize_url


BLOCKED_EXTENSIONS = {
    ".7z",
    ".avi",
    ".doc",
    ".docx",
    ".gif",
    ".jpeg",
    ".jpg",
    ".mp3",
    ".mp4",
    ".pdf",
    ".png",
    ".ppt",
    ".pptx",
    ".rar",
    ".xls",
    ".xlsx",
    ".zip",
}
BLOCKED_PATH_TERMS = (
    "calendar",
    "download.jsp",
    "login",
    "logout",
    "search",
    "sousuo",
    "user",
    "virtual_attach",
    "wp-admin",
)
BLOCKED_QUERY_TERMS = ("keyword=", "search=", "urltype=news.downloadattachurl", "wbfileid=", "wd=", "q=")


def is_crawlable_url(source: Source, url: str) -> bool:
    normalized = normalize_url(url)
    parsed = urlsplit(normalized)
    if parsed.scheme not in {"http", "https"}:
        return False
    if not _host_allowed(source, parsed.hostname or ""):
        return False
    path = parsed.path.lower()
    query = parsed.query.lower()
    if any(token in path for token in ("<", ">", "%3c", "%3e")):
        return False
    if any(path.endswith(extension) for extension in BLOCKED_EXTENSIONS):
        return False
    if any(f"e={extension.lstrip('.')}" in query for extension in BLOCKED_EXTENSIONS):
        return False
    if any(term in path for term in BLOCKED_PATH_TERMS):
        return False
    if any(term in query for term in BLOCKED_QUERY_TERMS):
        return False
    if _has_deep_pagination(query):
        return False
    if _matches_denied_pattern(source, f"{path}?{query}"):
        return False
    prefixes = [prefix for prefix in getattr(source, "allowed_path_prefixes", []) if prefix]
    if prefixes and not any(parsed.path.startswith(prefix) for prefix in prefixes):
        return False
    return True


def _host_allowed(source: Source, host: str) -> bool:
    allowed_domains = [domain.lower() for domain in getattr(source, "allowed_domains", []) if domain]
    if not allowed_domains:
        source_host = urlsplit(source.url).hostname
        allowed_domains = [source_host.lower()] if source_host else []
    return any(host == domain or host.endswith(f".{domain}") for domain in allowed_domains)


def _matches_denied_pattern(source: Source, value: str) -> bool:
    for pattern in getattr(source, "denied_path_patterns", []) or []:
        try:
            if re.search(pattern, value, flags=re.IGNORECASE):
                return True
        except re.error:
            if pattern.lower() in value.lower():
                return True
    return False


def _has_deep_pagination(query: str) -> bool:
    for key, value in re.findall(r"(?:^|&)(page|p|pageindex|current)=(\d+)", query):
        if int(value) > 100:
            return True
    return False
