from __future__ import annotations

from django.conf import settings
from django.utils import timezone
from celery import shared_task

from .models import DailyWeather, FishBatch
from .notifications import send_email_notification, send_sms_notification
from .services import smart_feed_kg_for_batch
from .services.weather_ingest import get_feeding_suggestion


@shared_task
def send_daily_feed_alert():
    """
    Enhanced daily feed summary with morning/evening split
    and weather-based feeding recommendation.
    """
    today        = timezone.now().date()
    daily_weather = DailyWeather.objects.filter(date=today).first()

    # Weather based suggestion
    suggestion = None
    if daily_weather:
        suggestion = get_feeding_suggestion(
            temp_c   = float(daily_weather.temperature_c),
            humidity = 70,   # fallback if not available
            rain_mm  = 0,
        )

    lines: list[str] = []
    lines.append("📢 AquaSmart — Daily Feed Alert")
    lines.append("")
    lines.append(f"Date: {today}")

    if daily_weather:
        lines.append(f"🌡️ Temperature: {daily_weather.temperature_c}°C")
        lines.append(f"☁️ Condition: {daily_weather.condition}")

    if suggestion:
        lines.append(f"\n{suggestion['icon']} {suggestion['title']}")
        lines.append(f"   {suggestion['message']}")

    lines.append("\n" + "─" * 40)
    lines.append("🐟 Today's Feeding Schedule")
    lines.append("─" * 40)

    total_morning = 0.0
    total_evening = 0.0

    for batch in FishBatch.objects.select_related("pond"):
        total_kg = smart_feed_kg_for_batch(batch)
        if total_kg is None:
            continue

        morning = round(total_kg * 0.6, 2)
        evening = round(total_kg * 0.4, 2)
        total_morning += morning
        total_evening += evening

        lines.append(
            f"\n🏊 {batch.pond.name} — {batch.get_species_display()}"
        )
        lines.append(f"   🌅 Morning (6:00 AM): {morning} kg")
        lines.append(f"   🌆 Evening (4:00 PM): {evening} kg")
        lines.append(f"   📊 Total: {total_kg} kg/day")

    lines.append("\n" + "─" * 40)
    lines.append(f"📦 Total Morning Feed: {round(total_morning, 2)} kg")
    lines.append(f"📦 Total Evening Feed: {round(total_evening, 2)} kg")
    lines.append(f"📦 Grand Total: {round(total_morning + total_evening, 2)} kg")
    lines.append("\n💧 Remember to test water pH today.")
    lines.append("📈 Log growth records weekly.")

    body = "\n".join(lines)
    send_email_notification("🐟 AquaSmart Daily Feed Alert", body)
    send_sms_notification(body)