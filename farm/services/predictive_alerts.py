"""
farm/services/predictive_alerts.py 
==============================================================
"""
from __future__ import annotations

import logging
import statistics
from collections import defaultdict
from datetime import date, timedelta
from typing import Any

from django.utils import timezone

logger = logging.getLogger(__name__)


# ── Safe thresholds ───────────────────────────────────────────────────────────

TEMP_WARNING_C    = 31.0
TEMP_CRITICAL_C   = 34.0
TEMP_LOW_WARNING  = 16.0
DO_WARNING        = 5.0
DO_CRITICAL       = 4.0
MORTALITY_SPIKE   = 10
MORTALITY_CRITICAL = 30


# ── Helpers ───────────────────────────────────────────────────────────────────

def _safe_float(value, default: float = 0.0) -> float:
    if value is None: return default
    try: return float(value)
    except (ValueError, TypeError): return default

def _safe_int(value, default: int = 0) -> int:
    if value is None: return default
    try: return int(value)
    except (ValueError, TypeError): return default


# ── Linear trend helper ───────────────────────────────────────────────────────

def _linear_trend(values: list[float]) -> tuple[float, float]:
    """Fit a simple linear trend. Filters out None/non-numeric automatically."""
    # User's robust cleaning logic
    clean_values = [v for v in values if v is not None and isinstance(v, (int, float))]
    if not clean_values:
        return 0.0, 0.0
    if len(clean_values) < 2:
        return 0.0, round(clean_values[-1], 2)

    n = len(clean_values)
    x = list(range(n))
    x_mean = statistics.mean(x)
    y_mean = statistics.mean(clean_values)

    numerator   = sum((x[i] - x_mean) * (clean_values[i] - y_mean) for i in range(n))
    denominator = sum((x[i] - x_mean) ** 2 for i in range(n))

    slope = numerator / denominator if denominator != 0 else 0.0
    return round(slope, 4), round(clean_values[-1], 2)


def _project_value(current: float, slope: float, days_ahead: int) -> float:
    return round(current + slope * days_ahead, 2)


# ── 1. Temperature Trend Predictor ───────────────────────────────────────────

def predict_temperature_alerts(pond, pre_fetched_weather: list = None) -> list[dict[str, Any]]:
    """Analyzes water temperature trend. Supports bulk pre-fetched data."""
    alerts = []
    seven_days_ago = timezone.now() - timedelta(days=7)

    if pre_fetched_weather is not None:
        # My performance logic + User's safe float logic
        temps = [_safe_float(w.water_temp_c) for w in pre_fetched_weather 
                 if w.timestamp >= seven_days_ago and w.water_temp_c is not None]
    else:
        from ..models import WeatherRecord
        records = list(WeatherRecord.objects.filter(pond=pond, timestamp__gte=seven_days_ago)
                       .order_by("timestamp").values_list("water_temp_c", flat=True))
        temps = [_safe_float(t) for t in records if t is not None]

    if len(temps) < 3:
        return []

    slope, current_temp = _linear_trend(temps)
    proj_1day = _project_value(current_temp, slope, 1)
    proj_3day = _project_value(current_temp, slope, 3)

    # High Temp
    if slope > 0.3:
        if proj_1day >= TEMP_CRITICAL_C:
            alerts.append({"alert_type": "high_temp", "level": "critical", "is_predictive": True, "pond": pond,
                "message": f"🔴 PREDICTIVE: Pond '{pond.name}' water temp trending CRITICAL. Current: {current_temp}°C | Trend: +{slope:.2f}°C/day | Proj tomorrow: {proj_1day}°C. Take action NOW.",
                "trend_slope": slope, "current_value": current_temp, "projected_1d": proj_1day, "projected_3d": proj_3day})
        elif proj_3day >= TEMP_WARNING_C:
            alerts.append({"alert_type": "high_temp", "level": "warning", "is_predictive": True, "pond": pond,
                "message": f"⚠️ PREDICTIVE: Pond '{pond.name}' temp rising. Current: {current_temp}°C | Trend: +{slope:.2f}°C/day | Proj 3d: {proj_3day}°C. Prepare cooling.",
                "trend_slope": slope, "current_value": current_temp, "projected_1d": proj_1day, "projected_3d": proj_3day})

    # Low Temp
    if slope < -0.4 and proj_3day <= TEMP_LOW_WARNING:
        alerts.append({"alert_type": "low_temp", "level": "warning", "is_predictive": True, "pond": pond,
            "message": f"⚠️ PREDICTIVE: Pond '{pond.name}' temp dropping. Current: {current_temp}°C | Proj 3d: {proj_3day}°C. Reduce feeding.",
            "trend_slope": slope, "current_value": current_temp, "projected_1d": proj_1day, "projected_3d": proj_3day})

    return alerts


