from datetime import timedelta

from django.db import migrations, models
from django.utils import timezone


def cleanup_current_operational_state(apps, schema_editor):
    Source = apps.get_model("aggregator", "Source")
    ContentItem = apps.get_model("aggregator", "ContentItem")

    Source.objects.filter(
        last_crawled_at__isnull=False,
        failure_count=0,
        last_success_at__isnull=True,
    ).update(last_success_at=models.F("last_crawled_at"), last_error_at=None)

    dead_sources = Source.objects.filter(url__in=["http://neuc.nuc.edu.cn/", "https://neuc.nuc.edu.cn/"])
    for source in dead_sources:
        note = "Auto-disabled: neuc.nuc.edu.cn returned NXDOMAIN during crawl health check."
        if note not in (source.notes or ""):
            source.notes = "\n".join(part for part in [source.notes, note] if part)
        source.crawl_enabled = False
        source.next_crawl_at = timezone.now() + timedelta(days=365)
        source.save(update_fields=["crawl_enabled", "notes", "next_crawl_at", "updated_at"])

    ContentItem.objects.filter(
        is_public=True,
        source_published_at__gt=timezone.now(),
    ).update(
        status="cleaned",
        review_status="needs_review",
        is_public=False,
        review_reason="published date is in the future",
    )


class Migration(migrations.Migration):

    dependencies = [
        ("aggregator", "0005_aiusagedaily"),
    ]

    operations = [
        migrations.AddField(
            model_name="crawljob",
            name="ai_call_count",
            field=models.PositiveIntegerField(default=0),
        ),
        migrations.AddField(
            model_name="crawljob",
            name="ai_fallback_count",
            field=models.PositiveIntegerField(default=0),
        ),
        migrations.AddField(
            model_name="crawljob",
            name="ai_skip_count",
            field=models.PositiveIntegerField(default=0),
        ),
        migrations.AddField(
            model_name="crawljob",
            name="discovered_count",
            field=models.PositiveIntegerField(default=0),
        ),
        migrations.AddField(
            model_name="crawljob",
            name="duplicate_skip_count",
            field=models.PositiveIntegerField(default=0),
        ),
        migrations.AddField(
            model_name="crawljob",
            name="failed_url_count",
            field=models.PositiveIntegerField(default=0),
        ),
        migrations.AddField(
            model_name="crawljob",
            name="listing_pages_count",
            field=models.PositiveIntegerField(default=0),
        ),
        migrations.AddField(
            model_name="crawljob",
            name="new_count",
            field=models.PositiveIntegerField(default=0),
        ),
        migrations.AddField(
            model_name="crawljob",
            name="success_count",
            field=models.PositiveIntegerField(default=0),
        ),
        migrations.AddField(
            model_name="crawljob",
            name="updated_count",
            field=models.PositiveIntegerField(default=0),
        ),
        migrations.AddField(
            model_name="crawljob",
            name="warning_message",
            field=models.TextField(blank=True),
        ),
        migrations.CreateModel(
            name="CrawlFailure",
            fields=[
                ("id", models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID")),
                ("created_at", models.DateTimeField(auto_now_add=True)),
                ("updated_at", models.DateTimeField(auto_now=True)),
                ("url", models.URLField(max_length=500)),
                ("error_type", models.CharField(blank=True, max_length=120)),
                ("error_message", models.TextField(blank=True)),
                (
                    "crawl_job",
                    models.ForeignKey(on_delete=models.deletion.CASCADE, related_name="failures", to="aggregator.crawljob"),
                ),
                (
                    "source",
                    models.ForeignKey(on_delete=models.deletion.CASCADE, related_name="crawl_failures", to="aggregator.source"),
                ),
            ],
            options={
                "verbose_name": "抓取失败URL",
                "verbose_name_plural": "抓取失败URL",
                "ordering": ["-created_at"],
            },
        ),
        migrations.RunPython(cleanup_current_operational_state, migrations.RunPython.noop),
    ]
