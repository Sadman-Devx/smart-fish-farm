from __future__ import annotations

import os

from celery import Celery
from celery.schedules import crontab

os.environ.setdefault("DJANGO_SETTINGS_MODULE", "smart_fish_farm.settings")

app = Celery("smart_fish_farm")
app.config_from_object("django.conf:settings", namespace="CELERY")
app.autodiscover_tasks()

# Example periodic schedule: send feed alert every day at 06:00 server time
app.conf.beat_schedule = {
    "send-daily-feed-alert": {
        "task": "farm.tasks.send_daily_feed_alert",
        "schedule": crontab(hour=6, minute=0),
    },
}

