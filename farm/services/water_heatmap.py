"""
farm/services/water_heatmap.py
=============================================================
"""
from __future__ import annotations

import logging
from collections import defaultdict
from datetime import date, timedelta
from typing import Any

from django.utils import timezone

logger = logging.getLogger(__name__)


# ── Safe ranges for color coding ─────────────────────────────────────────────

SAFE_RANGES = {
    "temp": {
        "optimal_low":  22.0, "optimal_high": 30.0,
        "warn_high":    31.0, "critical_high": 34.0,
        "warn_low":     17.0, "critical_low": 15.0,
    },
    "do": {
        "optimal_low":  6.0, "optimal_high": 9.0,
        "warn_low":     5.0, "critical_low": 4.0,
    },
    "ph": {
        "optimal_low":  7.0, "optimal_high": 8.5,
        "warn_low":     6.5, "warn_high":    9.0,
        "critical_low": 6.0, "critical_high": 9.5,
    },
}


# ── Helpers ───────────────────────────────────────────────────────────────────

def _safe_float(value, default: float = 0.0) -> float:
    if value is None: return default
    try: return float(value)
    except (ValueError, TypeError): return default


def _get_status(value: float, metric: str) -> str:
    """Return 'optimal' / 'warning' / 'critical' for a reading."""
    r = SAFE_RANGES.get(metric, {})
    if not r:
        logger.warning(f"[Heatmap] Unknown metric '{metric}', defaulting to 'optimal'")
        return "optimal"

    if metric == "temp":
        if value >= r.get("critical_high", 34) or value <= r.get("critical_low", 15): return "critical"
        if value >= r.get("warn_high", 31) or value <= r.get("warn_low", 17): return "warning"
    elif metric == "do":
        if value <= r.get("critical_low", 4): return "critical"
        if value <= r.get("warn_low", 5): return "warning"
    elif metric == "ph":
        if value <= r.get("critical_low", 6) or value >= r.get("critical_high", 9.5): return "critical"
        if value <= r.get("warn_low", 6.5) or value >= r.get("warn_high", 9): return "warning"
    return "optimal"


def _normalize(value: float, metric: str) -> float:
    """Normalize a value to 0–1 scale. 0 = optimal, 1 = most dangerous."""
    r = SAFE_RANGES.get(metric, {})

    def _safe_diff(a, b): return max(a - b, 0.001)  # ✅ User's brilliant ZeroDivision guard

    if metric == "temp":
        opt_low, opt_high = r.get("optimal_low", 22), r.get("optimal_high", 30)
        if opt_low <= value <= opt_high: return 0.0
        if value > opt_high: return min((value - opt_high) / _safe_diff(r.get("critical_high", 34), opt_high), 1.0)
        return min((opt_low - value) / _safe_diff(opt_low, r.get("critical_low", 15)), 1.0)
    
    if metric == "do":
        opt = r.get("optimal_low", 6)
        if value >= opt: return 0.0
        return min((opt - value) / _safe_diff(opt, r.get("critical_low", 4)), 1.0)
    
    if metric == "ph":
        opt_low, opt_high = r.get("optimal_low", 7), r.get("optimal_high", 8.5)
        if opt_low <= value <= opt_high: return 0.0
        if value < opt_low: return min((opt_low - value) / _safe_diff(opt_low, r.get("critical_low", 6)), 1.0)
        return min((value - opt_high) / _safe_diff(r.get("critical_high", 9.5), opt_high), 1.0)
    
    return 0.0


# ── Main heatmap builder ──────────────────────────────────────────────────────

