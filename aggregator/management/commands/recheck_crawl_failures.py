from django.core.management.base import BaseCommand, CommandError
from django.db import transaction
from django.utils import timezone

from aggregator.models import CrawlFailure, CrawlJob
from aggregator.services.pipeline import _mark_crawl_failure_resolved, _record_crawl_failure, ingest_url


class Command(BaseCommand):
    help = "Re-fetch exact unresolved crawl failure URLs. Dry-run by default; IDs are required."

    def add_arguments(self, parser):
        parser.add_argument("failure_ids", nargs="+", type=int)
        parser.add_argument("--apply", action="store_true", help="Fetch URLs and persist results.")

    def handle(self, *args, **options):
        requested_ids = list(dict.fromkeys(options["failure_ids"]))
        failures = list(
            CrawlFailure.objects.filter(id__in=requested_ids, resolved_at__isnull=True)
            .select_related("source")
            .order_by("id")
        )
        found_ids = {failure.id for failure in failures}
        invalid_ids = [failure_id for failure_id in requested_ids if failure_id not in found_ids]
        if invalid_ids:
            raise CommandError(f"unresolved crawl failure IDs not found: {','.join(map(str, invalid_ids))}")

        targets = []
        seen = set()
        for failure in failures:
            key = (failure.source_id, failure.url)
            if key not in seen:
                seen.add(key)
                targets.append(failure)

        if not options["apply"]:
            self.stdout.write(self.style.SUCCESS(f"Would recheck {len(targets)} URL(s)."))
            return

        succeeded = 0
        failed = 0
        for failure in targets:
            now = timezone.now()
            job = CrawlJob.objects.create(
                source=failure.source,
                target_url=failure.url,
                status=CrawlJob.Status.RUNNING,
                started_at=now,
            )
            try:
                with transaction.atomic():
                    ingest_url(failure.source, failure.url, job)
                    _mark_crawl_failure_resolved(failure.source, failure.url)
            except Exception as exc:
                _record_crawl_failure(job, failure.source, failure.url, exc)
                job.status = CrawlJob.Status.FAILED
                job.error_message = str(exc)[:2000]
                failed += 1
            else:
                job.status = CrawlJob.Status.SUCCEEDED
                succeeded += 1
            job.finished_at = timezone.now()
            job.save(update_fields=["status", "error_message", "finished_at", "updated_at"])

        self.stdout.write(
            self.style.SUCCESS(f"Rechecked {len(targets)} URL(s): {succeeded} succeeded, {failed} failed.")
        )
