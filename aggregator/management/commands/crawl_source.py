from django.core.management.base import BaseCommand, CommandError

from aggregator.models import Source
from aggregator.tasks import crawl_source


class Command(BaseCommand):
    help = "Crawl one source immediately without Celery."

    def add_arguments(self, parser):
        parser.add_argument("source_id", type=int)

    def handle(self, *args, **options):
        try:
            source = Source.objects.get(id=options["source_id"])
        except Source.DoesNotExist as exc:
            raise CommandError("Source not found") from exc

        item_count = crawl_source(source.id)
        self.stdout.write(self.style.SUCCESS(f"Crawled and published {item_count} item(s)."))
