"""
farm/services/feed_calculator.py
─────────────────────────────────────────────────────────────────────────────
Smart feed calculator (Optimized & Crash-Proof)
================================================

GUARANTEED BEHAVIOUR
────────────────────
Always returns a positive float as long as the batch has fish AND 
a FeedingProfile exists in the database.
Returns None ONLY when:
  1. biomass is zero/negative/None (all fish dead), OR
  2. NO FeedingProfile is configured in the system.

Temperature resolution (highest priority first)
───────────────────────────────────────────────
  1. Latest WeatherRecord for the pond  (actual sensor / manual entry)
  2. DailyWeather for the exact day     (DB Cache)
  3. Most-recent DailyWeather in DB     (fallback for historical dates)
  4. Hard default: 26°C                 (absolute last resort)

Feed formula
────────────
    feed_kg = biomass_kg × feeding_rate_pct(water_temp) / 100
                          × temperature_factor(ambient_temp)
                          × size_factor(current_avg_weight_g)

The size_factor was added after a literature-benchmarked simulation
(research/feed_recommendation_eval/) showed the temperature-only formula
over-feeds fish once they grow past ~150g (implied FCR ~2.6 vs. a
literature range of 1.2-2.0). See _size_factor() docstring for details.
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

DEFAULT_FEED_RATE_PCT: float = 3.0   # fallback when NO profiles match the temp
DEFAULT_TEMP_C: float        = 26.0  # fallback when no weather data at all

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


def _get_cached_profile_rate(water_temp: float) -> float | None:
    """
    Fetch feeding rate from cache/DB.
    Prevents N+1 queries when calculating feed for multiple batches on dashboard.
    
    Returns None ONLY if there are absolutely no FeedingProfiles in the database.
    Returns DEFAULT_FEED_RATE_PCT if profiles exist but none match the temperature.
    """
    profiles = cache.get(_PROFILE_CACHE_KEY)
    
    if profiles is None:
        profiles = list(FeedingProfile.objects.all())
        cache.set(_PROFILE_CACHE_KEY, profiles, timeout=_PROFILE_CACHE_TIMEOUT)
    
    # ✅ CRITICAL FIX: If the database has NO profiles at all, return None
    if not profiles:
        return None
    
    # Find matching profile in memory (fast, since list is tiny)
    matching = [
        p for p in profiles 
        if _safe_float(p.min_temp_c) <= water_temp <= _safe_float(p.max_temp_c)
    ]
    
    if matching:
        # Return the tightest fitting profile's rate
        return _safe_float(matching[0].feeding_rate_pct, DEFAULT_FEED_RATE_PCT)
        
    # Profiles exist, but none match this specific water_temp. Use safe default.
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


def _size_factor(avg_weight_g: float) -> float:
    """
    Fish-size multiplier applied on top of the temperature-based feeding rate.

    WHY: The FeedingProfile rates (1.5-4.0%) are calibrated for typical
    grow-out size fish (~50-150g). Aquaculture feeding-rate guidance
    indicates smaller/younger fish need a much higher feed rate as a
    percentage of body weight (higher metabolism, faster growth), while
    fish approaching harvest size need a much lower percentage (slower
    growth, lower metabolic demand). Without this adjustment, a batch
    kept at a constant temperature-based rate for its whole grow-out
    cycle gets over-fed once it grows past ~150g — this was confirmed via
    literature-benchmarked simulation (see research/feed_recommendation_eval).

    Bands (multiplier on top of the temperature-based rate):
      < 5g     → 3.75   (fry — very high metabolism)
      5-20g    → 2.0    (fingerling)
      20-50g   → 1.25   (juvenile)
      50-150g  → 1.0    (baseline grow-out — FeedingProfile rates calibrated here)
      150-300g → 0.5    (approaching harvest)
      > 300g   → 0.3    (near/at harvest size)

    NOTE: these multipliers are an engineering approximation calibrated
    against general aquaculture feeding-rate guidance (not a single
    peer-reviewed table specific to one species/system) — reasonable for
    this application, but worth refining further with real farm data.
    """
    w = _safe_float(avg_weight_g)
    if w <= 0:
        return 1.0  # unknown weight — don't distort the recommendation
    if w < 5:
        return 3.75
    if w < 20:
        return 2.0
    if w < 50:
        return 1.25
    if w < 150:
        return 1.0
    if w < 300:
        return 0.5
    return 0.3


# ── স্তর ১: Auto-Generate Feeding Profiles ───────────────────────────────────

def ensure_default_feeding_profiles() -> None:
    """
    ডাটাবেসে কোনো FeedingProfile না থাকলে, 
    বাংলাদেশের মৎস্যচাষের জন্য standard profiles অটো তৈরি করুন।
    """
    if FeedingProfile.objects.exists():
        return  # ইতিমধ্যে আছে, কিছু করার দরকার নেই

    default_profiles = [
        {
            "name": "🥶 শীতকালীন (18-22°C)",
            "min_temp_c": 18.0,
            "max_temp_c": 22.0,
            "feeding_rate_pct": 1.5,
        },
        {
            "name": "🌤️ মৌসুমী (22-26°C)",
            "min_temp_c": 22.0,
            "max_temp_c": 26.0,
            "feeding_rate_pct": 3.0,
        },
        {
            "name": "☀️ আদর্শ (26-30°C)",
            "min_temp_c": 26.0,
            "max_temp_c": 30.0,
            "feeding_rate_pct": 4.0,
        },
        {
            "name": "🔥 গরমকালীন (30-34°C)",
            "min_temp_c": 30.0,
            "max_temp_c": 34.0,
            "feeding_rate_pct": 3.0,
        },
        {
            "name": "🌡️ অতিরিক্ত গরম (34-38°C)",
            "min_temp_c": 34.0,
            "max_temp_c": 38.0,
            "feeding_rate_pct": 2.0,
        },
    ]

    created = FeedingProfile.objects.bulk_create([
        FeedingProfile(**p) for p in default_profiles
    ])
    
    logger.info(
        f"[FeedCalc] ✅ Auto-generated {len(created)} default FeedingProfiles "
        f"(System had no profiles configured)"
    )
    
    # Cache invalidate করুন যাতে নতুন ডাটা পড়ে
    cache.delete(_PROFILE_CACHE_KEY)


# ── Main service function ─────────────────────────────────────────────────────

def smart_feed_kg_for_batch(
    batch: FishBatch,
    day: date | None = None,
    try_live_api: bool = False,
) -> Optional[float]:
    """
    Return the recommended daily feed (kg) for *batch* on *day*.
    """
    target_day = day or timezone.now().date()

    # ── Step 0: Guard clauses ─────────────────────────────────────────────────
    
    biomass_kg = _safe_float(batch.latest_biomass_kg)
    
    # ✅ স্তর ২: AUTO-FIX (নতুন batch হলে biomass calculate)
    if biomass_kg <= 0:
        initial_count = _safe_float(batch.initial_count)
        avg_weight_g = _safe_float(batch.initial_avg_weight_g)
        
        if initial_count > 0 and avg_weight_g > 0:
            biomass_kg = (initial_count * avg_weight_g) / 1000.0
            try:
                batch.latest_biomass_kg = biomass_kg
                batch.save(update_fields=['latest_biomass_kg'])
                logger.info(f"[FeedCalc] Auto-calculated biomass for batch {batch.id}: {biomass_kg}kg")
            except Exception:
                pass

    if biomass_kg <= 0:
        return None

    # Current average fish weight, for the size-based feeding adjustment below.
    # Same fallback pattern used in ml_prediction.py: latest GrowthRecord,
    # falling back to the batch's stocking weight if no growth history yet.
    latest_growth = batch.growth_records.order_by("-date").first()
    current_avg_weight_g = (
        _safe_float(latest_growth.avg_weight_g)
        if latest_growth and latest_growth.avg_weight_g is not None
        else _safe_float(getattr(batch, "initial_avg_weight_g", None))
    )

    # ── Step 1: resolve water & ambient temperature safely ────────────────────

    water_temp = 0.0
    ambient_temp = 0.0

    # Priority A — Pond Sensor (Most accurate)
    if batch.pond is not None:
        pond_record = (
            WeatherRecord.objects
            .filter(pond=batch.pond)
            .order_by("-timestamp")
            .first()
        )
        if pond_record is not None:
            water_temp = _safe_float(pond_record.water_temp_c)

    # Priority B — Daily Weather from DB
    daily_weather = DailyWeather.objects.filter(date=target_day).first()
    
    # Priority C — Live API fetch (ONLY if explicitly requested)
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
        
        if dw_temp > 0:
            ambient_temp = dw_temp
            
        if water_temp == 0.0 and dw_temp > 0:
            water_temp = dw_temp

    # Priority E — Absolute hardcoded fallback
    if water_temp == 0.0:
        water_temp = DEFAULT_TEMP_C
    if ambient_temp == 0.0:
        ambient_temp = DEFAULT_TEMP_C

    # ── Step 2: ✅ স্তর ২: AUTO-GENERATE Profiles যদি না থাকে ────────────────
    
    ensure_default_feeding_profiles()  # ← এই এক লাইনেই সব হবে!
    
    feed_rate_pct = _get_cached_profile_rate(water_temp)

    # ✅ CRITICAL FIX: If no FeedingProfile exists in DB, return None immediately
    if feed_rate_pct is None:
        return None

    # ── Step 3: calculate ─────────────────────────────────────────────────────
    
    base_feed    = biomass_kg * feed_rate_pct / 100.0
    temp_factor  = _temperature_factor(ambient_temp)
    size_factor  = _size_factor(current_avg_weight_g)
    recommended  = round(base_feed * temp_factor * size_factor, 2)

    # Since factor is mathematically always >= 0.10 and biomass > 0, 
    # this will never realistically be <= 0. We just ensure strictly positive.
    return max(recommended, 0.01)