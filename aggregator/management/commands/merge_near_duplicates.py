from django.core.management.base import BaseCommand
from django.db import transaction

from aggregator.models import ContentItem, ContentSource, DuplicateGroup
from aggregator.services.dedupe import is_near_duplicate, title_fingerprint


class Command(BaseCommand):
    help = "Find and optionally merge already-published near-duplicate content items."

    def add_arguments(self, parser):
        parser.add_argument("--apply", action="store_true", help="Apply merges. Default is dry-run.")
        parser.add_argument("--threshold", type=float, default=0.88)

    def handle(self, *args, **options):
        apply = options["apply"]
        threshold = options["threshold"]
        merged = 0
        seen_pairs = set()
        for fingerprint in _candidate_fingerprints():
            items = list(ContentItem.objects.filter(title_fingerprint=fingerprint).order_by("id"))
            if len(items) < 2:
                continue
            canonical = items[0]
            for item in items[1:]:
                pair = (canonical.id, item.id)
                if pair in seen_pairs:
                    continue
                if not is_near_duplicate(canonical.content_text, item.content_text, threshold=threshold):
                    continue
                seen_pairs.add(pair)
                merged += 1
                self.stdout.write(f"{'[apply]' if apply else '[dry-run]'} #{item.id} -> #{canonical.id} {item.title[:80]}")
                if apply:
                    _merge_item(canonical, item)
        self.stdout.write(f"{'Merged' if apply else 'Would merge'} {merged} item(s).")


def _candidate_fingerprints():
    fingerprints = (
        ContentItem.objects.exclude(title_fingerprint="")
        .values_list("title_fingerprint", flat=True)
        .distinct()
    )
    return fingerprints


@transaction.atomic
def _merge_item(canonical: ContentItem, duplicate: ContentItem) -> None:
    group, _ = DuplicateGroup.objects.get_or_create(
        fingerprint=f"title:{canonical.title_fingerprint or title_fingerprint(canonical.title)}",
        defaults={"canonical_item": canonical},
    )
    canonical.duplicate_group = group
    canonical.save(update_fields=["duplicate_group", "updated_at"])
    duplicate.duplicate_group = group
    duplicate.is_public = False
    duplicate.status = ContentItem.Status.BLOCKED
    duplicate.review_status = ContentItem.ReviewStatus.BLOCKED
    duplicate.review_reason = "merged as near duplicate"
    duplicate.save(update_fields=["duplicate_group", "is_public", "status", "review_status", "review_reason", "updated_at"])
    ContentSource.objects.update_or_create(
        content_item=canonical,
        source=duplicate.source,
        url=duplicate.canonical_url,
        defaults={
            "raw_document": duplicate.raw_document,
            "source_title": duplicate.title,
            "source_published_at": duplicate.source_published_at,
        },
    )
