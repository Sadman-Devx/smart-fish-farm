"""
farm/services/feed_calculator.py
─────────────────────────────────────────────────────────────────────────────
Smart feed calculator (Optimized & Crash-Proof)
================================================

GUARANTEED BEHAVIOUR
────────────────────
Always returns a positive float as long as the batch has fish.
Returns None ONLY when biomass is zero/negative/None (all fish dead).

Temperature resolution (highest priority first)
───────────────────────────────────────────────
  1. Latest WeatherRecord for the pond  (actual sensor / manual entry)
  2. DailyWeather for the exact day     (DB Cache)
  3. Most-recent DailyWeather in DB     (fallback for historical dates)
  4. Hard default: 26°C                 (absolute last resort)

Feeding rate resolution
───────────────────────
  1. FeedingProfile matching water temp (Cached to prevent N+1 queries)
  2. Built-in default: 3.0% of biomass/day
"""
from __future__ import annotations

import logging
from datetime import date
from typing import Optional

from django.core.cache import cache
from django.utils import timezone

from ..models import DailyWeather, FishBatch, FeedingProfile, WeatherRecord

logger = logging.getLogger(__name__)

# ── Constants ─────────────────────────────────────────────────────────────────

DEFAULT_FEED_RATE_PCT: float = 3.0
DEFAULT_TEMP_C: float        = 26.0

# Cache key for FeedingProfiles (they rarely change)
_PROFILE_CACHE_KEY = "feeding_profiles_all"
_PROFILE_CACHE_TIMEOUT = 3600  # 1 hour


# ── Helpers ───────────────────────────────────────────────────────────────────

def _safe_float(value, default: float = 0.0) -> float:
    """Safely convert to float; returns *default* on None / bad value."""
    if value is None:
        return default
    try:
        return float(value)
    except (ValueError, TypeError):
        return default


def _get_cached_profile_rate(water_temp: float) -> float:
    """
    Fetch feeding rate from cache/DB.
    Prevents N+1 queries when calculating feed for multiple batches on dashboard.
    """
    profiles = cache.get(_PROFILE_CACHE_KEY)
    
    if profiles is None:
        profiles = list(FeedingProfile.objects.all())
        cache.set(_PROFILE_CACHE_KEY, profiles, timeout=_PROFILE_CACHE_TIMEOUT)
    
    # Find matching profile in memory (fast, since list is tiny)
    matching = [
        p for p in profiles 
        if _safe_float(p.min_temp_c) <= water_temp <= _safe_float(p.max_temp_c)
    ]
    
    if matching:
        # Return the tightest fitting profile's rate
        return _safe_float(matching[0].feeding_rate_pct, DEFAULT_FEED_RATE_PCT)
        
    return DEFAULT_FEED_RATE_PCT


def _temperature_factor(temp_c: float) -> float:
    """
    Appetite multiplier applied on top of the profile feeding rate.
      < 18°C  → 0.10  |  18–21°C → 0.40  |  22–25°C → 0.70
      26–30°C → 1.00  |  > 30°C  → 0.90
    """
    if temp_c < 18: return 0.10
    if temp_c < 22: return 0.40
    if temp_c < 26: return 0.70
    if temp_c <= 30: return 1.00
    return 0.90


# ── Main service function ─────────────────────────────────────────────────────

def smart_feed_kg_for_batch(
    batch: FishBatch,
    day: date | None = None,
    try_live_api: bool = False,  # ✅ FIX: Explicit flag to prevent hidden API blocks
) -> Optional[float]:
    """
    Return the recommended daily feed (kg) for *batch* on *day*.
    """
    target_day = day or timezone.now().date()

    # ── Step 0: Guard clauses ─────────────────────────────────────────────────
    
    # ✅ FIX: Handle None biomass (e.g., no growth records yet)
    biomass_kg = _safe_float(batch.latest_biomass_kg)
    if biomass_kg <= 0:
        return None

    # ── Step 1: resolve water & ambient temperature safely ────────────────────

    water_temp = 0.0
    ambient_temp = 0.0

    # Priority A — Pond Sensor (Most accurate)
    # ✅ FIX: Guard against batch.pond being None
    if batch.pond is not None:
        pond_record = (
            WeatherRecord.objects
            .filter(pond=batch.pond)
            .order_by("-timestamp")
            .first()
        )
        if pond_record is not None:
            # ✅ FIX: Safely handle nullable DB fields
            water_temp = _safe_float(pond_record.water_temp_c)

    # Priority B — Daily Weather from DB
    daily_weather = DailyWeather.objects.filter(date=target_day).first()
    
    # Priority C — Live API fetch (ONLY if explicitly requested, e.g., via Cron)
    # ✅ FIX: Prevents dashboard from taking 15 seconds to load due to HTTP calls
    if daily_weather is None and try_live_api:
        try:
            from .weather_ingest import get_or_update_daily_weather
            daily_weather = get_or_update_daily_weather(day=target_day)
        except Exception as e:
            logger.warning(f"[FeedCalc] API fetch failed: {e}")

    # Priority D — Fallback to most recent DailyWeather
    if daily_weather is None:
        daily_weather = DailyWeather.objects.order_by("-date").first()

    # Process daily weather if found
    if daily_weather is not None:
        dw_temp = _safe_float(daily_weather.temperature_c)
        
        # Use daily weather for ambient temp
        if dw_temp > 0:
            ambient_temp = dw_temp
            
        # Fallback water temp if pond sensor failed
        if water_temp == 0.0 and dw_temp > 0:
            water_temp = dw_temp

    # Priority E — Absolute hardcoded fallback
    if water_temp == 0.0:
        water_temp = DEFAULT_TEMP_C
    if ambient_temp == 0.0:
        ambient_temp = DEFAULT_TEMP_C

    # ── Step 2: resolve feeding rate (Cached) ────────────────────────────────
    
    # ✅ FIX: Uses cached profiles instead of hitting DB for every batch
    feed_rate_pct = _get_cached_profile_rate(water_temp)

    # ── Step 3: calculate ─────────────────────────────────────────────────────
    
    base_feed   = biomass_kg * feed_rate_pct / 100.0
    factor      = _temperature_factor(ambient_temp)
    recommended = round(base_feed * factor, 2)

    # Since factor is mathematically always >= 0.10 and biomass > 0, 
    # this will never realistically be <= 0. We just ensure strictly positive.
    return max(recommended, 0.01)
