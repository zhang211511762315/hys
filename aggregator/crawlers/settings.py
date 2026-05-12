BOT_NAME = "zhongbei_info"

SPIDER_MODULES = ["aggregator.crawlers.spiders"]
NEWSPIDER_MODULE = "aggregator.crawlers.spiders"

ROBOTSTXT_OBEY = False
COOKIES_ENABLED = False
DOWNLOAD_TIMEOUT = 20
CONCURRENT_REQUESTS = 8
CONCURRENT_REQUESTS_PER_DOMAIN = 2
LOG_LEVEL = "INFO"
USER_AGENT = "ZhongbeiInfoBot/0.1 (+https://example.local)"

ITEM_PIPELINES = {
    "aggregator.crawlers.pipelines.DjangoIngestPipeline": 300,
}