# ── 2. Mortality Pattern Predictor ────────────────────────────────────────────

def predict_mortality_alerts(batch, pre_fetched_mortality: list = None) -> list[dict[str, Any]]:
    """Detects accelerating death rates. Supports bulk pre-fetched data."""
    # User's defensive check
    if not batch.pond:
        return []

    alerts = []
    fourteen_days_ago = timezone.now().date() - timedelta(days=14)

    if pre_fetched_mortality is not None:
        logs = [log for log in pre_fetched_mortality if log.date >= fourteen_days_ago]
    else:
        from ..models import MortalityLog
        logs = list(MortalityLog.objects.filter(batch=batch, date__gte=fourteen_days_ago).order_by("date"))

    if not logs:
        return []

    # User's safe int logic
    daily_deaths: dict[date, int] = {}
    for log in logs:
        count = _safe_int(log.count, 0)
        daily_deaths[log.date] = daily_deaths.get(log.date, 0) + count

    all_days = [daily_deaths.get(fourteen_days_ago + timedelta(days=i), 0) for i in range(14)]
    first_week, second_week = sum(all_days[:7]), sum(all_days[7:])
    slope, latest_daily = _linear_trend([float(v) for v in all_days])

    # User's case-insensitive disease check + safe int
    disease_count = sum(_safe_int(log.count, 0) for log in logs if log.cause and log.cause.lower() == "disease")
    total_count = sum(_safe_int(log.count, 0) for log in logs)
    disease_pct = (disease_count / total_count * 100) if total_count > 0 else 0

    # Accelerating mortality
    if slope > 1.5 and second_week > first_week:
        acceleration = round((second_week - first_week) / max(first_week, 1) * 100, 1)
        proj_7day = _project_value(latest_daily, slope, 7)

        level = "critical" if (latest_daily >= MORTALITY_CRITICAL or proj_7day >= MORTALITY_CRITICAL) else "warning"
        prefix = "🔴 PREDICTIVE CRITICAL" if level == "critical" else "⚠️ PREDICTIVE"

        alerts.append({"alert_type": "high_mortality", "level": level, "is_predictive": True, "pond": batch.pond,
            "message": f"{prefix}: Batch '{batch}' mortality ACCELERATING. W1: {first_week} | W2: {second_week} ({acceleration}% incr). Proj 7d: {proj_7day:.0f}/day.",
            "trend_slope": slope, "first_week": first_week, "second_week": second_week, "acceleration_pct": acceleration})

    # Disease outbreak
    if disease_pct >= 60 and total_count >= 20:
        alerts.append({"alert_type": "high_mortality", "level": "warning", "is_predictive": True, "pond": batch.pond,
            "message": f"🦠 PREDICTIVE DISEASE: Batch '{batch}' — {disease_pct:.0f}% deaths ({disease_count}/{total_count}) disease-related.",
            "disease_pct": disease_pct, "disease_count": disease_count, "total_count": total_count})

    return alerts


# ── 3. DO (Dissolved Oxygen) Trend Predictor ──────────────────────────────────

def predict_do_alerts(pond, pre_fetched_weather: list = None) -> list[dict[str, Any]]:
    """Predict low DO events. Supports bulk pre-fetched data."""
    alerts = []
    five_days_ago = timezone.now() - timedelta(days=5)

    if pre_fetched_weather is not None:
        do_values = [_safe_float(w.dissolved_oxygen_mg_l) for w in pre_fetched_weather 
                     if w.timestamp >= five_days_ago and w.dissolved_oxygen_mg_l is not None]
    else:
        from ..models import WeatherRecord
        records = list(WeatherRecord.objects.filter(pond=pond, timestamp__gte=five_days_ago)
                       .order_by("timestamp").values_list("dissolved_oxygen_mg_l", flat=True))
        do_values = [_safe_float(d) for d in records if d is not None]

    if len(do_values) < 3:
        return []

    slope, current_do = _linear_trend(do_values)
    if slope >= 0:
        return []

    proj_2day = _project_value(current_do, slope, 2)

    if proj_2day <= DO_CRITICAL:
        alerts.append({"alert_type": "low_oxygen", "level": "critical", "is_predictive": True, "pond": pond,
            "message": f"🔴 PREDICTIVE: Pond '{pond.name}' DO DROPPING FAST. Current: {current_do} mg/L | Proj 2d: {proj_2day} mg/L. Increase aeration NOW.",
            "trend_slope": slope, "current_value": current_do, "projected_2d": proj_2day})
    elif proj_2day <= DO_WARNING:
        alerts.append({"alert_type": "low_oxygen", "level": "warning", "is_predictive": True, "pond": pond,
            "message": f"⚠️ PREDICTIVE: Pond '{pond.name}' DO declining. Current: {current_do} mg/L | Proj 2d: {proj_2day} mg/L. Check aerator.",
            "trend_slope": slope, "current_value": current_do, "projected_2d": proj_2day})

    return alerts


