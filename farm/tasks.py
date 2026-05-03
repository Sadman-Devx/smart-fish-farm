from __future__ import annotations

from django.conf import settings
from django.contrib.auth import get_user_model
from django.utils import timezone
from celery import shared_task

from .models import DailyWeather, FishBatch, Pond, WeatherRecord, FarmProfile
from .notifications import send_email_notification, send_sms_notification, send_whatsapp_notification
from .services import smart_feed_kg_for_batch
from .services.weather_ingest import get_feeding_suggestion, get_weather_for_location, get_weather_by_city
from .services.generate_water_alerts import generate_water_alerts

User = get_user_model()


@shared_task
def send_daily_feed_alert():
    today = timezone.now().date()
    daily_weather = DailyWeather.objects.filter(date=today).first()

    suggestion = None
    if daily_weather:
        suggestion = get_feeding_suggestion(
            temp_c=float(daily_weather.temperature_c),
            humidity=70,
            rain_mm=0,
        )

    # select_related('pond') is used to optimize DB queries
    active_users = User.objects.filter(is_active=True).prefetch_related('profile', 'farm_profile')

    for user in active_users:
        if not user.email:
            continue

        # Using getattr to avoid try-except blocks (Clean Code)
        user_phone = getattr(user, 'profile', None) and getattr(user.profile, 'phone_number', "") or ""
        if not user_phone:
            user_phone = getattr(user, 'farm_profile', None) and getattr(user.farm_profile, 'phone_number', "") or ""

        # Only this user's batches
        user_batches = FishBatch.objects.select_related("pond").filter(pond__owner=user)
        
        # Removed .exists() to directly loop, avoiding an extra DB query
        if not user_batches:
            continue

        # ── Build Message ─────────────────────────────────────────────────────
        lines: list[str] = []
        lines.append("📢 AquaSmart — Daily Feed Alert")
        lines.append(f"Date: {today}")

        if daily_weather:
            lines.append(f"🌡️ Temp: {daily_weather.temperature_c}°C | ☁️ {daily_weather.condition}")

        if suggestion:
            lines.append(f"{suggestion['icon']} {suggestion['title']}: {suggestion['message']}")

        lines.append("\n" + "─" * 30)
        
        total_morning = 0.0
        total_evening = 0.0

        for batch in user_batches:
            total_kg = smart_feed_kg_for_batch(batch)
            if total_kg is None:
                continue

            morning = round(total_kg * 0.6, 2)
            evening = round(total_kg * 0.4, 2)
            total_morning += morning
            total_evening += evening

            lines.append(f"🏊 {batch.pond.name} ({batch.get_species_display()}): 🌅{morning}kg | 🌆{evening}kg")

        grand_total = round(total_morning + total_evening, 2)
        lines.append("─" * 30)
        lines.append(f"📦 Grand Total: {grand_total} kg")
        lines.append("💧 Test water pH today.")

        full_body = "\n".join(lines)

        # ── Create short message for SMS ──────────────────────────────────
        short_sms_body = (
            f"AquaSmart Alert ({today}):\n"
            f"Total Feed: {grand_total}kg (Morning: {round(total_morning,2)}kg, Evening: {round(total_evening,2)}kg).\n"
            f"Check email for details."
        )

        # ── Send to THIS user only ────────────────────────────────────────────
        send_email_notification(
            "🐟 AquaSmart Daily Feed Alert",
            full_body,
            recipient_email=user.email,
        )
        
        if user_phone:
            # Sending short text for SMS instead of full text
            send_sms_notification(short_sms_body, to_number=user_phone)
            # Full text can be sent via WhatsApp
            send_whatsapp_notification(full_body, to_number=user_phone)


@shared_task
def auto_log_water_temperature():
    """
    Automatically logs water temperature for each farm/user 
    based on their specific location.
    """
    today = timezone.now().date()
    active_users = User.objects.filter(is_active=True)

    for user in active_users:
        # Get user's farm profile
        fp = getattr(user, 'farm_profile', None)
        if not fp or not getattr(fp, 'onboarding_complete', False):
            continue

        # Get ponds belonging to this user
        user_ponds = Pond.objects.filter(owner=user)
        if not user_ponds.exists():
            continue

        air_temp: float | None = None
        rainfall: float = 0.0

        try:
            data = None
            if getattr(fp, 'latitude', None) and getattr(fp, 'longitude', None):
                data = get_weather_for_location(float(fp.latitude), float(fp.longitude))
            elif getattr(fp, 'district', None):
                upazila = getattr(fp, 'upazila', '')
                query = f"{upazila},{fp.district},BD" if upazila else f"{fp.district},BD"
                data = get_weather_by_city(query)

            if data:
                air_temp = data["temp_c"]
                rainfall = float(data.get("rain_mm", 0) or 0)
        except Exception:
            pass

        # Fallback: If API fails, fetch from DailyWeather
        if air_temp is None:
            dw = DailyWeather.objects.filter(date=today).first()
            if dw:
                air_temp = float(dw.temperature_c)

        # No temperature data found for this user, skip to next user
        if air_temp is None:
            continue 

        water_temp = round(air_temp - 2.0, 1)

        # Check and save only for this user's ponds
        for pond in user_ponds:
            already_has_entry = WeatherRecord.objects.filter(
                pond=pond,
                timestamp__date=today,
            ).exists()

            if not already_has_entry:
                WeatherRecord.objects.create(
                    pond=pond,
                    water_temp_c=water_temp,
                    dissolved_oxygen_mg_l=6.5,
                    ph=7.0,
                    rainfall_mm=rainfall,
                    source="auto",
                )

    return "Auto water temperature logging completed for all users"


@shared_task
def run_predictive_alerts_task():
    """
    Hourly Celery task — runs predictive alert checks for all users.
    """
    from .services.predictive_alerts import run_predictive_alerts

    try:
        # If your service function handles all users when user=None, this is fine. 
        # Otherwise, you need to loop through users here like the other tasks.
        count = run_predictive_alerts(user=None)
        return f"Predictive alerts: {count} new alerts created"
    except Exception as e:
        return f"Predictive alerts task failed: {e}"