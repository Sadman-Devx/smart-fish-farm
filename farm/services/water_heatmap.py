"""
farm/services/water_heatmap.py
────────────────────────────────────────────────────────────────────────────
Water Quality Heatmap Data Generator
======================================

Generates 7-day × pond heatmap data for:
  - Water Temperature (°C)
  - Dissolved Oxygen (mg/L)
  - pH level

Each cell = average reading for that pond on that day.
Color intensity = how far from optimal range.

Used by the analytics view to render Chart.js heatmap.
"""

from __future__ import annotations

import logging
from datetime import date, timedelta
from typing import Any

from django.utils import timezone

logger = logging.getLogger(__name__)


# ── Safe ranges for color coding ─────────────────────────────────────────────

SAFE_RANGES = {
    "temp": {
        "optimal_low":  22.0,
        "optimal_high": 30.0,
        "warn_high":    31.0,
        "critical_high": 34.0,
        "warn_low":     17.0,
        "critical_low": 15.0,
    },
    "do": {
        "optimal_low":  6.0,
        "optimal_high": 9.0,
        "warn_low":     5.0,
        "critical_low": 4.0,
    },
    "ph": {
        "optimal_low":  7.0,
        "optimal_high": 8.5,
        "warn_low":     6.5,
        "warn_high":    9.0,
        "critical_low": 6.0,
        "critical_high": 9.5,
    },
}


def _get_status(value: float, metric: str) -> str:
    """Return 'optimal' / 'warning' / 'critical' for a reading."""
    r = SAFE_RANGES.get(metric, {})

    if metric == "temp":
        if value >= r.get("critical_high", 34):
            return "critical"
        if value <= r.get("critical_low", 15):
            return "critical"
        if value >= r.get("warn_high", 31):
            return "warning"
        if value <= r.get("warn_low", 17):
            return "warning"
        return "optimal"

    if metric == "do":
        if value <= r.get("critical_low", 4):
            return "critical"
        if value <= r.get("warn_low", 5):
            return "warning"
        return "optimal"

    if metric == "ph":
        if value <= r.get("critical_low", 6) or value >= r.get("critical_high", 9.5):
            return "critical"
        if value <= r.get("warn_low", 6.5) or value >= r.get("warn_high", 9):
            return "warning"
        return "optimal"

    return "optimal"


def _normalize(value: float, metric: str) -> float:
    """
    Normalize a value to 0–1 scale for heatmap intensity.
    0 = perfectly optimal, 1 = most dangerous.
    """
    r = SAFE_RANGES.get(metric, {})

    if metric == "temp":
        opt_low  = r.get("optimal_low", 22)
        opt_high = r.get("optimal_high", 30)
        crit_h   = r.get("critical_high", 34)
        crit_l   = r.get("critical_low", 15)
        if opt_low <= value <= opt_high:
            return 0.0
        if value > opt_high:
            return min((value - opt_high) / (crit_h - opt_high), 1.0)
        return min((opt_low - value) / (opt_low - crit_l), 1.0)

    if metric == "do":
        opt = r.get("optimal_low", 6)
        crit = r.get("critical_low", 4)
        if value >= opt:
            return 0.0
        return min((opt - value) / (opt - crit), 1.0)

    if metric == "ph":
        opt_low  = r.get("optimal_low", 7)
        opt_high = r.get("optimal_high", 8.5)
        if opt_low <= value <= opt_high:
            return 0.0
        if value < opt_low:
            crit = r.get("critical_low", 6)
            return min((opt_low - value) / (opt_low - crit), 1.0)
        crit = r.get("critical_high", 9.5)
        return min((value - opt_high) / (crit - opt_high), 1.0)

    return 0.0


# ── Main heatmap builder ──────────────────────────────────────────────────────

