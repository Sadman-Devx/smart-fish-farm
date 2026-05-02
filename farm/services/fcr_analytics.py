"""
farm/services/fcr_analytics.py
────────────────────────────────────────────────────────────────────────────
Feed Conversion Ratio (FCR) Analytics
=======================================

FCR = Total Feed Given (kg) / Total Weight Gain (kg)

Lower FCR = more efficient feeding.
  Tilapia optimal FCR: 1.2 – 1.8
  Catfish optimal FCR: 1.5 – 2.0
  Carp optimal FCR:    1.8 – 2.5

Functions:
  calculate_batch_fcr(batch)         → FCR for a specific batch
  calculate_all_batches_fcr(user)    → FCR comparison across all batches
  get_fcr_history(batch, weeks)      → Weekly FCR trend for a batch
  get_feed_efficiency_ranking(user)  → Ranked list: best → worst FCR
"""

from __future__ import annotations

import logging
from datetime import date, timedelta
from typing import Any

logger = logging.getLogger(__name__)


# ── Species FCR benchmarks (from aquaculture literature) ─────────────────────

FCR_BENCHMARKS: dict[str, dict[str, float]] = {
    "tilapia": {"optimal_low": 1.2, "optimal_high": 1.8, "poor": 2.5},
    "catfish": {"optimal_low": 1.5, "optimal_high": 2.0, "poor": 2.8},
    "carp":    {"optimal_low": 1.8, "optimal_high": 2.5, "poor": 3.5},
    "other":   {"optimal_low": 1.5, "optimal_high": 2.2, "poor": 3.0},
}


def _get_benchmark(species: str) -> dict[str, float]:
    return FCR_BENCHMARKS.get(species, FCR_BENCHMARKS["other"])


def _fcr_status(fcr: float, species: str) -> str:
    """Return 'excellent' / 'good' / 'poor' based on species benchmarks."""
    bench = _get_benchmark(species)
    if fcr <= bench["optimal_low"]:
        return "excellent"
    if fcr <= bench["optimal_high"]:
        return "good"
    if fcr <= bench["poor"]:
        return "below_average"
    return "poor"


# ── Core FCR calculation ──────────────────────────────────────────────────────

def calculate_batch_fcr(batch) -> dict[str, Any] | None:
    """
    Calculate overall FCR for a batch from all its records.

    Returns None if insufficient data.
    """
    from django.db.models import Sum
    from ..models import FeedLog, GrowthRecord

    # Total feed given
    total_feed_kg = float(
        FeedLog.objects
        .filter(batch=batch)
        .aggregate(total=Sum("feed_amount_kg"))["total"] or 0
    )

    if total_feed_kg <= 0:
        return None

    # Weight gain: latest growth record weight - initial weight
    latest = batch.growth_records.order_by("-date").first()
    first  = batch.growth_records.order_by("date").first()

    if not latest or not first:
        return None

    initial_weight_g  = float(first.avg_weight_g)
    current_weight_g  = float(latest.avg_weight_g)
    surviving_count   = latest.surviving_count

    if current_weight_g <= initial_weight_g:
        return None

    weight_gain_kg = (current_weight_g - initial_weight_g) * surviving_count / 1000.0

    if weight_gain_kg <= 0:
        return None

    fcr    = round(total_feed_kg / weight_gain_kg, 3)
    status = _fcr_status(fcr, batch.species)
    bench  = _get_benchmark(batch.species)

    return {
        "batch_id":        batch.id,
        "batch_name":      str(batch),
        "pond_name":       batch.pond.name,
        "species":         batch.get_species_display(),
        "fcr":             fcr,
        "status":          status,
        "total_feed_kg":   round(total_feed_kg, 2),
        "weight_gain_kg":  round(weight_gain_kg, 2),
        "initial_weight_g": round(initial_weight_g, 1),
        "current_weight_g": round(current_weight_g, 1),
        "surviving_count": surviving_count,
        "benchmark_low":   bench["optimal_low"],
        "benchmark_high":  bench["optimal_high"],
        "days_running":    batch.current_age_days,
    }


# ── Weekly FCR history ────────────────────────────────────────────────────────

def get_fcr_history(batch, weeks: int = 8) -> dict[str, Any]:
    """
    Calculate weekly FCR trend for a batch.
    Shows how feed efficiency changed week by week.
    """
    from django.db.models import Sum
    from ..models import FeedLog, GrowthRecord

    labels      : list[str]   = []
    fcr_values  : list[float] = []
    feed_values : list[float] = []

    growth_records = list(batch.growth_records.order_by("date"))
    if len(growth_records) < 2:
        return {"labels": [], "fcr_values": [], "feed_values": [], "has_data": False}

    today = date.today()

    for w in range(weeks - 1, -1, -1):
        week_end   = today - timedelta(weeks=w)
        week_start = week_end - timedelta(weeks=1)

        # Feed this week
        week_feed = float(
            FeedLog.objects
            .filter(batch=batch, date__gt=week_start, date__lte=week_end)
            .aggregate(total=Sum("feed_amount_kg"))["total"] or 0
        )

        # Growth records in this window
        records_in_week = [
            r for r in growth_records
            if week_start <= r.date <= week_end
        ]

        if not records_in_week or week_feed <= 0:
            labels.append(week_end.strftime("%b %d"))
            fcr_values.append(None)
            feed_values.append(round(week_feed, 2))
            continue

        # Weight gain this week
        prev_records = [r for r in growth_records if r.date <= week_start]
        if prev_records:
            start_weight = float(prev_records[-1].avg_weight_g)
            start_count  = prev_records[-1].surviving_count
        else:
            start_weight = float(batch.initial_avg_weight_g)
            start_count  = batch.initial_count

        end_record   = records_in_week[-1]
        end_weight   = float(end_record.avg_weight_g)
        end_count    = end_record.surviving_count

        avg_count    = (start_count + end_count) / 2
        gain_g       = max(end_weight - start_weight, 0)
        gain_kg      = gain_g * avg_count / 1000.0

        if gain_kg > 0:
            week_fcr = round(week_feed / gain_kg, 3)
            fcr_values.append(min(week_fcr, 10.0))  # cap at 10 for chart sanity
        else:
            fcr_values.append(None)

        labels.append(week_end.strftime("%b %d"))
        feed_values.append(round(week_feed, 2))

    bench = _get_benchmark(batch.species)

    return {
        "labels":          labels,
        "fcr_values":      fcr_values,
        "feed_values":     feed_values,
        "benchmark_low":   bench["optimal_low"],
        "benchmark_high":  bench["optimal_high"],
        "has_data":        any(v is not None for v in fcr_values),
        "species":         batch.get_species_display(),
    }


# ── All-batches FCR comparison ────────────────────────────────────────────────

def get_feed_efficiency_ranking(user=None) -> list[dict[str, Any]]:
    """
    Calculate FCR for all batches and rank them best → worst.
    Used by the analytics dashboard for comparison table.
    """
    from ..models import FishBatch

    qs = FishBatch.objects.select_related("pond")
    if user:
        qs = qs.filter(pond__owner=user)

    results = []
    for batch in qs:
        fcr_data = calculate_batch_fcr(batch)
        if fcr_data:
            results.append(fcr_data)

    # Sort by FCR ascending (lower = better)
    results.sort(key=lambda x: x["fcr"])

    # Add rank
    for i, r in enumerate(results):
        r["rank"] = i + 1

    return results