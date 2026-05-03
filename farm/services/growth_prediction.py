"""
farm/services/growth_prediction.py 
=============================================================
"""
from __future__ import annotations

import math
from datetime import timedelta
from typing import Any

from django.conf import settings
from django.utils import timezone

from ..models import FishBatch, WeatherRecord


# ── Helpers ───────────────────────────────────────────────────────────────────

def _safe_float(value, default: float = 0.0) -> float:
    """Safely convert to float; returns *default* on None / bad value."""
    if value is None: return default
    try: return float(value)
    except (ValueError, TypeError): return default


def _safe_int(value, default: int = 0) -> int:
    """Safely convert to int; returns *default* on None / bad value."""
    if value is None: return default
    try: return int(value)
    except (ValueError, TypeError): return default


def _temperature_growth_efficiency(temp_c: float) -> float:
    if temp_c < 18: return 0.40
    if temp_c < 22: return 0.70
    if temp_c < 26: return 0.90
    if temp_c <= 30: return 1.00
    return 0.95


def _species_fcr_factor(species: str) -> float:
    factors = {
        "tilapia": 0.95,
        "catfish": 1.00,
        "carp": 1.05,
        "other": 1.10,
    }
    return factors.get(species, 1.10)


# ── Main prediction function ─────────────────────────────────────────────────

def predict_batch_growth(
    batch: FishBatch, 
    feed_kg: float | None = None,
    current_water_temp: float | None = None  # ✅ FIX: Pass temp to avoid N+1 DB queries in loops
) -> dict[str, Any]:
    """
    Predict next weight and days to market.
    """
    # ── Step 1: Base metrics (DRY Safe extraction) ────────────────────────────
    
    latest_growth = batch.growth_records.order_by("-date").first()
    
    # Uses _safe_float to handle None natively
    current_avg_weight_g = (
        _safe_float(latest_growth.avg_weight_g) 
        if latest_growth 
        else _safe_float(batch.initial_avg_weight_g)
    )
    
    fish_count = (
        _safe_int(latest_growth.surviving_count) 
        if latest_growth 
        else _safe_int(batch.initial_count)
    )
    fish_count = max(fish_count, 1)

    # ── Step 2: Feed amount resolution ────────────────────────────────────────
    
    if feed_kg is None:
        latest_feed = batch.feed_logs.order_by("-date").first()
        feed_kg = _safe_float(latest_feed.feed_amount_kg) if latest_feed else 0.0
        
        # Fallback to calculator ONLY if no historical feed exists
        if feed_kg <= 0:
            # ✅ FIX: Local import prevents circular import & speeds up module load
            from .feed_calculator import smart_feed_kg_for_batch
            feed_kg = smart_feed_kg_for_batch(batch) or 0.0

    # ── Step 3: Temperature resolution ────────────────────────────────────────
    
    if current_water_temp is not None:
        water_temp_c = current_water_temp
    elif batch.pond is not None:  # Guard against missing pond
        latest_weather = WeatherRecord.objects.filter(pond=batch.pond).order_by("-timestamp").first()
        water_temp_c = _safe_float(latest_weather.water_temp_c, 26.0) if latest_weather else 26.0
    else:
        water_temp_c = 26.0

    # ── Step 4: FCR & Growth Math ─────────────────────────────────────────────
    
    base_fcr = float(getattr(settings, "DEFAULT_FCR", 1.5))
    
    # ✅ User's clean inline fallback for species
    species_factor = _species_fcr_factor(batch.species or "other") 
    
    temp_efficiency = _temperature_growth_efficiency(water_temp_c)
    
    # Protect against division by zero / crazy high FCR
    effective_fcr = max(0.3, base_fcr * species_factor / max(temp_efficiency, 0.3))

    weight_gain_kg = (feed_kg / effective_fcr) if feed_kg > 0 else 0.0
    gain_per_fish_g = (weight_gain_kg * 1000.0) / fish_count
    predicted_next_avg_weight_g = current_avg_weight_g + gain_per_fish_g

    # ── Step 5: Trend Smoothing ───────────────────────────────────────────────
    
    growth_records = list(batch.growth_records.order_by("date"))
    trend_daily_g = 0.0
    
    if len(growth_records) >= 2:
        first_rec, last_rec = growth_records[0], growth_records[-1]
        days = max((last_rec.date - first_rec.date).days, 1)
        # Safe float subtraction for trend
        trend_daily_g = max(
            (_safe_float(last_rec.avg_weight_g) - _safe_float(first_rec.avg_weight_g)) / days, 
            0.0
        )

    # Blend calculated gain with historical trend
    predicted_daily_gain_g = gain_per_fish_g if trend_daily_g <= 0 else (gain_per_fish_g + trend_daily_g) / 2.0
    predicted_daily_gain_g = max(predicted_daily_gain_g, 0.1)

    # ── Step 6: Days to Market ────────────────────────────────────────────────
    
    market_weight_g = float(getattr(settings, "DEFAULT_MARKET_WEIGHT_G", 500.0))
    remaining_g = max(market_weight_g - current_avg_weight_g, 0.0)
    days_to_market = 0 if remaining_g == 0 else int(math.ceil(remaining_g / predicted_daily_gain_g))
    harvest_date = timezone.now().date() + timedelta(days=days_to_market)

    return {
        "current_avg_weight_g": round(current_avg_weight_g, 2),
        "predicted_next_avg_weight_g": round(predicted_next_avg_weight_g, 2),
        "predicted_weight_gain_kg": round(weight_gain_kg, 2),
        "predicted_daily_gain_g": round(predicted_daily_gain_g, 2),
        "effective_fcr": round(effective_fcr, 2),
        "water_temp_c": round(water_temp_c, 1),
        "estimated_days_to_market": days_to_market,
        "estimated_harvest_date": harvest_date,
        "target_market_weight_g": round(market_weight_g, 2),
    }