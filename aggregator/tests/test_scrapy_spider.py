from aggregator.crawlers.spiders.source_spider import SourceSpider


def test_source_spider_request_cap_is_enforced_before_scheduling():
    spider = SourceSpider(
        source_records=[
            {
                "id": 1,
                "name": "NUC",
                "url": "https://www.nuc.edu.cn/",
                "allowed_domains": ["www.nuc.edu.cn"],
                "allowed_path_prefixes": [],
                "denied_path_patterns": [],
                "max_depth": 6,
                "max_pages_per_run": 5000,
            }
        ],
        max_pages_per_source=1,
    )
    source = spider.sources[1]

    list(spider.start_requests())

    assert spider._can_schedule(source, "https://www.nuc.edu.cn/info/1.htm") is False
