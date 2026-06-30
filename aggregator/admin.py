from django.contrib import admin
from django.utils import timezone
from django.utils.text import slugify

from .models import (
    AIJob,
    AIUsageDaily,
    Attachment,
    Category,
    ContentItem,
    ContentSource,
    CrawlFailure,
    CrawlJob,
    CrawlNetworkEvent,
    DuplicateGroup,
    RawDocument,
    Source,
    Tag,
)
from .services.ai import get_ai_provider
from .services.dedupe import content_fingerprint
from .services.extraction import _extract_text, _parse_published_at_with_confidence
from .tasks import crawl_source


@admin.action(description="立即抓取所选信息源")
def run_crawl_now(modeladmin, request, queryset):
    for source in queryset:
        crawl_source.delay(source.id)


@admin.register(Source)
class SourceAdmin(admin.ModelAdmin):
    list_display = (
        "name",
        "source_type",
        "priority",
        "enabled",
        "crawl_enabled",
        "crawl_interval_minutes",
        "crawl_depth",
        "max_articles_per_run",
        "next_crawl_at",
        "last_success_at",
        "last_error_at",
        "failure_count",
    )
    list_filter = ("source_type", "priority", "enabled", "crawl_enabled")
    search_fields = ("name", "url", "notes")
    actions = [run_crawl_now]


@admin.register(ContentItem)
class ContentItemAdmin(admin.ModelAdmin):
    list_display = (
        "title",
        "source",
        "category",
        "importance_score",
        "status",
        "review_status",
        "is_public",
        "date_confidence",
        "review_reason_short",
        "published_at",
    )
    list_filter = ("status", "review_status", "is_public", "date_confidence", "category", "source__source_type")
    search_fields = ("title", "summary", "content_text", "canonical_url")
    autocomplete_fields = ("source", "category", "tags")
    readonly_fields = ("created_at", "updated_at")
    actions = ["publish_items", "block_items", "reextract_items", "reclassify_items", "merge_duplicate_items"]

    @admin.display(description="待审原因")
    def review_reason_short(self, obj):
        return (obj.review_reason[:80] + "...") if len(obj.review_reason) > 80 else obj.review_reason

    @admin.action(description="发布所选内容")
    def publish_items(self, request, queryset):
        queryset.update(
            status=ContentItem.Status.PUBLISHED,
            review_status=ContentItem.ReviewStatus.PUBLISHED,
            is_public=True,
            review_reason="",
            published_at=timezone.now(),
        )

    @admin.action(description="屏蔽所选内容")
    def block_items(self, request, queryset):
        queryset.update(
            status=ContentItem.Status.BLOCKED,
            review_status=ContentItem.ReviewStatus.BLOCKED,
            is_public=False,
            review_reason="blocked by admin",
        )

    @admin.action(description="重新抽取所选内容")
    def reextract_items(self, request, queryset):
        for item in queryset.select_related("raw_document"):
            if not item.raw_document or not item.raw_document.html:
                continue
            item.content_text = _extract_text(item.raw_document.html)
            item.source_published_at, item.date_confidence = _parse_published_at_with_confidence(item.content_text)
            item.extraction_quality_score = 0
            item.review_status = ContentItem.ReviewStatus.NEEDS_REVIEW
            item.is_public = False
            item.review_reason = "re-extracted by admin"
            item.save(
                update_fields=[
                    "content_text",
                    "source_published_at",
                    "date_confidence",
                    "extraction_quality_score",
                    "review_status",
                    "is_public",
                    "review_reason",
                    "updated_at",
                ]
            )

    @admin.action(description="重新分类所选内容")
    def reclassify_items(self, request, queryset):
        provider = get_ai_provider()
        categories = list(Category.objects.values_list("name", flat=True))
        for item in queryset:
            analysis = provider.analyze(item.content_text, categories)
            category, _ = Category.objects.get_or_create(
                name=analysis.category,
                defaults={"slug": slugify(analysis.category) or f"category-{Category.objects.count() + 1}"},
            )
            item.category = category
            item.summary = analysis.summary
            item.ai_provider = analysis.provider
            item.save(update_fields=["category", "summary", "ai_provider", "updated_at"])
            item.tags.clear()
            for tag_name in analysis.tags:
                tag, _ = Tag.objects.get_or_create(
                    name=tag_name,
                    defaults={"slug": slugify(tag_name) or f"tag-{Tag.objects.count() + 1}"},
                )
                item.tags.add(tag)

    @admin.action(description="合并重复内容")
    def merge_duplicate_items(self, request, queryset):
        items = list(queryset.order_by("id"))
        if len(items) < 2:
            return
        fingerprint = content_fingerprint("\n".join(item.content_text for item in items))
        group, _ = DuplicateGroup.objects.get_or_create(fingerprint=fingerprint, defaults={"canonical_item": items[0]})
        ContentItem.objects.filter(id__in=[item.id for item in items]).update(duplicate_group=group)


@admin.register(Category)
class CategoryAdmin(admin.ModelAdmin):
    prepopulated_fields = {"slug": ("name",)}
    search_fields = ("name",)


@admin.register(Tag)
class TagAdmin(admin.ModelAdmin):
    prepopulated_fields = {"slug": ("name",)}
    search_fields = ("name",)


@admin.register(CrawlJob)
class CrawlJobAdmin(admin.ModelAdmin):
    list_display = (
        "source",
        "target_url",
        "status",
        "started_at",
        "finished_at",
        "discovered_count",
        "success_count",
        "new_count",
        "updated_count",
        "duplicate_skip_count",
        "near_duplicate_skip_count",
        "failed_url_count",
        "direct_fetch_count",
        "relay_fetch_count",
        "ai_call_count",
        "ai_skip_count",
        "ai_fallback_count",
    )
    list_filter = ("status",)
    search_fields = ("target_url", "error_message", "warning_message")
    readonly_fields = ("created_at", "updated_at")


admin.site.register(RawDocument)
admin.site.register(CrawlFailure)
admin.site.register(CrawlNetworkEvent)
admin.site.register(DuplicateGroup)
admin.site.register(ContentSource)
admin.site.register(Attachment)
admin.site.register(AIJob)
admin.site.register(AIUsageDaily)
