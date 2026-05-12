from django.core.management.base import BaseCommand

from aggregator.models import ContentItem
from aggregator.services.extraction import _parse_published_at
from aggregator.services.importance import score_importance


class Command(BaseCommand):
    help = "Recalculate importance scores for existing content items."

    def handle(self, *args, **options):
        count = 0
        queryset = ContentItem.objects.select_related("source", "category").all()
        for item in queryset.iterator():
            if item.source_published_at is None:
                item.source_published_at = _parse_published_at(item.content_text)
            item.importance_score = score_importance(
                item.source,
                item.title,
                item.content_text,
                item.category.name if item.category else "",
                item.source_published_at,
            )
            item.save(update_fields=["source_published_at", "importance_score", "updated_at"])
            count += 1
        self.stdout.write(self.style.SUCCESS(f"Refreshed importance scores for {count} item(s)."))
