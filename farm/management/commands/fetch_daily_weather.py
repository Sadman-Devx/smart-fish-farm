from datetime import date

import requests
from django.conf import settings
from django.core.management.base import BaseCommand, CommandError

from farm.models import DailyWeather
from farm.services import save_daily_weather


class Command(BaseCommand):
    help = "Fetch today's weather from OpenWeather and store DailyWeather with a recommended feed %."

    def handle(self, *args, **options):
        api_key = settings.WEATHER_API_KEY
        location = settings.WEATHER_LOCATION

        if not api_key:
            raise CommandError("OPENWEATHER_API_KEY is not set in environment.")

        url = "https://api.openweathermap.org/data/2.5/weather"
        params = {"q": location, "appid": api_key, "units": "metric"}

        self.stdout.write(f"Fetching weather for {location}...")
        resp = requests.get(url, params=params, timeout=10)
        resp.raise_for_status()
        data = resp.json()

        temp_c = float(data["main"]["temp"])
        condition = data["weather"][0]["main"]

        # Same mapping used by dashboard auto-update service.
        if temp_c >= 30:
            feed_pct = 100.0
        elif temp_c >= 25:
            feed_pct = 70.0
        elif temp_c >= 20:
            feed_pct = 30.0
        else:
            feed_pct = 10.0

        today = date.today()

        existed = DailyWeather.objects.filter(date=today).exists()
        daily = save_daily_weather(
            day=today,
            location_query=location,
            temperature_c=temp_c,
            condition=condition,
            feed_percent=feed_pct,
            payload=data,
        )

        status = "updated" if existed else "created"
        self.stdout.write(
            self.style.SUCCESS(
                f"{status} DailyWeather for {today}: {temp_c:.1f}°C, {condition}, feed {feed_pct}%"
            )
        )

