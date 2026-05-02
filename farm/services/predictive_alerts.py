"""
farm/services/predictive_alerts.py
────────────────────────────────────────────────────────────────────────────
Predictive Alert System
========================

Analyzes historical trends to generate EARLY WARNING alerts before problems occur.

Two prediction engines:
  1. Temperature Trend Predictor
     - Looks at last 7 days of water temperature readings
     - Fits a linear trend line
     - If projected temp will exceed danger thresholds within 3 days → alert

  2. Mortality Pattern Predictor
     - Looks at last 14 days of mortality events
     - Detects accelerating death rates
     - Clusters causes to identify potential disease outbreak
     - If mortality rate is rising → predictive disease alert

Alert levels:
  - PREDICTIVE_WARN   : trend is heading toward danger (yellow)
  - PREDICTIVE_CRITICAL: projected to hit critical threshold within 48h (red)
"""

from __future__ import annotations

import logging
import statistics
from datetime import date, timedelta
from typing import Any

from django.utils import timezone

logger = logging.getLogger(__name__)


# ── Safe thresholds ───────────────────────────────────────────────────────────

TEMP_WARNING_C    = 31.0   # warn before hitting critical
TEMP_CRITICAL_C   = 34.0   # critical threshold
TEMP_LOW_WARNING  = 16.0   # low temp warning
DO_WARNING        = 5.0    # warn before critical
DO_CRITICAL       = 4.0    # critical DO
MORTALITY_SPIKE   = 10     # deaths/day → concern
MORTALITY_CRITICAL = 30    # deaths/day → critical


# ── Linear trend helper ───────────────────────────────────────────────────────

def _linear_trend(values: list[float]) -> tuple[float, float]:
    """
    Fit a simple linear trend to a list of values.
    Returns (slope_per_day, latest_value).
    Positive slope = rising, negative = falling.
    """
    if len(values) < 2:
        return 0.0, values[-1] if values else 0.0

    n = len(values)
    x = list(range(n))
    x_mean = statistics.mean(x)
    y_mean = statistics.mean(values)

    numerator   = sum((x[i] - x_mean) * (values[i] - y_mean) for i in range(n))
    denominator = sum((x[i] - x_mean) ** 2 for i in range(n))

    slope = numerator / denominator if denominator != 0 else 0.0
    return round(slope, 4), round(values[-1], 2)


def _project_value(current: float, slope: float, days_ahead: int) -> float:
    """Project a value N days into the future using the trend slope."""
    return round(current + slope * days_ahead, 2)


# ── 1. Temperature Trend Predictor ───────────────────────────────────────────

def predict_temperature_alerts(pond) -> list[dict[str, Any]]:
    """
    Analyze water temperature trend for a pond.
    Returns list of predictive alert dicts if trend is dangerous.
    """
    from ..models import WeatherRecord

    alerts = []

    # Last 7 days of readings
    seven_days_ago = timezone.now() - timedelta(days=7)
    records = list(
        WeatherRecord.objects
        .filter(pond=pond, timestamp__gte=seven_days_ago)
        .order_by("timestamp")
        .values_list("water_temp_c", flat=True)
    )

    if len(records) < 3:
        return []   # not enough data for trend

    temps  = [float(t) for t in records]
    slope, current_temp = _linear_trend(temps)

    # Project 3 days ahead
    proj_1day = _project_value(current_temp, slope, 1)
    proj_3day = _project_value(current_temp, slope, 3)

    # ── High temperature trend ────────────────────────────────────────────────
    if slope > 0.3:   # rising more than 0.3°C per day
        if proj_1day >= TEMP_CRITICAL_C:
            alerts.append({
                "alert_type":  "high_temp",
                "level":       "critical",
                "is_predictive": True,
                "pond":        pond,
                "message": (
                    f"🔴 PREDICTIVE: Pond '{pond.name}' water temperature trending CRITICAL. "
                    f"Current: {current_temp}°C | Trend: +{slope:.2f}°C/day | "
                    f"Projected tomorrow: {proj_1day}°C (limit: {TEMP_CRITICAL_C}°C). "
                    f"Take action NOW to prevent fish loss."
                ),
                "trend_slope":   slope,
                "current_value": current_temp,
                "projected_1d":  proj_1day,
                "projected_3d":  proj_3day,
            })
        elif proj_3day >= TEMP_WARNING_C:
            alerts.append({
                "alert_type":  "high_temp",
                "level":       "warning",
                "is_predictive": True,
                "pond":        pond,
                "message": (
                    f"⚠️ PREDICTIVE: Pond '{pond.name}' temperature rising. "
                    f"Current: {current_temp}°C | Trend: +{slope:.2f}°C/day | "
                    f"Projected in 3 days: {proj_3day}°C. "
                    f"Monitor closely and prepare cooling measures."
                ),
                "trend_slope":   slope,
                "current_value": current_temp,
                "projected_1d":  proj_1day,
                "projected_3d":  proj_3day,
            })

    # ── Low temperature trend ─────────────────────────────────────────────────
    if slope < -0.4 and proj_3day <= TEMP_LOW_WARNING:
        alerts.append({
            "alert_type":  "low_temp",
            "level":       "warning",
            "is_predictive": True,
            "pond":        pond,
            "message": (
                f"⚠️ PREDICTIVE: Pond '{pond.name}' temperature dropping. "
                f"Current: {current_temp}°C | Trend: {slope:.2f}°C/day | "
                f"Projected in 3 days: {proj_3day}°C. "
                f"Reduce feeding rate preemptively."
            ),
            "trend_slope":   slope,
            "current_value": current_temp,
            "projected_1d":  proj_1day,
            "projected_3d":  proj_3day,
        })

    return alerts


