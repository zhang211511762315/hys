from django.conf import settings
from django.core.management.base import BaseCommand, CommandError
from django.utils import timezone

from aggregator.crawlers.runner import run_scrapy_crawl
from aggregator.models import Source


class Command(BaseCommand):
    help = "Run the Scrapy deep crawler for configured sources."

    def add_arguments(self, parser):
        parser.add_argument("--all", action="store_true", help="Crawl all enabled sources.")
        parser.add_argument("--source-id", action="append", type=int, dest="source_ids", help="Crawl a specific source id.")
        parser.add_argument("--source-type", choices=[choice[0] for choice in Source.SourceType.choices])
        parser.add_argument("--mode", choices=["bootstrap", "incremental"], default="incremental")
        parser.add_argument("--since", default=getattr(settings, "CRAWL_SINCE_DATE", "2026-01-01"))
        parser.add_argument("--max-pages-per-source", type=int, default=None)
        parser.add_argument("--dry-run", action="store_true")

    def handle(self, *args, **options):
        if options["since"]:
            settings.CRAWL_SINCE_DATE = options["since"]

        queryset = Source.objects.filter(enabled=True, crawl_enabled=True)
        if options["source_ids"]:
            queryset = queryset.filter(id__in=options["source_ids"])
        elif options["source_type"]:
            queryset = queryset.filter(source_type=options["source_type"])
        elif not options["all"]:
            queryset = queryset.exclude(source_type=Source.SourceType.MANUAL_URL)

        source_ids = list(queryset.values_list("id", flat=True))
        if options["dry_run"]:
            self.stdout.write(f"Dry run: {len(source_ids)} source(s) would be crawled.")
            for source in queryset.order_by("priority", "name"):
                self.stdout.write(f"- {source.id}: {source.name} <{source.url}>")
            return
        if not source_ids:
            raise CommandError("No enabled sources matched the crawl options.")

        run_scrapy_crawl(source_ids, options["mode"], options["since"], options["max_pages_per_source"])
        now = timezone.now()
        update_fields = {"last_success_at": now, "last_crawled_at": now}
        if options["mode"] == "bootstrap":
            update_fields["bootstrap_completed_at"] = now
        Source.objects.filter(id__in=source_ids).update(**update_fields)
        self.stdout.write(self.style.SUCCESS(f"Scrapy crawl finished for {len(source_ids)} source(s)."))
