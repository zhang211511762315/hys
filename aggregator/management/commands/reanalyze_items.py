from django.core.management.base import BaseCommand
from django.utils.text import slugify

from aggregator.models import Category, ContentItem, Tag
from aggregator.services.ai import get_ai_provider


class Command(BaseCommand):
    help = "Explicitly rerun AI analysis for selected content items."

    def add_arguments(self, parser):
        parser.add_argument("--ids", help="Comma-separated content item ids.")
        parser.add_argument("--limit", type=int, default=50)
        parser.add_argument("--missing-only", action="store_true", help="Only analyze items missing summary/category/provider.")

    def handle(self, *args, **options):
        queryset = ContentItem.objects.order_by("-created_at")
        if options["ids"]:
            ids = [int(part.strip()) for part in options["ids"].split(",") if part.strip()]
            queryset = queryset.filter(id__in=ids)
        if options["missing_only"]:
            queryset = queryset.filter(summary="")
        items = list(queryset[: options["limit"]])
        provider = get_ai_provider()
        categories = list(Category.objects.values_list("name", flat=True))
        updated = 0
        for item in items:
            analysis = provider.analyze(item.content_text, categories)
            category, _ = Category.objects.get_or_create(
                name=analysis.category,
                defaults={"slug": slugify(analysis.category) or f"category-{Category.objects.count() + 1}"},
            )
            item.summary = analysis.summary
            item.category = category
            item.ai_provider = analysis.provider
            item.save(update_fields=["summary", "category", "ai_provider", "updated_at"])
            item.tags.clear()
            for tag_name in analysis.tags:
                tag, _ = Tag.objects.get_or_create(
                    name=tag_name,
                    defaults={"slug": slugify(tag_name) or f"tag-{Tag.objects.count() + 1}"},
                )
                item.tags.add(tag)
            updated += 1
        self.stdout.write(self.style.SUCCESS(f"Reanalyzed {updated} item(s)."))
