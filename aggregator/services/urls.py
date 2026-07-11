import ipaddress
import socket
from urllib.parse import parse_qsl, urlencode, urlsplit, urlunsplit

TRACKING_PREFIXES = ("utm_",)
TRACKING_PARAMS = {"spm", "from", "share_token", "timestamp", "isappinstalled"}


class UnsafeURLError(ValueError):
    pass


def normalize_url(url: str) -> str:
    parsed = urlsplit(url.strip())
    scheme = parsed.scheme.lower() or "https"
    netloc = parsed.netloc.lower()
    path = parsed.path or "/"
    query_pairs = []
    for key, value in parse_qsl(parsed.query, keep_blank_values=True):
        lowered = key.lower()
        if lowered in TRACKING_PARAMS or any(lowered.startswith(prefix) for prefix in TRACKING_PREFIXES):
            continue
        query_pairs.append((key, value))
    query = urlencode(sorted(query_pairs))
    return urlunsplit((scheme, netloc, path, query, ""))


def ensure_public_http_url(url: str) -> None:
    parsed = urlsplit((url or "").strip())
    if parsed.scheme not in {"http", "https"} or not parsed.hostname:
        raise UnsafeURLError("only absolute HTTP(S) URLs are allowed")
    if parsed.username or parsed.password:
        raise UnsafeURLError("URL credentials are not allowed")
    port = parsed.port or (443 if parsed.scheme == "https" else 80)
    try:
        literal_ip = ipaddress.ip_address(parsed.hostname)
    except ValueError:
        literal_ip = None
    if literal_ip is not None:
        resolved_ips = [literal_ip]
    else:
        try:
            addresses = socket.getaddrinfo(parsed.hostname, port, type=socket.SOCK_STREAM)
        except OSError as exc:
            raise UnsafeURLError("URL host could not be resolved") from exc
        if not addresses:
            raise UnsafeURLError("URL host could not be resolved")
        resolved_ips = [ipaddress.ip_address(address[4][0]) for address in addresses]
    for ip in resolved_ips:
        if not ip.is_global:
            raise UnsafeURLError(f"private or reserved network address is not allowed: {ip}")
