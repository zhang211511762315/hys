import scrapy


class CrawledPageItem(scrapy.Item):
    source_id = scrapy.Field()
    url = scrapy.Field()
    final_url = scrapy.Field()
    html = scrapy.Field()
