from django.core.management.base import BaseCommand
from django.db.models import Count
from django.utils import timezone

from aggregator.models import CrawlFailure


class Command(BaseCommand):
    help = "Resolve duplicate open crawl failures while keeping the latest record for each source and URL."

    def add_arguments(self, parser):
        parser.add_argument("--apply", action="store_true", help="Apply cleanup. Default is dry-run.")

    def handle(self, *args, **options):
        apply = options["apply"]
        duplicate_groups = (
            CrawlFailure.objects.filter(resolved_at__isnull=True)
            .values("source_id", "url")
            .annotate(n=Count("id"))
            .filter(n__gt=1)
        )
        resolved = 0
        groups = 0
        for group in duplicate_groups.iterator():
            failures = CrawlFailure.objects.filter(
                source_id=group["source_id"],
                url=group["url"],
                resolved_at__isnull=True,
            ).order_by("-updated_at", "-created_at", "-id")
            latest = failures.first()
            older = failures.exclude(id=latest.id)
            count = older.count()
            if not count:
                continue
            groups += 1
            resolved += count
            self.stdout.write(
                f"{'[apply]' if apply else '[dry-run]'} source=#{group['source_id']} "
                f"keep=#{latest.id} resolve={count} {group['url']}"
            )
            if apply:
                older.update(resolved_at=timezone.now())
        action = "Resolved" if apply else "Would resolve"
        self.stdout.write(self.style.SUCCESS(f"{action} {resolved} duplicate failure(s) across {groups} URL(s)."))
