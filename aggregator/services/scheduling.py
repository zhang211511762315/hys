import json

from django.conf import settings
from django_celery_beat.models import CrontabSchedule, PeriodicTask

from aggregator.models import Source


def recommended_crawl_interval_minutes(source_type: str, priority: int | None = None) -> int:
    if source_type == Source.SourceType.SOCIAL_LINK:
        return 1440
    if source_type == Source.SourceType.WECHAT_LINK:
        return 1440
    if source_type == Source.SourceType.MANUAL_URL:
        return 1440
    if source_type == Source.SourceType.OFFICIAL_SITE:
        return 5
    if priority == Source.Priority.HIGH:
        return 10
    if source_type in {Source.SourceType.COLLEGE_SITE, Source.SourceType.DEPARTMENT_SITE}:
        return 30
    return 360


def ensure_fixed_crawl_schedules() -> None:
    web_crontab, _ = CrontabSchedule.objects.get_or_create(
        minute="0",
        hour="10,18",
        day_of_week="*",
        day_of_month="*",
        month_of_year="*",
        timezone=settings.TIME_ZONE,
    )
    social_crontab, _ = CrontabSchedule.objects.get_or_create(
        minute="0",
        hour="10",
        day_of_week="*",
        day_of_month="*",
        month_of_year="*",
        timezone=settings.TIME_ZONE,
    )
    PeriodicTask.objects.update_or_create(
        name="crawl-web-sources-at-10-and-18",
        defaults={
            "task": "aggregator.tasks.enqueue_schedule_group",
            "crontab": web_crontab,
            "args": json.dumps([Source.ScheduleGroup.WEB_TWICE_DAILY]),
            "enabled": True,
        },
    )
    PeriodicTask.objects.update_or_create(
        name="crawl-social-sources-at-10",
        defaults={
            "task": "aggregator.tasks.enqueue_schedule_group",
            "crontab": social_crontab,
            "args": json.dumps([Source.ScheduleGroup.SOCIAL_DAILY]),
            "enabled": True,
        },
    )
