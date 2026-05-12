from django.core.management.base import BaseCommand

from aggregator.services.scheduling import ensure_fixed_crawl_schedules


class Command(BaseCommand):
    help = "Create or update fixed Celery Beat crawl schedules."

    def handle(self, *args, **options):
        ensure_fixed_crawl_schedules()
        self.stdout.write(self.style.SUCCESS("Ensured fixed crawl schedules."))
