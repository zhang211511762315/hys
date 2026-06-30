from dataclasses import dataclass
from contextlib import contextmanager, nullcontext
import socket
from urllib.parse import urljoin
from urllib.parse import urlsplit

import httpx
from django.conf import settings


@dataclass(frozen=True)
class FetchResult:
    url: str
    final_url: str
    text: str
    status_code: int
    headers: dict
    via: str


class FetchError(RuntimeError):
    pass


def fetch_url(url: str) -> FetchResult:
    if getattr(settings, "CRAWL_DIRECT_FIRST", True):
        try:
            return _fetch_direct(url)
        except Exception as exc:
            if not _should_try_relay(exc):
                raise
            if not settings.CRAWL_RELAY_URL:
                raise
            return _fetch_relay(url, exc)
    if settings.CRAWL_RELAY_URL:
        return _fetch_relay(url, None)
    return _fetch_direct(url)


def _fetch_direct(url: str) -> FetchResult:
    attempts = max(1, getattr(settings, "CRAWL_DIRECT_RETRY_ATTEMPTS", 2))
    last_exc = None
    for attempt in range(attempts):
        try:
            return _fetch_direct_once(url)
        except Exception as exc:
            last_exc = exc
            if attempt >= attempts - 1 or not _should_retry_direct(exc):
                raise
    raise last_exc


def _fetch_direct_once(url: str) -> FetchResult:
    context = _force_ipv4_for_url(url) if _should_force_ipv4(url) else nullcontext()
    with context:
        response = httpx.get(
            url,
            headers={"User-Agent": settings.CRAWL_USER_AGENT},
            follow_redirects=True,
            timeout=httpx.Timeout(settings.FETCH_TIMEOUT_SECONDS, connect=settings.FETCH_CONNECT_TIMEOUT_SECONDS),
        )
    response.raise_for_status()
    return FetchResult(
        url=url,
        final_url=str(response.url),
        text=response.text,
        status_code=response.status_code,
        headers=dict(response.headers),
        via="direct",
    )


def _should_retry_direct(exc: Exception) -> bool:
    return isinstance(exc, (httpx.ConnectError, httpx.ConnectTimeout, httpx.ReadTimeout, httpx.TimeoutException))


def _should_force_ipv4(url: str) -> bool:
    host = (urlsplit(url).hostname or "").lower()
    if not host:
        return False
    for domain in getattr(settings, "CRAWL_FORCE_IPV4_DOMAINS", []):
        domain = domain.lower()
        if domain.startswith(".") and host.endswith(domain):
            return True
        if host == domain or host.endswith(f".{domain}"):
            return True
    return False


@contextmanager
def _force_ipv4_for_url(url: str):
    target_host = (urlsplit(url).hostname or "").lower()
    original_getaddrinfo = socket.getaddrinfo

    def getaddrinfo(host, port, family=0, type=0, proto=0, flags=0):
        results = original_getaddrinfo(host, port, family, type, proto, flags)
        if (host or "").lower() != target_host:
            return results
        ipv4_results = [result for result in results if result[0] == socket.AF_INET]
        return ipv4_results or results

    socket.getaddrinfo = getaddrinfo
    try:
        yield
    finally:
        socket.getaddrinfo = original_getaddrinfo


def _fetch_relay(url: str, original_exc: Exception | None) -> FetchResult:
    headers = {"User-Agent": settings.CRAWL_USER_AGENT}
    if settings.CRAWL_RELAY_TOKEN:
        headers["Authorization"] = f"Bearer {settings.CRAWL_RELAY_TOKEN}"
    response = httpx.post(
        settings.CRAWL_RELAY_URL,
        headers=headers,
        json={"url": url},
        timeout=httpx.Timeout(settings.CRAWL_RELAY_TIMEOUT_SECONDS, connect=settings.FETCH_CONNECT_TIMEOUT_SECONDS),
    )
    response.raise_for_status()
    payload = response.json()
    status_code = int(payload.get("status") or payload.get("status_code") or 0)
    if status_code >= 400:
        raise FetchError(f"relay returned HTTP {status_code} for {url}")
    body = payload.get("body") or payload.get("text") or ""
    final_url = payload.get("final_url") or payload.get("url") or url
    if not body:
        raise FetchError(f"relay returned empty body for {url}")
    if original_exc is not None:
        headers["X-Original-Fetch-Error"] = f"{type(original_exc).__name__}: {original_exc}"
    return FetchResult(
        url=url,
        final_url=urljoin(url, final_url),
        text=body,
        status_code=status_code or 200,
        headers=payload.get("headers") or {},
        via="relay",
    )


def _should_try_relay(exc: Exception) -> bool:
    enabled_errors = {part.strip().lower() for part in settings.CRAWL_RELAY_ON_ERRORS.split(",") if part.strip()}
    if not enabled_errors:
        return False
    if isinstance(exc, (httpx.ConnectError, httpx.ConnectTimeout)):
        if "network is unreachable" in str(exc).lower() and "network" in enabled_errors:
            return True
        return bool({"connect", "dns", "network", "timeout"} & enabled_errors)
    if isinstance(exc, (httpx.ReadTimeout, httpx.TimeoutException)):
        return "timeout" in enabled_errors
    if isinstance(exc, httpx.HTTPStatusError):
        status_code = exc.response.status_code
        if status_code >= 500 and "5xx" in enabled_errors:
            return True
        if status_code == 429 and "429" in enabled_errors:
            return True
    return type(exc).__name__.lower() in enabled_errors
