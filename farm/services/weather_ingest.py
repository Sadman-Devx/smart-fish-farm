from __future__ import annotations

from datetime import date
from typing import Any

import requests
from django.conf import settings

from ..models import DailyWeather


def save_daily_weather(
    day: date,
    location_query: str,
    temperature_c: float,
    condition: str,
    feed_percent: float,
    payload: dict[str, Any] | None = None,
) -> DailyWeather:
    weather, _ = DailyWeather.objects.update_or_create(
        date=day,
        defaults={
            "location_query": location_query,
            "temperature_c": temperature_c,
            "condition": condition,
            "feed_percent": feed_percent,
            "raw_payload": payload,
        },
    )
    return weather


def _calculate_feed_percent(temp_c: float) -> float:
    if temp_c >= 30:
        return 100.0
    if temp_c >= 25:
        return 70.0
    if temp_c >= 20:
        return 30.0
    return 10.0


def get_or_update_daily_weather(day: date | None = None) -> DailyWeather | None:
    """
    Returns weather for the requested day.
    Fetches from API only if not already stored for that day.
    """
    target_day = day or date.today()
    location = settings.WEATHER_LOCATION
    existing = DailyWeather.objects.filter(date=target_day).first()
    if existing is not None and existing.location_query == location:
        return existing

    api_key = settings.WEATHER_API_KEY
    if not api_key:
        return None

    url = "https://api.openweathermap.org/data/2.5/weather"
    params = {"q": location, "appid": api_key, "units": "metric"}

    try:
        response = requests.get(url, params=params, timeout=10)
        response.raise_for_status()
        payload = response.json()
        temp_c = float(payload["main"]["temp"])
        condition = payload["weather"][0]["main"]
    except Exception:
        return None

    return save_daily_weather(
        day=target_day,
        location_query=location,
        temperature_c=temp_c,
        condition=condition,
        feed_percent=_calculate_feed_percent(temp_c),
        payload=payload,
    )

