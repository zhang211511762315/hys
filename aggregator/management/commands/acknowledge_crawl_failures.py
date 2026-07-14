from django.core.management.base import BaseCommand, CommandError

from aggregator.services.failures import CrawlFailureAcknowledgementError, acknowledge_crawl_failures


class Command(BaseCommand):
    help = "Acknowledge explicitly confirmed permanent HTTP 404/410 crawl failures. Defaults to dry-run."

    def add_arguments(self, parser):
        parser.add_argument("--failure-id", action="append", type=int, required=True)
        parser.add_argument("--note", required=True)
        parser.add_argument("--confirmed-status", type=int, choices=[404, 410], required=True)
        parser.add_argument("--apply", action="store_true", help="Persist acknowledgement audit metadata.")

    def handle(self, *args, **options):
        try:
            failure_ids = acknowledge_crawl_failures(
                options["failure_id"],
                note=options["note"],
                confirmed_status=options["confirmed_status"],
                apply=options["apply"],
            )
        except CrawlFailureAcknowledgementError as exc:
            raise CommandError(str(exc)) from exc
        mode = "apply" if options["apply"] else "dry-run"
        self.stdout.write(
            f"{mode}: acknowledged permanent HTTP {options['confirmed_status']} failure IDs: "
            + ", ".join(str(failure_id) for failure_id in failure_ids)
        )
