from __future__ import annotations

from datetime import date
from typing import Optional

from django.utils import timezone

from ..models import DailyWeather, FishBatch, FeedingProfile, WeatherRecord
from .weather_ingest import get_or_update_daily_weather


def _temperature_factor(temp_c: float) -> float:
    if temp_c < 18:
        return 0.0
    if temp_c < 22:
        return 0.25
    if temp_c < 26:
        return 0.5
    if temp_c <= 30:
        return 1.0
    return 1.0


def smart_feed_kg_for_batch(batch: FishBatch, day: date | None = None) -> Optional[float]:
    target_day = day or timezone.now().date()
    daily_weather: Optional[DailyWeather] = DailyWeather.objects.filter(date=target_day).first()
    if daily_weather is None:
        daily_weather = get_or_update_daily_weather(day=target_day)

    latest_weather: Optional[WeatherRecord] = (
        WeatherRecord.objects.filter(pond=batch.pond).order_by("-timestamp").first()
    )
    biomass_kg = batch.latest_biomass_kg
    if latest_weather is not None:
        water_temp = float(latest_weather.water_temp_c)
    elif daily_weather is not None:
        water_temp = float(daily_weather.temperature_c)
    else:
        return None

    profile: Optional[FeedingProfile] = (
        FeedingProfile.objects.filter(min_temp_c__lte=water_temp, max_temp_c__gte=water_temp)
        .order_by("min_temp_c")
        .first()
    )
    if profile is None:
        return None

    base_feed_rate_pct = float(profile.feeding_rate_pct)
    daily_feed_kg = biomass_kg * base_feed_rate_pct / 100.0

    factor = _temperature_factor(float(daily_weather.temperature_c)) if daily_weather else _temperature_factor(water_temp)
    return round(daily_feed_kg * factor, 2)

