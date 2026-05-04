"""
farm/services/weather_ingest.py (Ultimate Merged Version)
==========================================================
"""
from __future__ import annotations

import logging
from datetime import date
from typing import Any

import requests
from django.conf import settings

from ..models import DailyWeather

logger = logging.getLogger(__name__)

# ✅ PERFORMANCE FIX: Module-level session for HTTP Keep-Alive (Connection Pooling)
_session = requests.Session()


# ──────────────────────────────────────────────
#  Safe type helpers
# ──────────────────────────────────────────────
def _safe_float(value: Any, default: float = 0.0) -> float:
    if value is None: return default
    try: return float(value)
    except (TypeError, ValueError): return default

def _safe_int(value: Any, default: int = 0) -> int:
    if value is None: return default
    try: return int(value)
    except (TypeError, ValueError): return default


# ──────────────────────────────────────────────
#  Private DRY Helper for API Responses
# ──────────────────────────────────────────────
def _extract_weather_payload(payload: dict) -> dict | None:
    """
    Safely extract weather data from OpenWeatherMap JSON.
    Returns None if the payload is malformed or missing required keys.
    """
    if not payload or not isinstance(payload, dict):
        return None
        
    main_data = payload.get("main")
    weather_list = payload.get("weather")
    
    if not main_data or not weather_list:
        return None
        
    return {
        "temp_c":    _safe_float(main_data.get("temp")),
        "humidity":  _safe_int(main_data.get("humidity"), default=50),
        "rain_mm":   _safe_float(payload.get("rain", {}).get("1h", 0)),
        "condition": weather_list[0].get("main", "Unknown") if weather_list else "Unknown",
    }


# ──────────────────────────────────────────────
#  DB persistence
# ──────────────────────────────────────────────
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
            "location_query": location_query or "",
            "temperature_c": _safe_float(temperature_c),
            "condition": condition or "Unknown",
            "feed_percent": _safe_float(feed_percent),
            "raw_payload": payload,
        },
    )
    return weather


def _calculate_feed_percent(temp_c: float | None) -> float:
    if temp_c is None: return 50.0
    temp_c = _safe_float(temp_c)
    if temp_c >= 30: return 100.0
    if temp_c >= 25: return 70.0
    if temp_c >= 20: return 30.0
    return 10.0


# ──────────────────────────────────────────────
#  Get / update weather for a day
# ──────────────────────────────────────────────
def get_or_update_daily_weather(day: date | None = None) -> DailyWeather | None:
    """Returns weather for requested day. Fetches API only if not stored."""
    target_day = day or date.today()
    location = getattr(settings, "WEATHER_LOCATION", "")
    existing = DailyWeather.objects.filter(date=target_day).first()

    # Safe location comparison (handles DB nulls)
    if existing is not None and (existing.location_query or "") == location:
        return existing

    api_key = getattr(settings, "WEATHER_API_KEY", "")
    if not api_key or not api_key.strip():
        return existing  # Return existing (could be None) instead of hard None

    try:
        # ✅ Uses persistent session instead of raw requests.get()
        response = _session.get(
            "https://api.openweathermap.org/data/2.5/weather",
            params={"q": location, "appid": api_key.strip(), "units": "metric"},
            timeout=10,
        )
        response.raise_for_status()
        
        # ✅ Uses DRY helper for safe extraction
        data = _extract_weather_payload(response.json())
        if not data:
            logger.warning("OpenWeatherMap returned unexpected payload for %s", location)
            return existing

        return save_daily_weather(
            day=target_day,
            location_query=location,
            temperature_c=data["temp_c"],
            condition=data["condition"],
            feed_percent=_calculate_feed_percent(data["temp_c"]),
            payload=response.json(),
        )
        
    except requests.Timeout:
        logger.warning("OpenWeatherMap request timed out for %s", location)
        return existing  # ✅ SYSTEM RECOVERY: Return old data on timeout
    except requests.HTTPError as e:
        logger.warning("OpenWeatherMap HTTP error for %s: %s", location, e)
        return existing
    except Exception:
        logger.exception("Unexpected error fetching weather for %s", location)
        return None


