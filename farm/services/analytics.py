from __future__ import annotations

from ..models import FishBatch


def projected_weight_gain_kg(feed_kg: float, feed_conversion_ratio: float) -> float:
    # ✅ FIX: Validate feed_kg — negative feed doesn't make sense
    if feed_kg <= 0 or feed_conversion_ratio <= 0:
        return 0.0
    return round(feed_kg / feed_conversion_ratio, 2)


def projected_avg_weight_g(
    batch: FishBatch,
    feed_kg: float,
    feed_conversion_ratio: float,
) -> float:
    weight_gain_kg = projected_weight_gain_kg(feed_kg, feed_conversion_ratio)

    # ✅ FIX: Early return if no weight gain — saves unnecessary DB query
    if weight_gain_kg <= 0:
        latest_growth = batch.growth_records.order_by("-date").first()
        current_avg_g = float(latest_growth.avg_weight_g) if latest_growth else float(batch.initial_avg_weight_g)
        return round(current_avg_g or 0.0, 2)

    latest_growth = batch.growth_records.order_by("-date").first()

    # ✅ FIX: Safely handle None values from nullable DB fields
    # surviving_count could be None if the field is nullable
    if latest_growth and latest_growth.surviving_count is not None:
        fish_count = latest_growth.surviving_count
    else:
        fish_count = batch.initial_count or 0

    # avg_weight_g could be None if the field is nullable
    if latest_growth and latest_growth.avg_weight_g is not None:
        current_avg_g = float(latest_growth.avg_weight_g)
    else:
        current_avg_g = float(batch.initial_avg_weight_g or 0)

    if fish_count <= 0:
        return round(current_avg_g, 2)

    gain_per_fish_g = (weight_gain_kg * 1000.0) / fish_count
    return round(current_avg_g + gain_per_fish_g, 2)
