import os

from celery import Celery

os.environ.setdefault("DJANGO_SETTINGS_MODULE", "zhongbei_info.settings")

app = Celery("zhongbei_info")
app.config_from_object("django.conf:settings", namespace="CELERY")
app.autodiscover_tasks()
