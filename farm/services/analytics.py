from __future__ import annotations

from ..models import FishBatch


def projected_weight_gain_kg(feed_kg: float, feed_conversion_ratio: float) -> float:
    if feed_conversion_ratio <= 0:
        return 0.0
    return round(feed_kg / feed_conversion_ratio, 2)


def projected_avg_weight_g(
    batch: FishBatch,
    feed_kg: float,
    feed_conversion_ratio: float,
) -> float:
    weight_gain_kg = projected_weight_gain_kg(feed_kg, feed_conversion_ratio)
    latest_growth = batch.growth_records.order_by("-date").first()
    fish_count = latest_growth.surviving_count if latest_growth else batch.initial_count
    current_avg_g = float(latest_growth.avg_weight_g) if latest_growth else float(batch.initial_avg_weight_g)
    if fish_count <= 0:
        return round(current_avg_g, 2)
    gain_per_fish_g = (weight_gain_kg * 1000.0) / fish_count
    return round(current_avg_g + gain_per_fish_g, 2)

