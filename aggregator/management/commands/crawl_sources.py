from datetime import timedelta

from django.core.management.base import BaseCommand
from django.db.models import QuerySet
from django.utils import timezone

from aggregator.models import Source
from aggregator.services.pipeline import ingest_source


class Command(BaseCommand):
    help = "Crawl multiple sources synchronously for local bootstrap or maintenance."

    def add_arguments(self, parser):
        parser.add_argument("--all", action="store_true", help="Crawl all enabled sources instead of only due sources.")
        parser.add_argument("--limit", type=int, default=5, help="Maximum number of sources to crawl.")
        parser.add_argument("--source-type", choices=[choice[0] for choice in Source.SourceType.choices])
        parser.add_argument("--ids", help="Comma-separated source ids to crawl.")
        parser.add_argument("--max-articles", type=int, help="Temporarily override max articles per selected source.")

    def handle(self, *args, **options):
        sources = self._select_sources(options)
        total_items = 0
        for source in sources:
            original_max = source.max_articles_per_run
            if options["max_articles"]:
                source.max_articles_per_run = options["max_articles"]
            self.stdout.write(f"Crawling #{source.id} {source.name} ...")
            count = ingest_source(source)
            total_items += count
            source.last_crawled_at = timezone.now()
            source.next_crawl_at = source.last_crawled_at + timedelta(minutes=source.crawl_interval_minutes)
            source.max_articles_per_run = original_max
            source.failure_count = 0
            source.save(update_fields=["last_crawled_at", "next_crawl_at", "failure_count", "updated_at"])
            self.stdout.write(self.style.SUCCESS(f"  published/updated {count} item(s)"))
        self.stdout.write(self.style.SUCCESS(f"Crawled {len(sources)} source(s), published/updated {total_items} item(s)."))

    def _select_sources(self, options) -> list[Source]:
        queryset: QuerySet[Source] = Source.objects.filter(enabled=True).order_by("priority", "id")
        if options["ids"]:
            ids = [int(part.strip()) for part in options["ids"].split(",") if part.strip()]
            queryset = queryset.filter(id__in=ids).order_by("priority", "id")
        elif not options["all"]:
            queryset = queryset.filter(next_crawl_at__lte=timezone.now())
        if options["source_type"]:
            queryset = queryset.filter(source_type=options["source_type"])
        return list(queryset[: options["limit"]])
