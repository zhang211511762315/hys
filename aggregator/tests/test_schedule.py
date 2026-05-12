from django_celery_beat.models import CrontabSchedule, PeriodicTask

from aggregator.services.scheduling import ensure_fixed_crawl_schedules


def test_fixed_crawl_schedules_use_10_and_18_for_web_and_10_for_social(db):
    ensure_fixed_crawl_schedules()

    web_task = PeriodicTask.objects.get(name="crawl-web-sources-at-10-and-18")
    social_task = PeriodicTask.objects.get(name="crawl-social-sources-at-10")

    assert isinstance(web_task.crontab, CrontabSchedule)
    assert web_task.crontab.hour == "10,18"
    assert web_task.crontab.minute == "0"
    assert social_task.crontab.hour == "10"
    assert social_task.crontab.minute == "0"
