from scrapy.crawler import CrawlerProcess
from scrapy.settings import Settings

from aggregator.crawlers import settings as crawler_settings
from aggregator.crawlers.spiders.source_spider import SourceSpider
from aggregator.models import Source


def run_scrapy_crawl(
    source_ids: list[int],
    mode: str,
    since: str | None = None,
    max_pages_per_source: int | None = None,
) -> None:
    source_records = list(
        Source.objects.filter(id__in=source_ids, enabled=True, crawl_enabled=True).values(
            "id",
            "name",
            "url",
            "allowed_domains",
            "allowed_path_prefixes",
            "denied_path_patterns",
            "max_depth",
            "max_pages_per_run",
        )
    )
    scrapy_settings = Settings()
    scrapy_settings.setmodule(crawler_settings, priority="project")
    process = CrawlerProcess(scrapy_settings)
    crawler = process.create_crawler(SourceSpider)
    failures = []
    deferred = process.crawl(
        crawler,
        source_records=source_records,
        mode=mode,
        since=since,
        max_pages_per_source=max_pages_per_source,
    )
    deferred.addErrback(failures.append)
    process.start()
    if failures:
        failure = failures[0]
        traceback = failure.getTraceback() if hasattr(failure, "getTraceback") else str(failure)
        raise RuntimeError(traceback)
    error_count = crawler.stats.get_value("log_count/ERROR", 0) or 0
    request_count = crawler.stats.get_value("downloader/request_count", 0) or 0
    if error_count and request_count == 0:
        raise RuntimeError(f"Scrapy crawl failed before issuing requests; {error_count} error log(s).")
