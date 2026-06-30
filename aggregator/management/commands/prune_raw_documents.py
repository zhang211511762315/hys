from datetime import timedelta

from django.core.management.base import BaseCommand
from django.db.models import Q
from django.utils import timezone

from aggregator.models import ContentItem, RawDocument


class Command(BaseCommand):
    help = "Clear large stored raw HTML/text fields for old documents. Defaults to dry-run."

    def add_arguments(self, parser):
        parser.add_argument("--apply", action="store_true", help="Apply pruning. Default is dry-run.")
        parser.add_argument("--days", type=int, default=30, help="Only prune documents fetched before this many days ago.")
        parser.add_argument("--limit", type=int, default=500, help="Maximum documents to prune in one run.")
        parser.add_argument(
            "--include-uncertain-dates",
            action="store_true",
            help="Also prune raw documents linked to items with uncertain dates.",
        )

    def handle(self, *args, **options):
        cutoff = timezone.now() - timedelta(days=options["days"])
        qs = RawDocument.objects.filter(fetched_at__lt=cutoff).filter(Q(html__gt="") | Q(extracted_text__gt=""))
        if not options["include_uncertain_dates"]:
            uncertain_raw_ids = ContentItem.objects.filter(
                raw_document_id__isnull=False,
                date_confidence__in=[ContentItem.DateConfidence.YEAR_ONLY, ContentItem.DateConfidence.UNKNOWN],
            ).values("raw_document_id")
            qs = qs.exclude(id__in=uncertain_raw_ids)

        ids = list(qs.order_by("fetched_at").values_list("id", flat=True)[: options["limit"]])
        action = "Pruning" if options["apply"] else "Would prune"
        self.stdout.write(f"{action} {len(ids)} raw document(s) fetched before {cutoff.date().isoformat()}.")

        if options["apply"] and ids:
            updated = RawDocument.objects.filter(id__in=ids).update(html="", extracted_text="")
            self.stdout.write(f"Pruned {updated} raw document(s).")
