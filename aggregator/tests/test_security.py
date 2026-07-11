import httpx
import pytest

from aggregator.services.fetching import FetchError, fetch_url


def test_fetch_url_blocks_private_ip_before_network_request(monkeypatch, settings):
    settings.CRAWL_BLOCK_PRIVATE_NETWORKS = True
    called = []
    monkeypatch.setattr("aggregator.services.fetching.httpx.get", lambda *args, **kwargs: called.append(args))

    with pytest.raises(FetchError, match="private or reserved"):
        fetch_url("http://127.0.0.1/admin")

    assert called == []


def test_fetch_url_revalidates_every_redirect_target(monkeypatch, settings):
    settings.CRAWL_BLOCK_PRIVATE_NETWORKS = True
    settings.CRAWL_DIRECT_RETRY_ATTEMPTS = 1
    settings.CRAWL_RELAY_URL = ""
    calls = []

    monkeypatch.setattr(
        "aggregator.services.urls.socket.getaddrinfo",
        lambda host, port, type=0: [(2, 1, 6, "", ("8.8.8.8", port))],
    )

    class RedirectResponse:
        status_code = 302
        headers = {"location": "http://169.254.169.254/latest/meta-data"}
        url = "https://public.example/start"
        text = ""

        def raise_for_status(self):
            return None

    def fake_get(url, **kwargs):
        calls.append(url)
        return RedirectResponse()

    monkeypatch.setattr("aggregator.services.fetching.httpx.get", fake_get)

    with pytest.raises(FetchError, match="private or reserved"):
        fetch_url("https://public.example/start")

    assert calls == ["https://public.example/start"]
