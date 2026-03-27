from __future__ import annotations

from django.conf import settings
from django.utils import timezone
from celery import shared_task

from .models import DailyWeather, FishBatch
from .notifications import send_email_notification, send_sms_notification
from .services import smart_feed_kg_for_batch


@shared_task
def send_daily_feed_alert():
    """
    Build a daily feed summary and send it via email.
    You can later extend this task to also push SMS / mobile notifications.
    """
    today = timezone.now().date()
    daily_weather = DailyWeather.objects.filter(date=today).first()

    lines: list[str] = []
    lines.append("📢 Fish Farm Alert")
    lines.append("")
    lines.append(f"Date: {today}")
    if daily_weather:
        lines.append(f"Temperature: {daily_weather.temperature_c}°C")
    lines.append("")
    lines.append("Pond Feed:")

    for batch in FishBatch.objects.select_related("pond"):
        suggested = smart_feed_kg_for_batch(batch)
        if suggested is None:
            continue
        lines.append(f"{batch.pond.name} {batch.get_species_display()} → {suggested:.2f}kg")

    lines.append("")
    lines.append("🐟 Feeding schedule")
    lines.append("💧 Water quality test")
    lines.append("📈 Growth monitoring")
    lines.append("")
    lines.append("Remember to test water pH today.")

    body = "\n".join(lines)
    send_email_notification("Fish Farm Daily Feed Alert", body)
    send_sms_notification(body)

