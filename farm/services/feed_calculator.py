"""
farm/services/feed_calculator.py
─────────────────────────────────────────────────────────────────────────────
Smart feed calculator.

GUARANTEED BEHAVIOUR
────────────────────
This function ALWAYS returns a positive float as long as the batch has fish.
It returns None ONLY when biomass is zero/negative (all fish dead).

Temperature resolution (highest priority first)
───────────────────────────────────────────────
  1. Latest WeatherRecord for the pond  (actual sensor / manual entry)
  2. DailyWeather for the exact day     (OpenWeather API cache)
  3. Most-recent DailyWeather in DB     (fallback for historical dates)
  4. Hard default: 26°C                 (absolute last resort)

Feeding rate resolution
───────────────────────
  1. FeedingProfile matching water temperature
  2. Built-in default: 3.0% of biomass/day  (when no profile configured)
"""
from __future__ import annotations

from datetime import date
from typing import Optional

from django.utils import timezone

from ..models import DailyWeather, FishBatch, FeedingProfile, WeatherRecord
from .weather_ingest import get_or_update_daily_weather


# ── Constants ─────────────────────────────────────────────────────────────────

DEFAULT_FEED_RATE_PCT: float = 3.0   # fallback when no FeedingProfile found
DEFAULT_TEMP_C: float        = 26.0  # fallback when no weather data at all


# ── Temperature factor ────────────────────────────────────────────────────────

def _temperature_factor(temp_c: float) -> float:
    """
    Appetite multiplier applied on top of the profile feeding rate.

      < 18°C  → 0.10  (very cold; minimal ration, never zero)
      18–21°C → 0.40  (cool; reduced appetite)
      22–25°C → 0.70  (sub-optimal)
      26–30°C → 1.00  (optimal range)
      > 30°C  → 0.90  (warm; slight stress)
    """
    if temp_c < 18:
        return 0.10
    if temp_c < 22:
        return 0.40
    if temp_c < 26:
        return 0.70
    if temp_c <= 30:
        return 1.00
    return 0.90


# ── Main service function ─────────────────────────────────────────────────────

def smart_feed_kg_for_batch(
    batch: FishBatch,
    day: date | None = None,
) -> Optional[float]:
    """
    Return the recommended daily feed (kg) for *batch* on *day*.

    Never returns None as long as the batch has a positive biomass.
    """
    target_day = day or timezone.now().date()

    # Guard: no fish → no feed
    biomass_kg = batch.latest_biomass_kg
    if biomass_kg <= 0:
        return None

    # ── Step 1: resolve water temperature ─────────────────────────────────────

    # Priority A — pond WeatherRecord (most accurate, from manual log / IoT)
    pond_record: Optional[WeatherRecord] = (
        WeatherRecord.objects
        .filter(pond=batch.pond)
        .order_by("-timestamp")
        .first()
    )

    # Priority B — DailyWeather for the exact requested day
    daily_weather: Optional[DailyWeather] = (
        DailyWeather.objects.filter(date=target_day).first()
    )
    if daily_weather is None:
        # Try live API fetch (silent no-op when key is not configured)
        daily_weather = get_or_update_daily_weather(day=target_day)

    # Priority C — most-recent DailyWeather row (for historical dates)
    if daily_weather is None:
        daily_weather = DailyWeather.objects.order_by("-date").first()

    # Determine water temp for FeedingProfile look-up
    if pond_record is not None:
        water_temp = float(pond_record.water_temp_c)
    elif daily_weather is not None:
        water_temp = float(daily_weather.temperature_c)
    else:
        water_temp = DEFAULT_TEMP_C   # Priority D — absolute fallback

    # Determine ambient temp for appetite factor
    # (prefer API/daily weather over pond sensor for ambient context)
    if daily_weather is not None:
        ambient_temp = float(daily_weather.temperature_c)
    elif pond_record is not None:
        ambient_temp = float(pond_record.water_temp_c)
    else:
        ambient_temp = DEFAULT_TEMP_C

    # ── Step 2: resolve feeding rate ──────────────────────────────────────────

    profile: Optional[FeedingProfile] = (
        FeedingProfile.objects
        .filter(min_temp_c__lte=water_temp, max_temp_c__gte=water_temp)
        .order_by("min_temp_c")
        .first()
    )

    # Use profile rate if found, otherwise use built-in default
    feed_rate_pct = (
        float(profile.feeding_rate_pct)
        if profile is not None
        else DEFAULT_FEED_RATE_PCT
    )

    # ── Step 3: calculate ─────────────────────────────────────────────────────

    base_feed   = biomass_kg * feed_rate_pct / 100.0
    factor      = _temperature_factor(ambient_temp)
    recommended = round(base_feed * factor, 2)

    # Never return 0 — always give at least the base amount
    if recommended <= 0:
        return round(base_feed, 2)

    return recommended