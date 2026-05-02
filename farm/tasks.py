from __future__ import annotations

from django.conf import settings
from django.utils import timezone
from celery import shared_task

from .models import DailyWeather, FishBatch
from .notifications import send_email_notification, send_sms_notification, send_whatsapp_notification
from .services import smart_feed_kg_for_batch
from .services.weather_ingest import get_feeding_suggestion


@shared_task
def send_daily_feed_alert():
    """
    Enhanced daily feed summary with morning/evening split
    and weather-based feeding recommendation.
    """
    today         = timezone.now().date()
    daily_weather = DailyWeather.objects.filter(date=today).first()

    suggestion = None
    if daily_weather:
        suggestion = get_feeding_suggestion(
            temp_c   = float(daily_weather.temperature_c),
            humidity = 70,
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

        lines.append(f"\n🏊 {batch.pond.name} — {batch.get_species_display()}")
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
    send_whatsapp_notification(body)


@shared_task
def auto_log_water_temperature():
    """
    Automatically logs estimated water temperature for all ponds once per day.

    FIX: `rainfall` was referenced before assignment when `dw` was None inside
    the except branch, causing a NameError. Initialise both `air_temp` and
    `rainfall` to None / 0 up front so every code path is safe.
    """
    from .models import Pond, WeatherRecord, DailyWeather, FarmProfile
    from .services.weather_ingest import get_weather_for_location, get_weather_by_city

    today = timezone.now().date()

    # Skip if already auto-logged today
    already_logged = WeatherRecord.objects.filter(
        timestamp__date=today,
        source="auto",
    ).exists()

    if already_logged:
        return "Already logged today"

    # FIX: initialise both variables so they are always defined
    air_temp: float | None = None
    rainfall: float = 0.0

    try:
        fp = FarmProfile.objects.filter(onboarding_complete=True).first()
        if fp:
            data = None
            if fp.latitude and fp.longitude:
                data = get_weather_for_location(
                    float(fp.latitude), float(fp.longitude)
                )
            elif fp.district:
                query = (
                    f"{fp.upazila},{fp.district},BD"
                    if fp.upazila
                    else f"{fp.district},BD"
                )
                data = get_weather_by_city(query)

            if data:
                air_temp = data["temp_c"]
                rainfall = float(data.get("rain_mm", 0) or 0)
            else:
                # Fall back to today's cached DailyWeather row
                dw = DailyWeather.objects.filter(date=today).first()
                if dw:
                    air_temp = float(dw.temperature_c)
                    rainfall = 0.0          # DailyWeather has no rain_mm field

    except Exception:
        # Last-resort fallback: use DailyWeather if the API call threw
        dw = DailyWeather.objects.filter(date=today).first()
        if dw:
            air_temp = float(dw.temperature_c)
            rainfall = 0.0

    if air_temp is None:
        return "No temperature data available"

    # Pond water is typically ~2 °C cooler than ambient air
    water_temp = round(air_temp - 2.0, 1)

    ponds = Pond.objects.all()
    count = 0

    for pond in ponds:
        already_has_entry = WeatherRecord.objects.filter(
            pond=pond,
            timestamp__date=today,
        ).exists()

        if not already_has_entry:
            WeatherRecord.objects.create(
                pond=pond,
                water_temp_c=water_temp,
                dissolved_oxygen_mg_l=6.5,   # sane default
                ph=7.0,                       # sane default
                rainfall_mm=rainfall,
                source="auto",
            )
            count += 1

    return f"Auto logged water temp {water_temp}°C for {count} ponds"

@shared_task
def run_predictive_alerts_task():
    """
    Hourly Celery task — runs predictive alert checks for all users.
    Analyzes temperature trends, DO trends, and mortality patterns.
    """
    from .services.predictive_alerts import run_predictive_alerts
 
    try:
        count = run_predictive_alerts(user=None)   # None = all users
        return f"Predictive alerts: {count} new alerts created"
    except Exception as e:
        return f"Predictive alerts task failed: {e}"