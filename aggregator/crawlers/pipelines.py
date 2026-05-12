from asgiref.sync import sync_to_async

from aggregator.models import Source
from aggregator.services.extraction import extract_document_from_html
from aggregator.services.pipeline import ingest_extracted_document


class DjangoIngestPipeline:
    async def process_item(self, item, spider):
        try:
            await sync_to_async(self._process_item, thread_sensitive=True)(item)
        except Exception as exc:
            spider.crawler.stats.inc_value("ingest/failed")
            spider.logger.warning("Failed to ingest %s: %s", item.get("final_url") or item.get("url"), exc)
        return item

    def _process_item(self, item):
        source = Source.objects.get(id=item["source_id"])
        document = extract_document_from_html(item["url"], item["final_url"], item["html"])
        ingest_extracted_document(source, document)
