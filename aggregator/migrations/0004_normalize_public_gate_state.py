from datetime import datetime

from django.db import migrations
from django.utils import timezone


SINCE = timezone.make_aware(datetime(2026, 1, 1), timezone.get_current_timezone())


def normalize_public_gate_state(apps, schema_editor):
    ContentItem = apps.get_model("aggregator", "ContentItem")
    ContentItem.objects.filter(source_published_at__lt=SINCE).update(
        is_public=False,
        review_status="out_of_range",
        review_reason="published before 2026-01-01",
    )
    ContentItem.objects.filter(source_published_at__isnull=True).exclude(review_status="blocked").update(
        is_public=False,
        review_status="needs_review",
        review_reason="published date unknown",
    )
    ContentItem.objects.filter(source_published_at__gte=SINCE, review_status="published").update(is_public=True)


class Migration(migrations.Migration):

    dependencies = [
        ("aggregator", "0003_contentitem_date_confidence_and_more"),
    ]

    operations = [
        migrations.RunPython(normalize_public_gate_state, migrations.RunPython.noop),
    ]
