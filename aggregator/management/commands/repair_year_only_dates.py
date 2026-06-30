from django.core.management.base import BaseCommand

from aggregator.models import ContentItem
from aggregator.services.extraction import ExtractedDocument, ExtractionError, _parse_published_at_with_confidence, extract_document_from_html
from aggregator.services.gate import evaluate_candidate
from aggregator.services.search import sync_item_to_search


class Command(BaseCommand):
    help = "Recalculate uncertain item dates from stored raw HTML/text and optionally apply exact fixes."

    def add_arguments(self, parser):
        parser.add_argument("--apply", action="store_true", help="Apply exact-date repairs. Default is dry-run.")
        parser.add_argument("--include-unknown", action="store_true", help="Also repair items blocked because the date is unknown.")
        parser.add_argument("--limit", type=int, default=500)

    def handle(self, *args, **options):
        apply = options["apply"]
        include_unknown = options["include_unknown"]
        checked = 0
        repaired = 0
        qs = ContentItem.objects.filter(date_confidence=ContentItem.DateConfidence.YEAR_ONLY)
        if include_unknown:
            qs = ContentItem.objects.filter(
                date_confidence__in=[ContentItem.DateConfidence.YEAR_ONLY, ContentItem.DateConfidence.UNKNOWN],
            ) | ContentItem.objects.filter(review_reason="published date unknown")
        qs = qs.select_related("raw_document", "source").order_by("-created_at")[: options["limit"]]
        for item in qs:
            checked += 1
            parsed_at, confidence, document = _repair_candidate(item)
            if confidence != ContentItem.DateConfidence.EXACT or not parsed_at:
                continue
            repaired += 1
            self.stdout.write(f"{'[apply]' if apply else '[dry-run]'} #{item.id} {item.source_published_at} -> {parsed_at} {item.title[:80]}")
            if apply:
                update_fields = ["source_published_at", "date_confidence", "updated_at"]
                item.source_published_at = parsed_at
                item.date_confidence = confidence
                if document is not None:
                    decision = evaluate_candidate(item.source, document)
                    item.review_status = decision.review_status
                    item.is_public = decision.is_public
                    item.extraction_quality_score = decision.extraction_quality_score
                    item.review_reason = decision.review_reason
                    item.status = ContentItem.Status.PUBLISHED if decision.is_public else ContentItem.Status.CLEANED
                    update_fields.extend(
                        ["review_status", "is_public", "extraction_quality_score", "review_reason", "status"]
                    )
                item.save(update_fields=update_fields)
                if item.is_public:
                    sync_item_to_search(item)
        self.stdout.write(f"Checked {checked} item(s), {'repaired' if apply else 'would repair'} {repaired}.")


def _repair_candidate(item: ContentItem):
    raw = item.raw_document
    html = raw.html if raw else ""
    url = (raw.final_url or raw.url) if raw else item.canonical_url
    if html:
        try:
            document = extract_document_from_html(url, url, html)
        except ExtractionError:
            document = None
        else:
            if document.published_at:
                return document.published_at, document.date_confidence, document
    text_parts = []
    if raw:
        text_parts.extend([raw.title, raw.extracted_text, raw.html])
    text_parts.extend([item.title, item.content_text])
    parsed_at, confidence = _parse_published_at_with_confidence(" ".join(part or "" for part in text_parts))
    if not parsed_at:
        return None, ContentItem.DateConfidence.UNKNOWN, None
    document = ExtractedDocument(
        url=item.canonical_url,
        final_url=item.canonical_url,
        title=item.title,
        html=html,
        text=item.content_text,
        image_urls=[],
        published_at=parsed_at,
        date_confidence=confidence,
    )
    return parsed_at, confidence, document
