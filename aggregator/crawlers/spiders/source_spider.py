from urllib.parse import urljoin
from types import SimpleNamespace

import scrapy
from bs4 import BeautifulSoup
from django.conf import settings

from aggregator.crawlers.items import CrawledPageItem
from aggregator.services.crawl_rules import is_crawlable_url
from aggregator.services.discovery import is_article_url, is_listing_url
from aggregator.services.urls import normalize_url


class SourceSpider(scrapy.Spider):
    name = "source_spider"

    def __init__(self, source_records=None, mode="bootstrap", since=None, max_pages_per_source=None, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.mode = mode
        self.since = since
        self.max_pages_per_source = int(max_pages_per_source) if max_pages_per_source else None
        self.source_records = source_records or []
        self.sources = {
            int(record["id"]): SimpleNamespace(**record)
            for record in self.source_records
        }
        self.scheduled: set[tuple[int, str]] = set()
        self.scheduled_counts: dict[int, int] = {}
        self.visited: set[tuple[int, str]] = set()
        self.page_counts: dict[int, int] = {}

    async def start(self):
        for request in self.start_requests():
            yield request

    def start_requests(self):
        for source in self.sources.values():
            start_url = normalize_url(source.url)
            self._mark_scheduled(source, start_url)
            yield scrapy.Request(
                start_url,
                callback=self.parse,
                meta={"source_id": source.id, "depth": 0},
                dont_filter=True,
            )

    def parse(self, response):
        source = self.sources[response.meta["source_id"]]
        source_key = (source.id, normalize_url(response.url))
        if source_key in self.visited:
            return
        self.visited.add(source_key)
        self.page_counts[source.id] = self.page_counts.get(source.id, 0) + 1
        if self.page_counts[source.id] > self._max_pages(source):
            return

        content_type = response.headers.get("Content-Type", b"").decode("latin1").lower()
        if content_type and "html" not in content_type:
            return

        final_url = normalize_url(response.url)
        if is_article_url(final_url):
            yield CrawledPageItem(
                source_id=source.id,
                url=normalize_url(response.request.url),
                final_url=final_url,
                html=response.text,
            )

        depth = int(response.meta.get("depth", 0))
        if depth >= self._max_depth(source):
            return

        soup = BeautifulSoup(response.text, "html.parser")
        for anchor in soup.find_all("a", href=True):
            href = anchor["href"].strip()
            if not href:
                continue
            absolute = normalize_url(urljoin(response.url, href))
            if (source.id, absolute) in self.visited:
                continue
            if not self._can_schedule(source, absolute):
                continue
            text = " ".join(anchor.get_text(" ", strip=True).split()).lower()
            if not is_crawlable_url(source, absolute):
                continue
            if not is_article_url(absolute) and not is_listing_url(absolute, text):
                continue
            self._mark_scheduled(source, absolute)
            yield scrapy.Request(
                absolute,
                callback=self.parse,
                meta={"source_id": source.id, "depth": depth + 1},
                dont_filter=True,
            )

    def _max_depth(self, source) -> int:
        return int(getattr(source, "max_depth", None) or getattr(settings, "SCRAPY_MAX_DEPTH", 6))

    def _max_pages(self, source) -> int:
        if self.max_pages_per_source is not None:
            return self.max_pages_per_source
        return int(getattr(source, "max_pages_per_run", None) or getattr(settings, "SCRAPY_MAX_PAGES_PER_SOURCE", 5000))

    def _can_schedule(self, source, url: str) -> bool:
        if (source.id, url) in self.scheduled:
            return False
        return self.scheduled_counts.get(source.id, 0) < self._max_pages(source)

    def _mark_scheduled(self, source, url: str) -> None:
        self.scheduled.add((source.id, url))
        self.scheduled_counts[source.id] = self.scheduled_counts.get(source.id, 0) + 1
