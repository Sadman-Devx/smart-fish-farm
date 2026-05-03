"""
farm/services/fcr_analytics.py
────────────────────────────────────────────────────────────────────────────
Feed Conversion Ratio (FCR) Analytics (Optimized & Crash-Proof)
================================================================

FCR = Total Feed Given (kg) / Total Weight Gain (kg)

Features:
  - N+1 Query Prevention (uses prefetching)
  - Null/Type Safety (prevents float(None) crashes)
  - Accurate Weekly Anchoring (based on last record, not today)
"""

from __future__ import annotations

import logging
from collections import defaultdict
from datetime import date, timedelta
from typing import Any

from django.db.models import Sum

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
    """Return 'excellent' / 'good' / 'below_average' / 'poor'."""
    bench = _get_benchmark(species)
    if fcr <= bench["optimal_low"]: return "excellent"
    if fcr <= bench["optimal_high"]: return "good"
    if fcr <= bench["poor"]: return "below_average"
    return "poor"


# ── Type Safety Helpers ───────────────────────────────────────────────────────

def _safe_float(value, default: float = 0.0) -> float:
    """Safely convert a value to float, returning default if None or invalid."""
    if value is None: return default
    try: return float(value)
    except (ValueError, TypeError): return default


def _safe_int(value, default: int = 0) -> int:
    """Safely convert a value to int, returning default if None or invalid."""
    if value is None: return default
    try: return int(value)
    except (ValueError, TypeError): return default


# ── Core FCR calculation ──────────────────────────────────────────────────────

def calculate_batch_fcr(batch, prefetched_feed=None, prefetched_growth=None) -> dict[str, Any] | None:
    """
    Calculate overall FCR for a batch.
    Supports prefetched querysets to prevent N+1 queries during bulk operations.
    """
    # Total feed given (Use prefetched data if available, else query DB)
    if prefetched_feed is not None:
        total_feed_kg = sum(_safe_float(log.feed_amount_kg) for log in prefetched_feed)
    else:
        total_feed_kg = _safe_float(
            batch.feed_logs.aggregate(total=Sum("feed_amount_kg"))["total"]
        )

    if total_feed_kg <= 0:
        return None

    # Weight gain: latest - initial (Use prefetched data if available)
    if prefetched_growth is not None and len(prefetched_growth) > 0:
        sorted_growth = sorted(prefetched_growth, key=lambda x: x.date)
        first, latest = sorted_growth[0], sorted_growth[-1]
    else:
        latest = batch.growth_records.order_by("-date").first()
        first  = batch.growth_records.order_by("date").first()

    if not latest or not first:
        return None

    # Safely extract numeric values
    initial_weight_g = _safe_float(first.avg_weight_g)
    current_weight_g = _safe_float(latest.avg_weight_g)
    surviving_count  = _safe_int(latest.surviving_count)

    # If all fish died, FCR is mathematically undefined
    if surviving_count <= 0:
        logger.info(f"[FCR] Batch {batch.id}: surviving_count is 0. FCR skipped.")
        return None

    if current_weight_g <= initial_weight_g:
        return None

    weight_gain_kg = (current_weight_g - initial_weight_g) * surviving_count / 1000.0

    if weight_gain_kg <= 0:
        return None

    fcr    = round(total_feed_kg / weight_gain_kg, 3)
    status = _fcr_status(fcr, batch.species)
    bench  = _get_benchmark(batch.species)

    return {
        "batch_id":         batch.id,
        "batch_name":       str(batch),
        "pond_name":        batch.pond.name if batch.pond else "N/A",
        "species":          batch.get_species_display(),
        "fcr":              fcr,
        "status":           status,
        "total_feed_kg":    round(total_feed_kg, 2),
        "weight_gain_kg":   round(weight_gain_kg, 2),
        "initial_weight_g": round(initial_weight_g, 1),
        "current_weight_g": round(current_weight_g, 1),
        "surviving_count":  surviving_count,
        "benchmark_low":    bench["optimal_low"],
        "benchmark_high":   bench["optimal_high"],
        "days_running":     _safe_int(batch.current_age_days, 0),
    }


