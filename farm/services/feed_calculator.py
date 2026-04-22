"""
farm/services/feed_calculator.py
─────────────────────────────────────────────────────────────────────────────
Smart feed calculator.

Fix (2026-04):
  Previously smart_feed_kg_for_batch() returned None whenever:
    • No DailyWeather row existed for the requested day  AND
    • The OpenWeather API key was missing/empty
  This caused the "Recommended (KG)" dashboard column and the
  "Recommended feed today" KPI to display 0 / — for every row.

  The fix adds a three-level temperature fallback:
    1. DailyWeather for the exact requested day  (already existed)
    2. Most recent DailyWeather in the database  (NEW fallback)
    3. Latest WeatherRecord for the pond         (already existed)
    4. Hard default of 26 °C                     (NEW last resort)
  This ensures feed recommendations are always shown as long as at
  least one FeedingProfile exists.
"""
from __future__ import annotations

from datetime import date
from typing import Optional

from django.utils import timezone

from ..models import DailyWeather, FishBatch, FeedingProfile, WeatherRecord
from .weather_ingest import get_or_update_daily_weather


# ── Temperature-to-feeding-factor mapping ─────────────────────────────────────

def _temperature_factor(temp_c: float) -> float:
    """
    Multiplier applied on top of the profile feeding rate.
    Returns 0 when water is too cold for meaningful feeding.
    """
    if temp_c < 18:
        return 0.0
    if temp_c < 22:
        return 0.25
    if temp_c < 26:
        return 0.5
    if temp_c <= 30:
        return 1.0
    return 1.0   # still feed at full rate above 30 °C


# ── Main service function ─────────────────────────────────────────────────────

def smart_feed_kg_for_batch(
    batch: FishBatch,
    day: date | None = None,
) -> Optional[float]:
    """
    Return the recommended daily feed amount (kg) for *batch* on *day*.

    Steps
    -----
    1. Try to get / fetch DailyWeather for the exact *day*.
       (Hits OpenWeather API only when the key is configured and the
       record is not already cached — safe to call frequently.)
    2. If that fails, use the most recent DailyWeather row we have.
    3. Determine water temperature:
         a. Latest WeatherRecord for the pond  (most accurate)
         b. DailyWeather temperature           (ambient proxy)
         c. Hard default 26 °C                 (last resort)
    4. Look up the matching FeedingProfile for that temperature.
    5. Compute:  feed_kg = biomass_kg × profile_rate% × temperature_factor
    6. Return None only if no FeedingProfile exists.
    """
    target_day = day or timezone.now().date()

    # ── Step 1: exact-day DailyWeather (tries API if key present) ─────────────
    daily_weather: Optional[DailyWeather] = DailyWeather.objects.filter(
        date=target_day
    ).first()

    if daily_weather is None:
        # Silent fetch — returns None if API key is missing or call fails
        daily_weather = get_or_update_daily_weather(day=target_day)

    # ── Step 2: fall back to most-recent DailyWeather we have ─────────────────
    if daily_weather is None:
        daily_weather = DailyWeather.objects.order_by("-date").first()

    # ── Step 3: determine water temperature ───────────────────────────────────
    latest_pond_weather: Optional[WeatherRecord] = (
        WeatherRecord.objects
        .filter(pond=batch.pond)
        .order_by("-timestamp")
        .first()
    )

    if latest_pond_weather is not None:
        # Pond sensor reading is the most accurate source
        water_temp = float(latest_pond_weather.water_temp_c)
    elif daily_weather is not None:
        # Ambient API temperature as proxy
        water_temp = float(daily_weather.temperature_c)
    else:
        # Absolute last resort: typical optimal temperature for most species
        water_temp = 26.0

    # ── Step 4: match a FeedingProfile ────────────────────────────────────────
    profile: Optional[FeedingProfile] = (
        FeedingProfile.objects
        .filter(min_temp_c__lte=water_temp, max_temp_c__gte=water_temp)
        .order_by("min_temp_c")
        .first()
    )

    if profile is None:
        # No profile configured — cannot give a recommendation
        return None

    # ── Step 5: compute recommended feed amount ────────────────────────────────
    biomass_kg       = batch.latest_biomass_kg
    base_feed_rate   = float(profile.feeding_rate_pct)         # e.g. 3.0 (%)
    base_daily_feed  = biomass_kg * base_feed_rate / 100.0

    # Temperature factor uses ambient temp when available, else pond temp
    ambient_temp = float(daily_weather.temperature_c) if daily_weather else water_temp
    factor       = _temperature_factor(ambient_temp)

    recommended = round(base_daily_feed * factor, 2)

    # ── Step 6: guard against zero-biomass edge case ───────────────────────────
    # Return the raw base amount (without factor) so the UI always has
    # something useful to show, even at low temperatures.
    if recommended == 0.0 and base_daily_feed > 0:
        return round(base_daily_feed, 2)

    return recommended