def build_water_quality_heatmap(user=None, days: int = 7) -> dict[str, Any]:
    """
    Build complete heatmap dataset for the last N days across all ponds.

    Returns a dict ready to be passed to the template / Chart.js.

    Structure:
    {
        "dates":  ["Mon 01", "Tue 02", ...],          # X-axis
        "ponds":  ["Pond A", "Pond B", ...],           # Y-axis
        "metrics": {
            "temp": {
                "cells": [                             # rows=ponds, cols=dates
                    [{"value": 28.5, "status": "optimal", "intensity": 0.1}, ...],
                    ...
                ],
                "safe_range": "22–30°C",
            },
            "do":   { "cells": [...], "safe_range": "5–9 mg/L" },
            "ph":   { "cells": [...], "safe_range": "6.5–9.0" },
        },
        "summary": {
            "worst_day":   "Mon 01",
            "worst_pond":  "Pond A",
            "critical_count": 3,
            "warning_count":  7,
        }
    }
    """
    from ..models import Pond, WeatherRecord
    from django.db.models import Avg

    # Date range
    today     = timezone.now().date()
    date_list = [today - timedelta(days=i) for i in range(days - 1, -1, -1)]
    date_labels = [d.strftime("%a %d") for d in date_list]

    # Ponds
    pond_qs = Pond.objects.filter(owner=user) if user else Pond.objects.all()
    ponds   = list(pond_qs.order_by("name"))

    if not ponds or not date_list:
        return {"no_data": True}

    pond_names = [p.name for p in ponds]

    # Pre-fetch all readings for the date range
    since = timezone.now() - timedelta(days=days + 1)
    all_records = (
        WeatherRecord.objects
        .filter(pond__in=ponds, timestamp__date__gte=date_list[0])
        .values("pond_id", "timestamp", "water_temp_c",
                "dissolved_oxygen_mg_l", "ph")
    )

    # Group by pond_id → date → list of readings
    from collections import defaultdict
    grouped: dict[int, dict[date, list]] = defaultdict(lambda: defaultdict(list))
    for rec in all_records:
        d = rec["timestamp"].date() if hasattr(rec["timestamp"], "date") else rec["timestamp"]
        grouped[rec["pond_id"]][d].append(rec)

    # Build cells for each metric
    metrics_out: dict[str, dict] = {
        "temp": {"cells": [], "safe_range": "22–30°C",   "unit": "°C",    "label": "Water Temp"},
        "do":   {"cells": [], "safe_range": "5–9 mg/L",  "unit": "mg/L",  "label": "Dissolved O₂"},
        "ph":   {"cells": [], "safe_range": "6.5–9.0",   "unit": "",      "label": "pH"},
    }

    critical_count = 0
    warning_count  = 0
    worst_cells: list[dict] = []

    for pond in ponds:
        temp_row = []
        do_row   = []
        ph_row   = []

        for d in date_list:
            recs = grouped[pond.id].get(d, [])

            if recs:
                avg_temp = sum(float(r["water_temp_c"]) for r in recs) / len(recs)
                avg_do   = sum(float(r["dissolved_oxygen_mg_l"]) for r in recs) / len(recs)
                avg_ph   = sum(float(r["ph"]) for r in recs) / len(recs)

                temp_status = _get_status(avg_temp, "temp")
                do_status   = _get_status(avg_do,   "do")
                ph_status   = _get_status(avg_ph,   "ph")

                for st in [temp_status, do_status, ph_status]:
                    if st == "critical":
                        critical_count += 1
                    elif st == "warning":
                        warning_count += 1

                temp_row.append({
                    "value":     round(avg_temp, 1),
                    "status":    temp_status,
                    "intensity": round(_normalize(avg_temp, "temp"), 3),
                    "date":      d.strftime("%Y-%m-%d"),
                    "pond":      pond.name,
                    "readings":  len(recs),
                })
                do_row.append({
                    "value":     round(avg_do, 2),
                    "status":    do_status,
                    "intensity": round(_normalize(avg_do, "do"), 3),
                    "date":      d.strftime("%Y-%m-%d"),
                    "pond":      pond.name,
                    "readings":  len(recs),
                })
                ph_row.append({
                    "value":     round(avg_ph, 2),
                    "status":    ph_status,
                    "intensity": round(_normalize(avg_ph, "ph"), 3),
                    "date":      d.strftime("%Y-%m-%d"),
                    "pond":      pond.name,
                    "readings":  len(recs),
                })
            else:
                # No data for this pond/day
                empty = {
                    "value": None, "status": "no_data",
                    "intensity": 0, "date": d.strftime("%Y-%m-%d"),
                    "pond": pond.name, "readings": 0,
                }
                temp_row.append(empty)
                do_row.append(empty)
                ph_row.append(empty)

        metrics_out["temp"]["cells"].append(temp_row)
        metrics_out["do"]["cells"].append(do_row)
        metrics_out["ph"]["cells"].append(ph_row)

    # Find worst pond (most critical + warning cells)
    pond_scores = []
    for i, pond in enumerate(ponds):
        score = 0
        for metric in ["temp", "do", "ph"]:
            for cell in metrics_out[metric]["cells"][i]:
                if cell["status"] == "critical":
                    score += 3
                elif cell["status"] == "warning":
                    score += 1
        pond_scores.append((pond.name, score))
    worst_pond = max(pond_scores, key=lambda x: x[1])[0] if pond_scores else "—"

    # Find worst day
    day_scores = [0] * days
    for metric in ["temp", "do", "ph"]:
        for pond_row in metrics_out[metric]["cells"]:
            for j, cell in enumerate(pond_row):
                if cell["status"] == "critical":
                    day_scores[j] += 3
                elif cell["status"] == "warning":
                    day_scores[j] += 1
    worst_day_idx = day_scores.index(max(day_scores)) if day_scores else 0
    worst_day     = date_labels[worst_day_idx] if date_labels else "—"

    return {
        "no_data":       False,
        "dates":         date_labels,
        "ponds":         pond_names,
        "metrics":       metrics_out,
        "days":          days,
        "summary": {
            "worst_day":      worst_day,
            "worst_pond":     worst_pond,
            "critical_count": critical_count,
            "warning_count":  warning_count,
            "total_ponds":    len(ponds),
            "total_days":     days,
        },
    }