# ── 2. Mortality Pattern Predictor ────────────────────────────────────────────

def predict_mortality_alerts(batch) -> list[dict[str, Any]]:
    """
    Analyze mortality patterns for a batch.
    Detects accelerating death rates that suggest disease outbreak.
    """
    from ..models import MortalityLog
    from django.db.models import Sum

    alerts = []

    fourteen_days_ago = timezone.now().date() - timedelta(days=14)
    logs = list(
        MortalityLog.objects
        .filter(batch=batch, date__gte=fourteen_days_ago)
        .order_by("date")
    )

    if not logs:
        return []

    # Build daily death counts for last 14 days
    daily_deaths: dict[date, int] = {}
    for log in logs:
        daily_deaths[log.date] = daily_deaths.get(log.date, 0) + log.count

    # Fill missing days with 0
    all_days = []
    for i in range(14):
        d = fourteen_days_ago + timedelta(days=i)
        all_days.append(daily_deaths.get(d, 0))

    # Compare first week vs second week
    first_week  = sum(all_days[:7])
    second_week = sum(all_days[7:])

    # Trend analysis
    slope, latest_daily = _linear_trend([float(v) for v in all_days])

    # Cause analysis — check if "disease" is dominant cause
    disease_count = sum(
        log.count for log in logs if log.cause == "disease"
    )
    total_count = sum(log.count for log in logs)
    disease_pct = (disease_count / total_count * 100) if total_count > 0 else 0

    # ── Accelerating mortality ────────────────────────────────────────────────
    if slope > 1.5 and second_week > first_week:
        acceleration = round((second_week - first_week) / max(first_week, 1) * 100, 1)
        proj_7day    = _project_value(latest_daily, slope, 7)

        if latest_daily >= MORTALITY_CRITICAL or proj_7day >= MORTALITY_CRITICAL:
            level = "critical"
            prefix = "🔴 PREDICTIVE CRITICAL"
        else:
            level = "warning"
            prefix = "⚠️ PREDICTIVE"

        alerts.append({
            "alert_type":    "high_mortality",
            "level":         level,
            "is_predictive": True,
            "pond":          batch.pond,
            "message": (
                f"{prefix}: Batch '{batch}' mortality is ACCELERATING. "
                f"Week 1: {first_week} deaths | Week 2: {second_week} deaths "
                f"({acceleration}% increase). "
                f"Projected daily deaths in 7 days: {proj_7day:.0f}. "
                f"Inspect pond immediately for disease signs."
            ),
            "trend_slope":    slope,
            "first_week":     first_week,
            "second_week":    second_week,
            "acceleration_pct": acceleration,
        })

    # ── Disease outbreak prediction ───────────────────────────────────────────
    if disease_pct >= 60 and total_count >= 20:
        alerts.append({
            "alert_type":    "high_mortality",
            "level":         "warning",
            "is_predictive": True,
            "pond":          batch.pond,
            "message": (
                f"🦠 PREDICTIVE DISEASE: Batch '{batch}' — {disease_pct:.0f}% of recent "
                f"deaths ({disease_count}/{total_count}) are disease-related. "
                f"Possible outbreak developing. Quarantine affected fish, "
                f"check water quality, consult Fish Doctor AI."
            ),
            "disease_pct":   disease_pct,
            "disease_count": disease_count,
            "total_count":   total_count,
        })

    return alerts


# ── 3. DO (Dissolved Oxygen) Trend Predictor ──────────────────────────────────