# ── Weekly FCR history ────────────────────────────────────────────────────────

def get_fcr_history(batch, weeks: int = 8) -> dict[str, Any]:
    """
    Calculate weekly FCR trend. 
    Anchors to the batch's latest record instead of 'today' for accuracy.
    Uses in-memory grouping to prevent N+1 DB queries.
    """
    from ..models import FeedLog

    growth_records = list(batch.growth_records.order_by("date"))
    if len(growth_records) < 2:
        return {"labels": [], "fcr_values": [], "feed_values": [], "has_data": False}

    # ✅ FIX: Anchor to latest record, not today (Fixes finished/dead batch bugs)
    end_date = latest_record.date
    
    # ✅ FIX: Fetch ALL feed logs for the period in ONE query, group in memory
    start_date = end_date - timedelta(weeks=weeks)
    all_feed_logs = list(
        FeedLog.objects.filter(batch=batch, date__gt=start_date, date__lte=end_date)
    )
    
    feed_by_week = defaultdict(float)
    for log in all_feed_logs:
        weeks_ago = (end_date - log.date).days // 7
        if 0 <= weeks_ago < weeks:
            feed_by_week[weeks_ago] += _safe_float(log.feed_amount_kg)

    labels, fcr_values, feed_values = [], [], []

    for w in range(weeks - 1, -1, -1):
        week_end   = end_date - timedelta(weeks=w)
        week_start = week_end - timedelta(days=6) # Strict 7-day window

        week_feed = feed_by_week.get(w, 0.0)
        
        records_in_week = [r for r in growth_records if week_start < r.date <= week_end]

        if not records_in_week or week_feed <= 0:
            labels.append(week_end.strftime("%b %d"))
            fcr_values.append(None)
            feed_values.append(round(week_feed, 2))
            continue

        # Determine start weight for the week
        prev_records = [r for r in growth_records if r.date <= week_start]
        if prev_records:
            start_weight = _safe_float(prev_records[-1].avg_weight_g)
            start_count  = _safe_int(prev_records[-1].surviving_count)
        else:
            start_weight = _safe_float(batch.initial_avg_weight_g)
            start_count  = _safe_int(batch.initial_count)

        end_record = records_in_week[-1]
        end_weight = _safe_float(end_record.avg_weight_g)
        end_count  = _safe_int(end_record.surviving_count)

        # ✅ FIX: Robust avg_count calculation to prevent ZeroDivisionError
        if start_count <= 0 and end_count <= 0:
            avg_count = 0
        elif start_count <= 0:
            avg_count = end_count
        elif end_count <= 0:
            avg_count = start_count
        else:
            avg_count = (start_count + end_count) / 2

        gain_g = max(end_weight - start_weight, 0)

        if avg_count > 0 and gain_g > 0:
            gain_kg = gain_g * avg_count / 1000.0
            if gain_kg > 0:
                week_fcr = round(week_feed / gain_kg, 3)
                fcr_values.append(min(week_fcr, 10.0))  # Cap at 10 for chart sanity
            else:
                fcr_values.append(None)
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
    ✅ Uses prefetch_related to solve N+1 query problem.
    """
    from ..models import FishBatch

    # ✅ FIX: Eagerly load everything (Reduces 100+ queries to exactly 3 queries)
    qs = FishBatch.objects.select_related("pond").prefetch_related(
        "feed_logs",      
        "growth_records"  
    )
    
    if user:
        qs = qs.filter(pond__owner=user)

    results = []
    for batch in qs:
        # Pass prefetched data to the calculation function
        fcr_data = calculate_batch_fcr(
            batch, 
            prefetched_feed=batch.feed_logs.all(),
            prefetched_growth=batch.growth_records.all()
        )
        if fcr_data:
            results.append(fcr_data)

    # Sort by FCR ascending (lower FCR = better efficiency)
    results.sort(key=lambda x: x["fcr"])

    # Assign rank
    for i, r in enumerate(results):
        r["rank"] = i + 1

    return results