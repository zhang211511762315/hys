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


def test_fixed_crawl_schedules_register_daily_memory_cleanup_idempotently(db, settings):
    ensure_fixed_crawl_schedules()
    ensure_fixed_crawl_schedules()

    cleanup_task = PeriodicTask.objects.get(name="cleanup-expired-agent-memory-daily")

    assert cleanup_task.task == "agent_runtime.tasks.cleanup_expired_memory_task"
    assert cleanup_task.args == "[]"
    assert cleanup_task.crontab.hour == "3"
    assert cleanup_task.crontab.minute == "0"
    assert str(cleanup_task.crontab.timezone) == settings.TIME_ZONE
    assert PeriodicTask.objects.filter(name="cleanup-expired-agent-memory-daily").count() == 1
