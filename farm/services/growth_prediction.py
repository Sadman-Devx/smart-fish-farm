from __future__ import annotations

import math
from datetime import timedelta
from typing import Any

from django.conf import settings
from django.utils import timezone

from ..models import FishBatch, WeatherRecord
from .feed_calculator import smart_feed_kg_for_batch


def _temperature_growth_efficiency(temp_c: float) -> float:
    if temp_c < 18:
        return 0.40
    if temp_c < 22:
        return 0.70
    if temp_c < 26:
        return 0.90
    if temp_c <= 30:
        return 1.00
    return 0.95


def _species_fcr_factor(species: str) -> float:
    factors = {
        "tilapia": 0.95,
        "catfish": 1.00,
        "carp": 1.05,
        "other": 1.10,
    }
    return factors.get(species, 1.10)


def predict_batch_growth(batch: FishBatch, feed_kg: float | None = None) -> dict[str, Any]:
    latest_growth = batch.growth_records.order_by("-date").first()
    current_avg_weight_g = (
        float(latest_growth.avg_weight_g) if latest_growth else float(batch.initial_avg_weight_g)
    )
    fish_count = latest_growth.surviving_count if latest_growth else batch.initial_count
    fish_count = max(fish_count, 1)

    if feed_kg is None:
        latest_feed = batch.feed_logs.order_by("-date").first()
        feed_kg = float(latest_feed.feed_amount_kg) if latest_feed else (smart_feed_kg_for_batch(batch) or 0.0)

    latest_weather = WeatherRecord.objects.filter(pond=batch.pond).order_by("-timestamp").first()
    water_temp_c = float(latest_weather.water_temp_c) if latest_weather else 26.0

    base_fcr = float(getattr(settings, "DEFAULT_FCR", 1.5))
    species_factor = _species_fcr_factor(batch.species)
    temp_efficiency = _temperature_growth_efficiency(water_temp_c)
    effective_fcr = max(0.3, base_fcr * species_factor / max(temp_efficiency, 0.3))

    weight_gain_kg = (feed_kg / effective_fcr) if feed_kg > 0 else 0.0
    gain_per_fish_g = (weight_gain_kg * 1000.0) / fish_count
    predicted_next_avg_weight_g = current_avg_weight_g + gain_per_fish_g

    growth_records = list(batch.growth_records.order_by("date"))
    trend_daily_g = 0.0
    if len(growth_records) >= 2:
        first = growth_records[0]
        last = growth_records[-1]
        days = max((last.date - first.date).days, 1)
        trend_daily_g = max((float(last.avg_weight_g) - float(first.avg_weight_g)) / days, 0.0)

    predicted_daily_gain_g = gain_per_fish_g if trend_daily_g <= 0 else (gain_per_fish_g + trend_daily_g) / 2.0
    predicted_daily_gain_g = max(predicted_daily_gain_g, 0.1)

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

