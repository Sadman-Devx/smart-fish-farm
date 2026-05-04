"""
farm/management/commands/fetch_daily_weather.py
─────────────────────────────────────────────
Run: python manage.py fetch_daily_weather

Fetches today's weather from OpenWeather API and stores in DailyWeather.
"""
from __future__ import annotations

import logging
from datetime import date

import requests
from django.conf import settings
from django.core.management.base import BaseCommand, CommandError

from farm.models import DailyWeather
from farm.services.weather_ingest import _safe_float, _session, _calculate_feed_percent

logger = logging.getLogger(__name__)


class Command(BaseCommand):
    help = "Fetch today's weather from OpenWeather and store in DailyWeather."

    def handle(self, *args, **options):
        api_key = getattr(settings, "WEATHER_API_KEY", "").strip()
        location = getattr(settings, "WEATHER_LOCATION", "Dhaka,BD").strip()

        if not api_key:
            raise CommandError("WEATHER_API_KEY is not set in settings/environment.")

        url = "https://api.openweathermap.org/data/2.5/weather"
        params = {"q": location, "appid": api_key, "units": "metric"}

        self.stdout.write(f"🔄 Fetching weather for: {location}...")

        try:
            # ✅ FIX: Reuse persistent HTTP connection pool
            response = _session.get(url, params=params, timeout=10)
            response.raise_for_status()
            data = response.json()
        except requests.exceptions.Timeout:
            raise CommandError("⚠️ API request timed out. Check your internet connection.")
        except requests.exceptions.ConnectionError as e:
            raise CommandError(f"⚠️ Network error: {e}")
        except Exception as e:
            raise CommandError(f"⚠️ Unexpected error: {e}")

        # ✅ FIX: Safe JSON parsing (prevents crash on "404 city not found")
        main_data = data.get("main", {})
        weather_list = data.get("weather", [])

        if not main_data or not weather_list:
            cod = data.get("cod", "?")
            raise CommandError(
                f"❌ Invalid API response (cod: {cod}). "
                f"Check API key and location: {location}"
            )

        temp_c = _safe_float(main_data.get("temp"))
        condition = weather_list[0].get("main", "Unknown")

        today = date.today()

        # Check if already exists to show "created" vs "updated" message
        existed = DailyWeather.objects.filter(date=today).exists()

        # ✅ FIX: Reuse existing centralized logic instead of duplicating if/else chain
        feed_pct = _calculate_feed_percent(temp_c)

        # Save to DB
        daily = DailyWeather.objects.update_or_create(
            date=today,
            defaults={
                "location_query": location,
                "temperature_c": temp_c,
                "condition": condition,
                "feed_percent": feed_pct,
                "raw_payload": data,
            },
        )

        status = "🔄 Updated" if existed else "✅ Created"
        self.stdout.write(
            self.style.SUCCESS(
                f"{status} DailyWeather for {today}: "
                f"{temp_c:.1f}°C, {condition}, feed {feed_pct:.0f}%"
            )
        )