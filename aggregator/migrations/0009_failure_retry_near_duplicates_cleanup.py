import re

from django.db import migrations, models
from django.utils import timezone


_SPACE_RE = re.compile(r"\s+")
_PUNCT_RE = re.compile(r"[\W_]+", re.UNICODE)
_TITLE_SUFFIX_RE = re.compile(r"[-－—]+(?:中北大学|中北大学.*?学院|.*?学院|.*?部|.*?院|.*?网).*$")


def _title_fingerprint(title):
    normalized = _SPACE_RE.sub(" ", title or "").strip()
    normalized = _TITLE_SUFFIX_RE.sub("", normalized)
    return _PUNCT_RE.sub("", normalized.lower())[:160]


def populate_and_cleanup(apps, schema_editor):
    Source = apps.get_model("aggregator", "Source")
    ContentItem = apps.get_model("aggregator", "ContentItem")
    CrawlFailure = apps.get_model("aggregator", "CrawlFailure")
    PeriodicTask = apps.get_model("django_celery_beat", "PeriodicTask")

    for item in ContentItem.objects.filter(title_fingerprint="").only("id", "title", "title_fingerprint"):
        item.title_fingerprint = _title_fingerprint(item.title)
        item.save(update_fields=["title_fingerprint"])

    now = timezone.now()
    for failure in CrawlFailure.objects.filter(resolved_at__isnull=True):
        message = (failure.error_message or "").lower()
        error_type = failure.error_type or ""
        if error_type == "ExtractionError" and ("expired" in message or "不存在" in message or "过期" in message):
            failure.failure_class = "permanent"
            failure.permanent = True
            failure.next_retry_at = None
        elif error_type in {"ConnectError", "ConnectTimeout", "ReadTimeout", "TimeoutException"} or "network is unreachable" in message or "timed out" in message:
            failure.failure_class = "network"
            failure.permanent = False
            failure.next_retry_at = now
        else:
            failure.failure_class = "transient"
            failure.permanent = False
            failure.next_retry_at = now
        failure.save(update_fields=["failure_class", "permanent", "next_retry_at"])

    cleanup_notes = {
        "https://www.nuc.edu.cn/jxjg.htm": "Disabled by migration 0009: directory page, not an article/news source.",
        "http://neuc.nuc.edu.cn/": "Disabled by migration 0009: DNS NXDOMAIN for neuc.nuc.edu.cn.",
    }
    for url, note in cleanup_notes.items():
        try:
            source = Source.objects.get(url=url)
        except Source.DoesNotExist:
            continue
        if source.crawl_enabled:
            source.crawl_enabled = False
        if note not in source.notes:
            source.notes = "\n".join(part for part in [source.notes, note] if part)
        source.last_error_at = now
        source.save(update_fields=["crawl_enabled", "notes", "last_error_at", "updated_at"])

    has_social_sources = Source.objects.filter(enabled=True, crawl_enabled=True, schedule_group="social_daily").exists()
    if not has_social_sources:
        PeriodicTask.objects.filter(name="crawl-social-sources-at-10").update(enabled=False)


class Migration(migrations.Migration):

    dependencies = [
        ("django_celery_beat", "0019_alter_periodictasks_options"),
        ("aggregator", "0008_crawlfailure_resolved_at"),
    ]

    operations = [
        migrations.AddField(
            model_name="contentitem",
            name="title_fingerprint",
            field=models.CharField(blank=True, db_index=True, max_length=160),
        ),
        migrations.AddField(
            model_name="crawlfailure",
            name="failure_class",
            field=models.CharField(
                choices=[("transient", "临时失败"), ("network", "网络失败"), ("permanent", "永久失败")],
                default="transient",
                max_length=30,
            ),
        ),
        migrations.AddField(
            model_name="crawlfailure",
            name="next_retry_at",
            field=models.DateTimeField(blank=True, null=True),
        ),
        migrations.AddField(
            model_name="crawlfailure",
            name="permanent",
            field=models.BooleanField(default=False),
        ),
        migrations.AddField(
            model_name="crawlfailure",
            name="retry_count",
            field=models.PositiveIntegerField(default=0),
        ),
        migrations.AddField(
            model_name="crawljob",
            name="near_duplicate_skip_count",
            field=models.PositiveIntegerField(default=0),
        ),
        migrations.RunPython(populate_and_cleanup, migrations.RunPython.noop),
    ]