def predict_do_alerts(pond) -> list[dict[str, Any]]:
    """Predict low DO events before they become critical."""
    from ..models import WeatherRecord

    alerts = []
    five_days_ago = timezone.now() - timedelta(days=5)
    records = list(
        WeatherRecord.objects
        .filter(pond=pond, timestamp__gte=five_days_ago)
        .order_by("timestamp")
        .values_list("dissolved_oxygen_mg_l", flat=True)
    )

    if len(records) < 3:
        return []

    do_values = [float(d) for d in records]
    slope, current_do = _linear_trend(do_values)

    if slope >= 0:
        return []   # DO is stable or rising — no concern

    proj_2day = _project_value(current_do, slope, 2)

    if proj_2day <= DO_CRITICAL:
        alerts.append({
            "alert_type":    "low_oxygen",
            "level":         "critical",
            "is_predictive": True,
            "pond":          pond,
            "message": (
                f"🔴 PREDICTIVE: Pond '{pond.name}' DO is DROPPING FAST. "
                f"Current: {current_do} mg/L | Trend: {slope:.3f} mg/L/reading | "
                f"Projected in 2 days: {proj_2day} mg/L (critical: {DO_CRITICAL}). "
                f"Increase aeration immediately."
            ),
            "trend_slope":   slope,
            "current_value": current_do,
            "projected_2d":  proj_2day,
        })
    elif proj_2day <= DO_WARNING:
        alerts.append({
            "alert_type":    "low_oxygen",
            "level":         "warning",
            "is_predictive": True,
            "pond":          pond,
            "message": (
                f"⚠️ PREDICTIVE: Pond '{pond.name}' DO declining. "
                f"Current: {current_do} mg/L | Trend: {slope:.3f} mg/L/reading | "
                f"Projected in 2 days: {proj_2day} mg/L. "
                f"Check aeration system."
            ),
            "trend_slope":   slope,
            "current_value": current_do,
            "projected_2d":  proj_2day,
        })

    return alerts


# ── Master runner ─────────────────────────────────────────────────────────────

def run_predictive_alerts(user=None) -> int:
    """
    Run all predictive alert checks across all ponds and batches.
    Call this from:
      - A Celery task (scheduled hourly)
      - The dashboard view (on load)
      - Manually from admin

    Returns count of new alerts created.
    """
    from ..models import Pond, FishBatch, FarmAlert

    created_count = 0

    # Scope to user's ponds if provided
    ponds = Pond.objects.filter(owner=user) if user else Pond.objects.all()
    batches = (
        FishBatch.objects.filter(pond__owner=user)
        if user else FishBatch.objects.all()
    )

    for pond in ponds.select_related("owner"):
        # Temperature predictions
        for alert_data in predict_temperature_alerts(pond):
            created_count += _create_predictive_alert(alert_data)

        # DO predictions
        for alert_data in predict_do_alerts(pond):
            created_count += _create_predictive_alert(alert_data)

    for batch in batches.select_related("pond"):
        # Mortality predictions
        for alert_data in predict_mortality_alerts(batch):
            created_count += _create_predictive_alert(alert_data)

    logger.info(f"[Predictive Alerts] Created {created_count} new alerts.")
    return created_count


def _create_predictive_alert(alert_data: dict) -> int:
    """
    Save a predictive alert to DB — skip if identical unresolved alert exists.
    Returns 1 if created, 0 if skipped.
    """
    from ..models import FarmAlert

    pond       = alert_data.get("pond")
    alert_type = alert_data.get("alert_type")
    level      = alert_data.get("level")
    message    = alert_data.get("message", "")

    # Deduplication: don't create if same type+pond already unresolved
    existing = FarmAlert.objects.filter(
        pond=pond,
        alert_type=alert_type,
        resolved=False,
        message__startswith="🔴 PREDICTIVE" if level == "critical" else "⚠️ PREDICTIVE",
    ).exists()

    if existing:
        return 0

    FarmAlert.objects.create(
        pond=pond,
        alert_type=alert_type,
        level=level,
        message=message,
    )
    return 1


# ── Analytics: get trend data for dashboard ───────────────────────────────────

def get_temperature_trend_data(pond, days: int = 7) -> dict:
    """
    Returns temperature trend data for chart rendering.
    Used by the analytics dashboard.
    """
    from ..models import WeatherRecord

    since = timezone.now() - timedelta(days=days)
    records = list(
        WeatherRecord.objects
        .filter(pond=pond, timestamp__gte=since)
        .order_by("timestamp")
        .values("timestamp", "water_temp_c", "dissolved_oxygen_mg_l")
    )

    if not records:
        return {"labels": [], "temps": [], "do_values": [], "slope": 0}

    labels    = [r["timestamp"].strftime("%m/%d %H:%M") for r in records]
    temps     = [float(r["water_temp_c"]) for r in records]
    do_values = [float(r["dissolved_oxygen_mg_l"]) for r in records]

    slope, current = _linear_trend(temps) if temps else (0, 0)

    # Projected next 3 points
    proj_labels = []
    proj_temps  = []
    for i in range(1, 4):
        proj_labels.append(f"+{i}d")
        proj_temps.append(_project_value(current, slope, i))

    return {
        "labels":       labels,
        "temps":        temps,
        "do_values":    do_values,
        "slope":        slope,
        "current_temp": current,
        "proj_labels":  proj_labels,
        "proj_temps":   proj_temps,
        "warning_line": TEMP_WARNING_C,
        "critical_line": TEMP_CRITICAL_C,
    }