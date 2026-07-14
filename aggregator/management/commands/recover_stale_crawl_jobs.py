from datetime import timedelta

from django.core.management.base import BaseCommand, CommandError
from django.db import transaction
from django.db.models import Q
from django.utils import timezone

from aggregator.models import CrawlJob


class Command(BaseCommand):
    help = "Fail queued or running crawl jobs that exceeded an operator-selected age. Dry-run by default."

    def add_arguments(self, parser):
        parser.add_argument("--older-than-minutes", type=int, default=60)
        parser.add_argument("--apply", action="store_true", help="Persist recovery. Default is dry-run.")

    def handle(self, *args, **options):
        minutes = options["older_than_minutes"]
        if minutes <= 0:
            raise CommandError("--older-than-minutes must be positive")

        cutoff = timezone.now() - timedelta(minutes=minutes)
        stale_condition = (
            Q(status=CrawlJob.Status.QUEUED, created_at__lt=cutoff)
            | Q(status=CrawlJob.Status.RUNNING, started_at__lt=cutoff)
            | Q(
                status=CrawlJob.Status.RUNNING,
                started_at__isnull=True,
                created_at__lt=cutoff,
            )
        )

        with transaction.atomic():
            jobs = list(
                CrawlJob.objects.select_for_update()
                .filter(stale_condition)
                .order_by("id")
            )
            if options["apply"] and jobs:
                now = timezone.now()
                message = f"Recovered stale crawl job after exceeding {minutes} minute(s)."
                CrawlJob.objects.filter(id__in=[job.id for job in jobs]).update(
                    status=CrawlJob.Status.FAILED,
                    error_message=message,
                    finished_at=now,
                    updated_at=now,
                )

        action = "Recovered" if options["apply"] else "Would recover"
        ids = ",".join(str(job.id) for job in jobs) or "none"
        self.stdout.write(self.style.SUCCESS(f"{action} {len(jobs)} stale crawl job(s); IDs: {ids}."))