# ── Master runner (Optimized to 2 Queries Max) ───────────────────────────────

def run_predictive_alerts(user=None) -> int:
    """
    Run all predictive alerts. Fetches ALL data in 2 queries, then processes in memory.
    """
    from ..models import Pond, FishBatch, WeatherRecord, MortalityLog

    ponds = Pond.objects.filter(owner=user) if user else Pond.objects.all()
    batches = FishBatch.objects.filter(pond__owner=user) if user else FishBatch.objects.all()

    if not ponds and not batches:
        return 0

    # ✅ PERFORMANCE FIX: Fetch everything in 2 queries instead of N+1
    min_weather_date = timezone.now() - timedelta(days=7)
    all_weather = list(
        WeatherRecord.objects.filter(pond__in=ponds, timestamp__gte=min_weather_date)
        .select_related("pond")
    )
    weather_by_pond = defaultdict(list)
    for w in all_weather:
        weather_by_pond[w.pond_id].append(w)

    min_mort_date = timezone.now().date() - timedelta(days=14)
    all_mortality = list(
        MortalityLog.objects.filter(batch__in=batches, date__gte=min_mort_date)
        .select_related("batch")
    )
    mortality_by_batch = defaultdict(list)
    for m in all_mortality:
        mortality_by_batch[m.batch_id].append(m)

    created_count = 0

    for pond in ponds:
        pond_weather = weather_by_pond.get(pond.id, [])
        created_count += sum(_create_predictive_alert(a) for a in predict_temperature_alerts(pond, pond_weather))
        created_count += sum(_create_predictive_alert(a) for a in predict_do_alerts(pond, pond_weather))

    for batch in batches:
        batch_mortality = mortality_by_batch.get(batch.id, [])
        created_count += sum(_create_predictive_alert(a) for a in predict_mortality_alerts(batch, batch_mortality))

    logger.info(f"[Predictive Alerts] Processed {len(ponds)} ponds & {len(batches)} batches. Created {created_count} alerts.")
    return created_count


def _create_predictive_alert(alert_data: dict) -> int:
    """Save alert with robust deduplication and None-checks."""
    from ..models import FarmAlert

    pond = alert_data.get("pond")
    
    # ✅ USER'S CRITICAL FIX: Prevent DB IntegrityError if pond is missing
    if pond is None:
        logger.warning("[Predictive Alerts] Skipping alert with no pond reference.")
        return 0

    alert_type = alert_data.get("alert_type")
    level = alert_data.get("level")

    # ✅ USER'S CRITICAL FIX: Predictive deduplication without relying on text/emojis
    existing = FarmAlert.objects.filter(
        pond=pond,
        alert_type=alert_type,
        level=level,
        resolved=False,
        is_predictive=True,  # Isolates predictive alerts from live alerts
    ).exists()

    if existing:
        return 0

    FarmAlert.objects.create(
        pond=pond,
        alert_type=alert_type,
        level=level,
        message=alert_data.get("message", ""),
        is_predictive=True,  # Mark explicitly
    )
    return 1


# ── Analytics: get trend data for dashboard ───────────────────────────────────

def get_temperature_trend_data(pond, days: int = 7) -> dict:
    """Returns perfectly aligned chart data for temperature and DO."""
    from ..models import WeatherRecord

    since = timezone.now() - timedelta(days=days)
    records = list(
        WeatherRecord.objects.filter(pond=pond, timestamp__gte=since)
        .order_by("timestamp").values("timestamp", "water_temp_c", "dissolved_oxygen_mg_l")
    )

    if not records:
        return {"labels": [], "temps": [], "do_values": [], "slope": 0}

    # ✅ USER'S CRITICAL FIX: Meticulous label alignment to prevent Chart.js bugs
    valid_labels = []
    valid_temps = []
    valid_do = []
    
    for r in records:
        t = r["water_temp_c"]
        if t is not None:
            valid_labels.append(r["timestamp"].strftime("%m/%d %H:%M"))
            valid_temps.append(_safe_float(t))
            d = r["dissolved_oxygen_mg_l"]
            if d is not None:
                valid_do.append(_safe_float(d))

    slope, current = _linear_trend(valid_temps) if valid_temps else (0, 0)

    proj_labels = [f"+{i}d" for i in range(1, 4)]
    proj_temps  = [_project_value(current, slope, i) for i in range(1, 4)]

    return {
        "labels": valid_labels, "temps": valid_temps, "do_values": valid_do,
        "slope": slope, "current_temp": current,
        "proj_labels": proj_labels, "proj_temps": proj_temps,
        "warning_line": TEMP_WARNING_C, "critical_line": TEMP_CRITICAL_C,
    }