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

def get_weather_for_location(lat: float, lon: float) -> dict | None:
    """
    Fetch live weather using GPS coordinates.
    Returns dict with temp, humidity, rain, condition or None on failure.
    """
    api_key = settings.WEATHER_API_KEY
    if not api_key:
        return None

    url = "https://api.openweathermap.org/data/2.5/weather"
    params = {
        "lat": lat,
        "lon": lon,
        "appid": api_key,
        "units": "metric",
    }

    try:
        response = requests.get(url, params=params, timeout=10)
        response.raise_for_status()
        payload = response.json()
        return {
            "temp_c":    float(payload["main"]["temp"]),
            "humidity":  int(payload["main"]["humidity"]),
            "rain_mm":   float(payload.get("rain", {}).get("1h", 0)),
            "condition": payload["weather"][0]["main"],
        }
    except Exception:
        return None


def get_feeding_suggestion(temp_c: float, humidity: int, rain_mm: float) -> dict:
    """
    Returns feeding suggestion based on weather conditions.
    """
    if rain_mm > 5:
        return {
            "status": "danger",
            "icon": "❌",
            "title": "Minimal Feeding",
            "message": "Heavy rain detected — reduce feed to 30% to avoid waste.",
        }
    if temp_c < 22 or humidity > 85:
        return {
            "status": "warning",
            "icon": "⚠️",
            "title": "Reduce Feed by 30%",
            "message": f"{'Low temperature' if temp_c < 22 else 'High humidity'} — fish appetite is reduced.",
        }
    if 26 <= temp_c <= 30:
        return {
            "status": "success",
            "icon": "✅",
            "title": "Good Feeding Conditions",
            "message": "Temperature and humidity are optimal. Feed at full rate.",
        }
    return {
        "status": "info",
        "icon": "ℹ️",
        "title": "Moderate Conditions",
        "message": f"Temperature {temp_c:.1f}°C — feed at normal rate.",
    }

def get_weather_by_city(location_query: str) -> dict | None:
    """
    Fetch live weather using city/district name.
    Tries full query first, then falls back to district only.
    """
    api_key = settings.WEATHER_API_KEY
    if not api_key:
        return None

    url = "https://api.openweathermap.org/data/2.5/weather"

    # প্রথমে full query try করো, না হলে শুধু district দিয়ে try করো
    queries_to_try = [location_query]
    if "," in location_query:
        parts = location_query.split(",")
        # শুধু district + country দিয়ে try করো
        queries_to_try.append(f"{parts[-2].strip()},{parts[-1].strip()}")

    for query in queries_to_try:
        try:
            response = requests.get(
                url,
                params={"q": query, "appid": api_key, "units": "metric"},
                timeout=10,
            )
            if response.status_code == 200:
                payload = response.json()
                return {
                    "temp_c":    float(payload["main"]["temp"]),
                    "humidity":  int(payload["main"]["humidity"]),
                    "rain_mm":   float(payload.get("rain", {}).get("1h", 0)),
                    "condition": payload["weather"][0]["main"],
                }
        except Exception:
            continue

    return None