# ──────────────────────────────────────────────
#  GPS-coordinate based lookup
# ──────────────────────────────────────────────
def get_weather_for_location(lat: float | None, lon: float | None) -> dict | None:
    """Fetch live weather using GPS coordinates."""
    if lat is None or lon is None:
        logger.warning("get_weather_for_location called with None lat/lon")
        return None

    api_key = getattr(settings, "WEATHER_API_KEY", "")
    if not api_key or not api_key.strip():
        return None

    try:
        response = _session.get(
            "https://api.openweathermap.org/data/2.5/weather",
            params={
                "lat": _safe_float(lat),
                "lon": _safe_float(lon),
                "appid": api_key.strip(),
                "units": "metric",
            },
            timeout=10,
        )
        response.raise_for_status()
        
        return _extract_weather_payload(response.json())
        
    except Exception:
        logger.exception("Error fetching weather for lat=%s lon=%s", lat, lon)
        return None


# ──────────────────────────────────────────────
#  Feeding suggestion
# ──────────────────────────────────────────────
def get_feeding_suggestion(temp_c: float | None, humidity: int | None, rain_mm: float | None) -> dict:
    """Returns feeding suggestion based on weather conditions."""
    temp_c = _safe_float(temp_c)
    humidity = _safe_int(humidity, default=50)
    rain_mm = _safe_float(rain_mm)

    if rain_mm > 5:
        return {"status": "danger", "icon": "❌", "title": "Minimal Feeding",
                "message": "Heavy rain detected — reduce feed to 30% to avoid waste."}
    if temp_c < 22 or humidity > 85:
        reason = 'Low temperature' if temp_c < 22 else 'High humidity'
        return {"status": "warning", "icon": "⚠️", "title": "Reduce Feed by 30%",
                "message": f"{reason} — fish appetite is reduced."}
    if 26 <= temp_c <= 30:
        return {"status": "success", "icon": "✅", "title": "Good Feeding Conditions",
                "message": "Temperature and humidity are optimal. Feed at full rate."}
    return {"status": "info", "icon": "ℹ️", "title": "Moderate Conditions",
            "message": f"Temperature {temp_c:.1f}°C — feed at normal rate."}


# ──────────────────────────────────────────────
#  City / district name lookup
# ──────────────────────────────────────────────
def get_weather_by_city(location_query: str | None) -> dict | None:
    """Fetch live weather using city/district name with DB cache fallback."""
    if not location_query or not location_query.strip():
        return None

    location_query = location_query.strip()
    today = date.today()

    # ✅ USER'S EXCELLENT FIX: Check DB cache first to avoid API hit
    existing = DailyWeather.objects.filter(date=today, location_query=location_query).first()
    if existing and existing.temperature_c is not None:
        return {
            "temp_c":    _safe_float(existing.temperature_c),
            "humidity":  _safe_int(getattr(existing, "humidity", None), default=50),
            "rain_mm":   _safe_float(getattr(existing, "rain_mm", None)),
            "condition": existing.condition or "Unknown",
        }

    api_key = getattr(settings, "WEATHER_API_KEY", "")
    if not api_key or not api_key.strip():
        return None

    # ✅ USER'S EXCELLENT FIX: Handle "Dhaka,,BD" edge cases
    queries_to_try = [location_query]
    if "," in location_query:
        parts = [p.strip() for p in location_query.split(",") if p.strip()]
        if len(parts) >= 2:
            queries_to_try.append(f"{parts[-2]},{parts[-1]}")

    for query in queries_to_try:
        try:
            response = _session.get(
                "https://api.openweathermap.org/data/2.5/weather",
                params={"q": query, "appid": api_key.strip(), "units": "metric"},
                timeout=10,
            )
            if response.status_code == 200:
                data = _extract_weather_payload(response.json())
                if not data:
                    continue

                # ✅ Cache the successful API result in DB
                save_daily_weather(
                    day=today,
                    location_query=location_query,
                    temperature_c=data["temp_c"],
                    condition=data["condition"],
                    feed_percent=_calculate_feed_percent(data["temp_c"]),
                    payload=response.json(),
                )
                return data

        except requests.Timeout:
            logger.warning("OpenWeatherMap timed out for query=%s", query)
            continue
        except Exception:
            logger.exception("Error fetching weather for query=%s", query)
            continue

    return None