def build_water_quality_heatmap(user=None, days: int = 7) -> dict[str, Any]:
    """Build complete heatmap dataset for the last N days across all ponds."""
    from ..models import Pond, WeatherRecord

    today = timezone.now().date()
    date_list = [today - timedelta(days=i) for i in range(days - 1, -1, -1)]
    date_labels = [d.strftime("%a %d") for d in date_list]

    pond_qs = Pond.objects.filter(owner=user) if user else Pond.objects.all()
    ponds = list(pond_qs.order_by("name"))

    if not ponds or not date_list:
        return {"no_data": True}

    # ✅ Perfect Bulk Query (No N+1)
    all_records = list(
        WeatherRecord.objects
        .filter(pond__in=ponds, timestamp__date__gte=date_list[0])
        .values("pond_id", "timestamp", "water_temp_c", "dissolved_oxygen_mg_l", "ph")
    )

    # ✅ Timezone-safe grouping
    grouped: dict[int, dict[date, list]] = defaultdict(lambda: defaultdict(list))
    for rec in all_records:
        ts = rec["timestamp"]
        d = ts.date() if hasattr(ts, 'date') else (ts if isinstance(ts, date) else None)
        if d: grouped[rec["pond_id"]][d].append(rec)

    metrics_out: dict[str, dict] = {
        "temp": {"cells": [], "safe_range": "22–30°C",   "unit": "°C",   "label": "Water Temp"},
        "do":   {"cells": [], "safe_range": "5–9 mg/L",  "unit": "mg/L", "label": "Dissolved O₂"},
        "ph":   {"cells": [], "safe_range": "6.5–9.0",   "unit": "",     "label": "pH"},
    }

    critical_count = 0
    warning_count  = 0

    # ✅ MERGE MAGIC: DRY Helper combining User's safety with my brevity
    def _build_cell(base: dict, values: list[float], metric: str) -> dict:
        nonlocal critical_count, warning_count
        if not values:
            return {**base, "value": None, "status": "no_data", "intensity": 0, "readings": 0}
        
        avg_val = sum(values) / len(values)
        status = _get_status(avg_val, metric)
        
        if status == "critical": critical_count += 1
        elif status == "warning": warning_count += 1
        
        return {
            **base,
            "value": round(avg_val, 1 if metric == "temp" else 2),
            "status": status,
            "intensity": round(_normalize(avg_val, metric), 3),
            "readings": len(values),
        }

    # Build cells
    for pond in ponds:
        temp_row, do_row, ph_row = [], [], []

        for d in date_list:
            recs = grouped[pond.id].get(d, [])
            base = {"date": d.strftime("%Y-%m-%d"), "pond": pond.name}

            if recs:
                # User's safe extraction
                t_vals = [_safe_float(r["water_temp_c"]) for r in recs if r.get("water_temp_c") is not None]
                d_vals = [_safe_float(r["dissolved_oxygen_mg_l"]) for r in recs if r.get("dissolved_oxygen_mg_l") is not None]
                p_vals = [_safe_float(r["ph"]) for r in recs if r.get("ph") is not None]
            else:
                t_vals, d_vals, p_vals = [], [], []

            # Handle total absence of data for the day
            if not recs or (not t_vals and not d_vals and not p_vals):
                empty = {**base, "value": None, "status": "no_data", "intensity": 0, "readings": 0}
                temp_row.append(empty); do_row.append(empty); ph_row.append(empty)
                continue

            # Generate cells individually (allows partial data e.g., Temp exists but pH is None)
            temp_row.append(_build_cell(base, t_vals, "temp"))
            do_row.append(_build_cell(base, d_vals, "do"))
            ph_row.append(_build_cell(base, p_vals, "ph"))

        metrics_out["temp"]["cells"].append(temp_row)
        metrics_out["do"]["cells"].append(do_row)
        metrics_out["ph"]["cells"].append(ph_row)

    # Scoring logic
    pond_scores = [
        (p.name, sum(
            3 if c["status"] == "critical" else (1 if c["status"] == "warning" else 0)
            for m in ["temp", "do", "ph"] for c in metrics_out[m]["cells"][i]
        ))
        for i, p in enumerate(ponds)
    ]
    worst_pond = max(pond_scores, key=lambda x: x[1])[0] if pond_scores else "—"

    day_scores = [0] * days
    for m in ["temp", "do", "ph"]:
        for row in metrics_out[m]["cells"]:
            for j, c in enumerate(row):
                if c["status"] == "critical": day_scores[j] += 3
                elif c["status"] == "warning": day_scores[j] += 1
    worst_day = date_labels[day_scores.index(max(day_scores))] if day_scores and date_labels else "—"

    return {
        "no_data": False,
        "dates": date_labels,
        "ponds": [p.name for p in ponds],
        "metrics": metrics_out,
        "days": days,
        "summary": {
            "worst_day": worst_day,
            "worst_pond": worst_pond,
            "critical_count": critical_count,
            "warning_count": warning_count,
            "total_ponds": len(ponds),
            "total_days": days,
        },
    }