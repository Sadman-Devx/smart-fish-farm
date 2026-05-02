"""
farm/views.py — Smart Fish Farm Management System
─────────────────────────────────────────────────
Access policy:
  • All views require login — each user sees ONLY their own data.
  • Per-user isolation: Pond.owner = request.user filters all querysets.
  • Guests (unauthenticated) are redirected to login for all farm views.

Per-user data isolation (2026-04):
  Problem: All users shared the same ponds, batches, feeds, etc.
  Fix:     Pond.owner ForeignKey added. Every queryset now filters by
           owner=request.user (for Pond) or pond__owner=request.user
           (for Batch, FeedLog, Expense, etc.).

Bug fixes (2026-04):
  Bug 1 — "Recommended (KG)" column in the 14-day table always showed "—"
  Bug 2 — "Recommended feed today" KPI always showed 0.00 kg

  Root cause: smart_feed_kg_for_batch(batch, day=past_date) returned None
  whenever no DailyWeather row existed for that date AND the OpenWeather
  API key was not configured.  The dashboard loop then never accumulated
  any value so recommended_feed_today_kg stayed at 0 and every row in
  daily_feed_temp_rows had recommended_feed_kg=None.

  Fix:
    1. feed_calculator.py — added a 3-level temperature fallback:
         exact DailyWeather → most-recent DailyWeather → pond WeatherRecord → 26 °C
    2. dashboard() — source label updated to show "Default temp (26°C)"
       so operators know which temperature was used.

Analytics additions (2026-04):
  Feature 1 — Enhanced batch_detail with growth chart + summary card
  Feature 2 — Enhanced profit/loss with expense breakdown & 6-month trends
  Feature 3 — New mortality_report view with cause breakdown & trends
"""
from datetime import timedelta, date
from decimal import Decimal
import base64

from django.db.models import Avg, Sum, Count, Q
from django.db.models.functions import TruncDate, TruncMonth
from django.contrib import messages
from django.conf import settings
from django.http import JsonResponse
from django.shortcuts import get_object_or_404, redirect, render
from django.utils import timezone
from django.views.decorators.http import require_POST
from django.contrib.auth.decorators import login_required
import google.genai as genai
from google.genai import types
from .services.weather_ingest import get_weather_for_location, get_feeding_suggestion
from .services.predictive_alerts import run_predictive_alerts, get_temperature_trend_data
from .services.fcr_analytics import get_feed_efficiency_ranking, get_fcr_history, calculate_batch_fcr
from .services.water_heatmap import build_water_quality_heatmap

from .models import (
    FeedLog, FeedingProfile, FeedingReminder, FishBatch,
    GrowthRecord, Pond, WeatherRecord,
    HarvestRecord, Expense, MortalityLog, FarmAlert, PondNote,
)
from . import forms
from .services import (
    get_or_update_daily_weather,
    predict_batch_growth,
    projected_avg_weight_g,
    projected_weight_gain_kg,
    smart_feed_kg_for_batch,
    ml_predict_batch_growth,
)
from .services.benchmarking import (
    run_full_benchmark, get_benchmark_stats_for_paper, benchmark_view,
)
from .tasks import send_daily_feed_alert

from django.contrib.admin.views.decorators import staff_member_required
from .services.benchmarking import (
    run_full_benchmark,
    get_benchmark_stats_for_paper,
)


# ─────────────────────────────────────────────────────────────────────────────
# Per-user queryset helpers
# Every view MUST use these instead of Model.objects.all() so that each
# user sees only their own data.
# ─────────────────────────────────────────────────────────────────────────────

def _user_ponds(user):
    """Return Ponds belonging to this user."""
    return Pond.objects.filter(owner=user)


def _user_batches(user):
    """Return FishBatches whose pond belongs to this user."""
    return FishBatch.objects.filter(pond__owner=user)


def _user_feed_logs(user):
    return FeedLog.objects.filter(batch__pond__owner=user)


def _user_reminders(user):
    return FeedingReminder.objects.filter(batch__pond__owner=user)


def _user_alerts(user):
    return FarmAlert.objects.filter(pond__owner=user)


def _user_harvests(user):
    return HarvestRecord.objects.filter(batch__pond__owner=user)


def _user_expenses(user):
    return Expense.objects.filter(pond__owner=user)


def _user_mortality_logs(user):
    return MortalityLog.objects.filter(batch__pond__owner=user)


def _user_weather_records(user):
    return WeatherRecord.objects.filter(pond__owner=user)


# ─────────────────────────────────────────────────────────────────────────────
# Internal helpers
# ─────────────────────────────────────────────────────────────────────────────

def _generate_water_alerts(weather_record: WeatherRecord, user=None) -> None:
    """Auto-create FarmAlert entries and send email when water readings are out of range."""
    from .notifications import send_email_notification

    pond = weather_record.pond
    temp = float(weather_record.water_temp_c)
    do   = float(weather_record.dissolved_oxygen_mg_l)
    ph   = float(weather_record.ph)

    checks = [
        (do < 4.0,              "low_oxygen", "critical", f"🚨 CRITICAL: Pond {pond.name}: DO critically low at {do} mg/L (min 4.0) — fish may die!"),
        (do < 5.0,              "low_oxygen", "warning",  f"⚠️ WARNING: Pond {pond.name}: DO below optimum at {do} mg/L — check aeration"),
        (temp > 34.0,           "high_temp",  "critical", f"🚨 CRITICAL: Pond {pond.name}: Water temp critically high at {temp}°C — urgent action needed!"),
        (temp > 31.0,           "high_temp",  "warning",  f"⚠️ WARNING: Pond {pond.name}: Water temp elevated at {temp}°C — reduce feed"),
        (temp < 15.0,           "low_temp",   "warning",  f"⚠️ WARNING: Pond {pond.name}: Water temp low at {temp}°C — reduce feed significantly"),
        (ph < 6.5 or ph > 9.0, "ph_out",     "warning",  f"⚠️ WARNING: Pond {pond.name}: pH out of range at {ph} (safe: 6.5–9.0)"),
    ]

    new_alerts = []
    for condition, atype, level, msg in checks:
        if condition:
            exists = FarmAlert.objects.filter(
                pond=pond, alert_type=atype, resolved=False
            ).exists()
            if not exists:
                alert = FarmAlert.objects.create(
                    pond=pond, alert_type=atype, level=level, message=msg
                )
                new_alerts.append(alert)

    if new_alerts:
        subject = f"🚨 AquaSmart Water Quality Alert — {pond.name}"
        lines = [
            f"Water Quality Alert for Pond: {pond.name}",
            f"Logged at: {weather_record.timestamp.strftime('%Y-%m-%d %H:%M')}",
            "",
            "📊 Current Readings:",
            f"  🌡️  Water Temperature : {temp}°C",
            f"  💧 Dissolved Oxygen  : {do} mg/L",
            f"  🧪 pH Level          : {ph}",
            "",
            "⚠️ Alerts Triggered:",
        ]
        for alert in new_alerts:
            lines.append(f"  • [{alert.level.upper()}] {alert.message}")

        lines += [
            "",
            "Please take immediate action to prevent fish loss.",
            "Login to AquaSmart dashboard to resolve these alerts.",
        ]
        send_email_notification(subject, "\n".join(lines))


def _generate_harvest_due_alerts(user=None) -> None:
    """Create harvest-due alerts for batches within 7 days of estimated harvest."""
    qs = FishBatch.objects.prefetch_related("growth_records")
    if user is not None:
        qs = qs.filter(pond__owner=user)
    for batch in qs:
        pred = predict_batch_growth(batch)
        days = pred.get("estimated_days_to_market", 999)
        if days <= 7:
            exists = FarmAlert.objects.filter(
                alert_type="harvest_due",
                message__contains=str(batch.id),
                resolved=False,
            ).exists()
            if not exists:
                FarmAlert.objects.create(
                    pond=batch.pond,
                    alert_type="harvest_due",
                    level="warning",
                    message=(
                        f"Batch #{batch.id} ({batch}) estimated harvest in {days} day(s) "
                        f"(est. {pred.get('estimated_harvest_date')})."
                    ),
                )


# ─────────────────────────────────────────────────────────────────────────────
# Dashboard — PUBLIC (read-only for guests)
# ─────────────────────────────────────────────────────────────────────────────

def dashboard(request):
    """
    Main dashboard.
    - Logged-in users: see their own data, can create/edit.
    - Guests: see the page but with empty data and no create buttons.
    """
    user = request.user
    is_guest = not user.is_authenticated

    daily_api_weather = get_or_update_daily_weather()
    farm_weather      = None
    feeding_suggest   = None

    if not is_guest:
        _generate_harvest_due_alerts(user)
        try:
            fp = user.farm_profile
            if fp.latitude and fp.longitude:
                farm_weather = get_weather_for_location(float(fp.latitude), float(fp.longitude))
            elif fp.district:
                from .services.weather_ingest import get_weather_by_city
                location_query = f"{fp.upazila},{fp.district},BD" if fp.upazila else f"{fp.district},BD"
                farm_weather = get_weather_by_city(location_query)
            elif fp.weather_temp_c:
                farm_weather = {
                    "temp_c":    float(fp.weather_temp_c),
                    "humidity":  fp.weather_humidity_pct or 0,
                    "rain_mm":   float(fp.weather_rain_mm or 0),
                    "condition": fp.weather_condition or "—",
                }
            if farm_weather:
                feeding_suggest = get_feeding_suggestion(
                    farm_weather["temp_c"], farm_weather["humidity"], farm_weather["rain_mm"],
                )
        except Exception:
            pass

    # ── Querysets: empty for guests, user-scoped for logged-in ────────────────
    if is_guest:
        ponds          = Pond.objects.none()
        active_batches = FishBatch.objects.none()
        recent_feed    = FeedLog.objects.none()
        pending_reminders = FeedingReminder.objects.none()
        unresolved_alerts = 0
        critical_alerts   = FarmAlert.objects.none()
    else:
        ponds = _user_ponds(user).annotate(
            total_biomass_kg=Sum("batches__growth_records__avg_weight_g")
        )
        active_batches = (
            _user_batches(user)
            .prefetch_related("growth_records", "feed_logs")
            .order_by("pond__name", "stocking_date")
        )
        recent_feed       = _user_feed_logs(user).order_by("-date")[:7]
        today             = timezone.now().date()
        pending_reminders = _user_reminders(user).filter(
            scheduled_for__date=today, sent=False
        ).order_by("scheduled_for")
        unresolved_alerts = _user_alerts(user).filter(resolved=False).count()
        critical_alerts   = _user_alerts(user).filter(resolved=False, level="critical")

    feed_cost_per_kg = float(getattr(settings, "FEED_COST_PER_KG", 1.2))

    # ── Chart data ─────────────────────────────────────────────────────────────
    biomass_labels, biomass_values = [], []
    for batch in active_batches:
        biomass_labels.append(f"{batch.pond.name} – {batch.get_species_display()}")
        biomass_values.append(round(batch.latest_biomass_kg, 2))

    mortality_labels, mortality_values = [], []
    for batch in active_batches:
        latest  = batch.growth_records.order_by("-date").first()
        current = latest.surviving_count if latest else batch.initial_count
        pct     = ((batch.initial_count - current) / batch.initial_count * 100) if batch.initial_count else 0
        mortality_labels.append(f"{batch.pond.name} – {batch.get_species_display()}")
        mortality_values.append(round(max(pct, 0), 2))

    feed_cost_labels, feed_cost_values, feed_consumption_values = [], [], []
    weather_points      = []
    weather_labels      = []
    weather_temp_values = []
    feed_daily          = []
    daily_feed_temp_rows        = []
    target_actual_labels        = []
    target_actual_actual_values = []
    target_actual_target_values = []

    if not is_guest:
        for log in reversed(list(recent_feed)):
            feed_cost_labels.append(str(log.date))
            feed_cost_values.append(round(float(log.feed_amount_kg) * feed_cost_per_kg, 2))
            feed_consumption_values.append(round(float(log.feed_amount_kg), 2))

        weather_points = list(
            _user_weather_records(user).order_by("-timestamp").values("timestamp", "water_temp_c")[:14]
        )
        weather_points.reverse()
        weather_labels      = [p["timestamp"].strftime("%Y-%m-%d") for p in weather_points]
        weather_temp_values = [float(p["water_temp_c"]) for p in weather_points]

        # ── 14-day feed rows ───────────────────────────────────────────────────
        feed_daily = list(
            _user_feed_logs(user).values("date")
            .annotate(total_feed_kg=Sum("feed_amount_kg"))
            .order_by("-date")[:14]
        )
        feed_daily.reverse()

        weather_daily = list(
            _user_weather_records(user).annotate(day=TruncDate("timestamp"))
            .values("day").annotate(avg_temp_c=Avg("water_temp_c")).order_by("-day")[:21]
        )
        temp_by_day = {r["day"]: float(r["avg_temp_c"]) for r in weather_daily if r["day"]}

        for row in feed_daily:
            day    = row["date"]
            rec_kg = 0.0
            has_recommendation_data = False
            for b in active_batches:
                val = smart_feed_kg_for_batch(b, day=day)
                if val is not None:
                    has_recommendation_data = True
                    rec_kg += val

            daily_feed_temp_rows.append({
                "date":                day,
                "feed_kg":             round(float(row["total_feed_kg"]), 2),
                "temp_c":              round(temp_by_day[day], 1) if day in temp_by_day else None,
                "recommended_feed_kg": round(rec_kg, 2) if has_recommendation_data else None,
            })
            target_actual_labels.append(str(day))
            target_actual_actual_values.append(round(float(row["total_feed_kg"]), 2))
            target_actual_target_values.append(round(rec_kg, 2) if has_recommendation_data else None)

    # ── "Recommended feed today" KPI ──────────────────────────────────────────
    today = timezone.now().date()

    if is_guest:
        today_feed_given_kg       = 0.0
        recommended_feed_today_kg = 0.0
        label                     = "No recommendation"
    else:
        today_feed_given_kg       = float(
            _user_feed_logs(user).filter(date=today).aggregate(total=Sum("feed_amount_kg"))["total"] or 0
        )
        recommended_feed_today_kg = 0.0
        recommended_feed_sources  = set()

        for batch in active_batches:
            suggested = smart_feed_kg_for_batch(batch, day=today)
            if suggested is not None:
                recommended_feed_today_kg += float(suggested)
                has_pond_weather = _user_weather_records(user).filter(pond=batch.pond).exists()
                if has_pond_weather:
                    recommended_feed_sources.add("pond")
                elif daily_api_weather:
                    recommended_feed_sources.add("api")
                else:
                    recommended_feed_sources.add("default")

        recommended_feed_today_kg = round(recommended_feed_today_kg, 2)

        if recommended_feed_sources == {"pond"}:
            label = "Pond weather"
        elif recommended_feed_sources == {"api"}:
            label = "API weather"
        elif "default" in recommended_feed_sources:
            label = "Default temp (26°C)"
        elif recommended_feed_sources:
            label = "Mixed sources"
        else:
            label = "No recommendation"

    # ── KPIs ───────────────────────────────────────────────────────────────────
    total_ponds         = ponds.count()
    total_batches       = active_batches.count()
    reminders_today     = pending_reminders.count()
    feed_last_7_days_kg = round(sum(float(l.feed_amount_kg) for l in recent_feed), 2)
    avg_recent_temp_c   = (
        round(sum(weather_temp_values) / len(weather_temp_values), 1)
        if weather_temp_values else None
    )

    context = dict(
        is_guest=is_guest,
        ponds=ponds,
        active_batches=active_batches,
        recent_feed=recent_feed,
        pending_reminders=pending_reminders,
        total_ponds=total_ponds,
        total_batches=total_batches,
        reminders_today=reminders_today,
        feed_last_7_days_kg=feed_last_7_days_kg,
        today_feed_given_kg=today_feed_given_kg,
        recommended_feed_today_kg=recommended_feed_today_kg,
        recommended_feed_source_label=label,
        avg_recent_temp_c=avg_recent_temp_c,
        daily_api_temp_c=daily_api_weather.temperature_c if daily_api_weather else None,
        daily_api_condition=daily_api_weather.condition if daily_api_weather else None,
        daily_api_feed_percent=daily_api_weather.feed_percent if daily_api_weather else None,
        daily_api_date=daily_api_weather.date if daily_api_weather else today,
        daily_api_location=daily_api_weather.location_query if daily_api_weather else None,
        daily_feed_temp_rows=daily_feed_temp_rows,
        target_actual_labels=target_actual_labels,
        target_actual_actual_values=target_actual_actual_values,
        target_actual_target_values=target_actual_target_values,
        biomass_labels=biomass_labels,
        biomass_values=biomass_values,
        mortality_labels=mortality_labels,
        mortality_values=mortality_values,
        feed_cost_labels=feed_cost_labels,
        feed_cost_values=feed_cost_values,
        feed_consumption_values=feed_consumption_values,
        weather_labels=weather_labels,
        weather_temp_values=weather_temp_values,
        unresolved_alerts=unresolved_alerts,
        critical_alerts=critical_alerts,
        farm_weather=farm_weather,
        feeding_suggest=feeding_suggest,
    )
    return render(request, "farm/dashboard.html", context)


# ─────────────────────────────────────────────────────────────────────────────
# Pond — PUBLIC (read-only)
# ─────────────────────────────────────────────────────────────────────────────

@login_required
def pond_create(request):
    """Create a new pond for the logged-in user."""
    if request.method == "POST":
        form = forms.PondForm(request.POST)
        if form.is_valid():
            pond = form.save(commit=False)
            pond.owner = request.user   # ← tie to current user
            pond.save()
            messages.success(request, f"Pond '{pond.name}' created successfully.")
            return redirect("farm:pond_list")
    else:
        form = forms.PondForm()
    return render(request, "farm/simple_form.html", {"form": form, "title": "Add New Pond"})


@login_required
@require_POST
def pond_delete(request, pk):
    """Delete a pond belonging to the current user."""
    pond = get_object_or_404(Pond, pk=pk, owner=request.user)
    pond_name = pond.name
    pond.delete()
    messages.success(request, f"Pond '{pond_name}' deleted successfully.")
    return redirect("farm:pond_list")


@login_required
def batch_create(request):
    """Create a new fish batch — only user's own ponds shown in dropdown."""
    if request.method == "POST":
        form = forms.FishBatchForm(request.POST, user=request.user)
        if form.is_valid():
            form.save()
            messages.success(request, "Fish batch added successfully.")
            return redirect("farm:pond_list")
    else:
        form = forms.FishBatchForm(user=request.user)
    return render(request, "farm/simple_form.html", {"form": form, "title": "Add Fish Batch"})


@login_required
@require_POST
def batch_delete(request, pk):
    """Delete a fish batch belonging to current user."""
    batch = get_object_or_404(FishBatch, pk=pk, pond__owner=request.user)
    pond_pk = batch.pond_id
    batch.delete()
    messages.success(request, "Fish batch deleted successfully.")
    return redirect("farm:pond_detail", pk=pond_pk)



@login_required
def batch_update(request, pk):
    """Update a fish batch belonging to current user."""
    batch = get_object_or_404(FishBatch, pk=pk, pond__owner=request.user)

    if request.method == "POST":
        form = forms.FishBatchForm(request.POST, instance=batch, user=request.user)
        if form.is_valid():
            updated_batch = form.save()
            messages.success(request, "Fish batch updated successfully.")
            return redirect("farm:batch_detail", pk=updated_batch.pk)
    else:
        form = forms.FishBatchForm(instance=batch, user=request.user)

    return render(request, "farm/simple_form.html", {
        "form": form,
        "title": "Update Fish Batch"
    })



def pond_list(request):
    if request.user.is_authenticated:
        ponds = _user_ponds(request.user)
    else:
        ponds = Pond.objects.none()
    return render(request, "farm/pond_list.html", {"ponds": ponds, "is_guest": not request.user.is_authenticated})


def pond_detail(request, pk):
    is_guest = not request.user.is_authenticated
    if is_guest:
        pond = get_object_or_404(Pond, pk=pk)
    else:
        pond = get_object_or_404(Pond, pk=pk, owner=request.user)
    batches        = pond.batches.all().prefetch_related("growth_records")
    latest_weather = pond.weather_records.first()
    pond_notes     = pond.notes.all()[:10]
    active_alerts  = pond.alerts.filter(resolved=False)
    note_form      = forms.PondNoteForm(initial={"pond": pond}) if not is_guest else None

    if request.method == "POST" and not is_guest:
        if "add_note" in request.POST:
            note_form = forms.PondNoteForm(request.POST)
            if note_form.is_valid():
                note_form.save()
                messages.success(request, "Note added.")
                return redirect("farm:pond_detail", pk=pond.pk)

    return render(request, "farm/pond_detail.html", {
        "pond": pond,
        "is_guest": is_guest,
        "batches": batches,
        "latest_weather": latest_weather,
        "pond_notes": pond_notes,
        "active_alerts": active_alerts,
        "note_form": note_form,
    })


# ─────────────────────────────────────────────────────────────────────────────
# Batch detail — PUBLIC (read-only) — FEATURE 1: Enhanced with growth charts
# ─────────────────────────────────────────────────────────────────────────────

"""
batch_detail view — updated to use ML prediction alongside formula prediction.

Replace the existing batch_detail() function in farm/views.py with this one.
Also add this import at the top of views.py:

    from .services import ml_predict_batch_growth
"""

def batch_detail(request, pk):
    from .services import ml_predict_batch_growth   # ML import

    is_guest = not request.user.is_authenticated
    if is_guest:
        batch = get_object_or_404(FishBatch, pk=pk)
    else:
        batch = get_object_or_404(FishBatch, pk=pk, pond__owner=request.user)

    growth_records = batch.growth_records.all()
    feed_logs      = batch.feed_logs.all()
    latest_weather = WeatherRecord.objects.filter(pond=batch.pond).order_by("-timestamp").first()
    today          = timezone.now().date()
    today_feed_log = feed_logs.filter(date=today).first()

    auto_feed_kg  = smart_feed_kg_for_batch(batch)
    assumed_fcr   = float(getattr(settings, "DEFAULT_FCR", 1.5))
    projected_gain_kg = projected_next_avg_weight_g = None
    if auto_feed_kg is not None:
        projected_gain_kg           = projected_weight_gain_kg(auto_feed_kg, assumed_fcr)
        projected_next_avg_weight_g = projected_avg_weight_g(batch, auto_feed_kg, assumed_fcr)

    # ── Formula-based prediction (original) ───────────────────────────────────
    ai_prediction = predict_batch_growth(batch, feed_kg=auto_feed_kg)

    # ── ML-based prediction (new) ─────────────────────────────────────────────
    try:
        ml_prediction = ml_predict_batch_growth(batch)
    except Exception:
        ml_prediction = None

    mortality_logs  = batch.mortality_logs.all()[:10]
    total_mortality = batch.mortality_logs.aggregate(total=Sum("count"))["total"] or 0
    harvests        = batch.harvests.all()

    # ── Growth chart data ──────────────────────────────────────────────────────
    growth_list = list(growth_records.order_by("date"))
    growth_labels        = [str(r.date) for r in growth_list]
    growth_weight_values = [float(r.avg_weight_g) for r in growth_list]
    growth_count_values  = [r.surviving_count for r in growth_list]

    first_record    = growth_list[0] if growth_list else None
    latest_record   = growth_list[-1] if growth_list else None
    starting_weight = float(first_record.avg_weight_g) if first_record else float(batch.initial_avg_weight_g)
    current_weight  = float(latest_record.avg_weight_g) if latest_record else float(batch.initial_avg_weight_g)
    weight_gain_g   = round(current_weight - starting_weight, 2)
    weight_gain_pct = round((weight_gain_g / starting_weight * 100) if starting_weight > 0 else 0, 1)
    current_count   = latest_record.surviving_count if latest_record else batch.initial_count
    survival_rate   = round((current_count / batch.initial_count * 100) if batch.initial_count > 0 else 0, 1)

    if request.method == "POST" and not is_guest:
        form = forms.FeedLogForm(request.POST, batch=batch, initial_amount_kg=auto_feed_kg)
        if form.is_valid():
            form.save()
            FeedingReminder.objects.get_or_create(
                batch=batch,
                scheduled_for=timezone.now() + timedelta(hours=24),
                defaults={"message": "Time to feed this batch again."},
            )
            messages.success(request, "Feeding log saved.")
            return redirect("farm:batch_detail", pk=batch.pk)
    else:
        form = forms.FeedLogForm(batch=batch, initial_amount_kg=auto_feed_kg) if not is_guest else None

    return render(request, "farm/batch_detail.html", {
        "is_guest":                  is_guest,
        "batch":                     batch,
        "growth_records":            growth_records,
        "feed_logs":                 feed_logs,
        "latest_weather":            latest_weather,
        "auto_feed_kg":              auto_feed_kg,
        "assumed_fcr":               assumed_fcr,
        "projected_gain_kg":         projected_gain_kg,
        "projected_next_avg_weight_g": projected_next_avg_weight_g,
        "ai_prediction":             ai_prediction,
        "ml_prediction":             ml_prediction,       # ← নতুন
        "today_feed_log":            today_feed_log,
        "feed_form":                 form,
        "mortality_logs":            mortality_logs,
        "total_mortality":           total_mortality,
        "harvests":                  harvests,
        "growth_labels":             growth_labels,
        "growth_weight_values":      growth_weight_values,
        "growth_count_values":       growth_count_values,
        "starting_weight":           starting_weight,
        "current_weight":            current_weight,
        "weight_gain_g":             weight_gain_g,
        "weight_gain_pct":           weight_gain_pct,
        "survival_rate":             survival_rate,
        "current_count":             current_count,
    })

# ── Benchmark Dashboard ───────────────────────────────────────────────────────
@login_required
def benchmark_dashboard(request):
    """
    Performance benchmarking dashboard for research paper data collection.
    Shows response times, DB query counts, memory usage, and ML timing.
    """
    from .services.benchmarking import get_benchmark_stats_for_paper
 
    stats = get_benchmark_stats_for_paper()
 
    # Recent performance logs (last 100)
    from .models import PerformanceLog, BenchmarkRun
    recent_logs  = PerformanceLog.objects.order_by("-created_at")[:100]
    recent_runs  = BenchmarkRun.objects.order_by("-created_at")[:5]
 
    return render(request, "farm/benchmark_dashboard.html", {
        "stats":       stats,
        "recent_logs": recent_logs,
        "recent_runs": recent_runs,
        "page_title":  "Performance Benchmarking",
    })
 
 
@require_POST
@login_required
def run_benchmark_view(request):
    """
    Trigger a full benchmark suite run.
    POST /benchmark/run/
    """
    from .services.benchmarking import run_full_benchmark
 
    try:
        n_iter = int(request.POST.get("iterations", 10))
        n_iter = max(3, min(n_iter, 50))   # clamp 3–50
 
        suite  = run_full_benchmark(n_iterations=n_iter)
        messages.success(
            request,
            f"✅ Benchmark complete — {len(suite.results)} operations measured. "
            f"Avg response: {suite.summary.get('avg_response_ms', 0):.1f}ms"
        )
    except Exception as e:
        messages.error(request, f"Benchmark failed: {e}")
 
    return redirect("farm:benchmark_dashboard")
 
 
@login_required
def benchmark_export_json(request):
    """Export all benchmark data as JSON for paper analysis."""
    import json
    from django.http import JsonResponse
    from .models import PerformanceLog, BenchmarkRun
 
    logs = list(PerformanceLog.objects.values())
    runs = list(BenchmarkRun.objects.values())
 
    data = {
        "performance_logs": logs,
        "benchmark_runs":   runs,
        "exported_at":      timezone.now().isoformat(),
    }
    response = JsonResponse(data, safe=False, json_dumps_params={"indent": 2})
    response["Content-Disposition"] = 'attachment; filename="aquasmart_benchmark.json"'
    return response
# ─────────────────────────────────────────────────────────────────────────────
# Read-only report views — PUBLIC
# ─────────────────────────────────────────────────────────────────────────────

def reminder_list(request):
    if request.user.is_authenticated:
        reminders = _user_reminders(request.user).order_by("scheduled_for")
    else:
        reminders = FeedingReminder.objects.none()
    return render(request, "farm/reminder_list.html", {"reminders": reminders, "is_guest": not request.user.is_authenticated})


def daily_feed_report(request):
    today   = timezone.now().date()
    if not request.user.is_authenticated:
        return render(request, "farm/daily_feed_report.html", {"today": today, "rows": [], "is_guest": True})
    user    = request.user
    batches = _user_batches(user).select_related("pond").prefetch_related("growth_records")
    rows    = []
    for batch in batches:
        biomass_kg     = batch.latest_biomass_kg
        latest_weather = WeatherRecord.objects.filter(pond=batch.pond).order_by("-timestamp").first()
        temp           = latest_weather.water_temp_c if latest_weather else None
        suggested      = smart_feed_kg_for_batch(batch)
        rows.append({
            "pond": batch.pond,
            "batch": batch,
            "biomass_kg": biomass_kg,
            "temperature": temp,
            "suggested_feed_kg": suggested,
        })
    return render(request, "farm/daily_feed_report.html", {"today": today, "rows": rows})


def harvest_list(request):
    is_guest = not request.user.is_authenticated
    harvests  = _user_harvests(request.user).select_related("batch__pond") if not is_guest else HarvestRecord.objects.none()
    total_rev = sum(h.gross_revenue for h in harvests)
    total_kg  = harvests.aggregate(kg=Sum("total_weight_kg"))["kg"] or 0
    return render(request, "farm/harvest_list.html", {
        "is_guest": is_guest,
        "harvests": harvests,
        "total_revenue": round(total_rev, 2),
        "total_kg": total_kg,
    })


def expense_list(request):
    is_guest = not request.user.is_authenticated
    expenses = _user_expenses(request.user).select_related("pond") if not is_guest else Expense.objects.none()
    total    = expenses.aggregate(t=Sum("amount"))["t"] or 0
    by_cat   = (
        expenses.values("category").annotate(total=Sum("amount")).order_by("-total")
    )
    return render(request, "farm/expense_list.html", {
        "is_guest": is_guest,
        "expenses": expenses,
        "total": total,
        "by_cat": by_cat,
    })


def alert_list(request):
    is_guest         = not request.user.is_authenticated
    show_resolved    = request.GET.get("resolved") == "1"
    if is_guest:
        alerts           = FarmAlert.objects.none()
        unresolved_count = 0
    else:
        alerts           = _user_alerts(request.user).select_related("pond").filter(resolved=show_resolved)
        unresolved_count = _user_alerts(request.user).filter(resolved=False).count()
    return render(request, "farm/alert_list.html", {
        "is_guest": is_guest,
        "alerts": alerts,
        "show_resolved": show_resolved,
        "unresolved_count": unresolved_count,
    })


def profit_loss_report(request):
    """
    FEATURE 2: Enhanced profit/loss report.
    FIX: `user` was referenced inside the `else` branch but never assigned,
    causing a NameError for every authenticated visitor.
    """
    is_guest  = not request.user.is_authenticated
    today     = timezone.now().date()
    month_str = request.GET.get("month", today.strftime("%Y-%m"))
    try:
        year, month = int(month_str.split("-")[0]), int(month_str.split("-")[1])
    except Exception:
        year, month = today.year, today.month
 
    start = date(year, month, 1)
    end   = date(year + 1, 1, 1) if month == 12 else date(year, month + 1, 1)
 
    # FIX: define user here, before it is used in either branch
    user = request.user if not is_guest else None
 
    if is_guest:
        harvests_qs   = HarvestRecord.objects.none()
        revenue       = 0
        expenses_qs   = Expense.objects.none()
        total_expense = 0.0
        feed_qs       = FeedLog.objects.none()
        feed_kg       = 0.0
    else:
        harvests_qs   = _user_harvests(user).filter(
            harvest_date__gte=start, harvest_date__lt=end
        ).select_related("batch__pond")
        revenue       = sum(h.gross_revenue for h in harvests_qs)
        expenses_qs   = _user_expenses(user).filter(date__gte=start, date__lt=end)
        total_expense = float(expenses_qs.aggregate(t=Sum("amount"))["t"] or 0)
        feed_qs       = _user_feed_logs(user).filter(date__gte=start, date__lt=end)
        feed_kg       = float(feed_qs.aggregate(kg=Sum("feed_amount_kg"))["kg"] or 0)
 
    feed_cost_per_kg = float(getattr(settings, "FEED_COST_PER_KG", 1.2))
    feed_cost     = round(feed_kg * feed_cost_per_kg, 2)
    total_cost    = round(total_expense + feed_cost, 2)
    net_profit    = round(revenue - total_cost, 2)
    margin_pct    = round((net_profit / revenue * 100) if revenue > 0 else 0, 1)
 
    by_category   = list(
        expenses_qs.values("category")
        .annotate(total=Sum("amount"))
        .order_by("-total")
    )
 
    # ── Expense doughnut chart data ───────────────────────────────────────────
    expense_cat_labels = []
    expense_cat_values = []
    if feed_cost > 0:
        expense_cat_labels.append("Feed (calculated)")
        expense_cat_values.append(round(feed_cost, 2))
    for row in by_category:
        expense_cat_labels.append(row["category"].replace("_", " ").title())
        expense_cat_values.append(round(float(row["total"]), 2))
 
    # ── 6-month trend data ────────────────────────────────────────────────────
    monthly_trend = []
    if not is_guest:
        for i in range(5, -1, -1):
            m_start = (today.replace(day=1) - timedelta(days=i * 30)).replace(day=1)
            m_end   = (
                date(m_start.year + 1, 1, 1)
                if m_start.month == 12
                else date(m_start.year, m_start.month + 1, 1)
            )
            m_rev   = sum(
                h.gross_revenue for h in
                _user_harvests(user).filter(harvest_date__gte=m_start, harvest_date__lt=m_end)
            )
            m_exp   = float(
                _user_expenses(user)
                .filter(date__gte=m_start, date__lt=m_end)
                .aggregate(t=Sum("amount"))["t"] or 0
            )
            m_feed_kg = float(
                _user_feed_logs(user)
                .filter(date__gte=m_start, date__lt=m_end)
                .aggregate(kg=Sum("feed_amount_kg"))["kg"] or 0
            )
            m_feed_cost = round(m_feed_kg * feed_cost_per_kg, 2)
            m_cost  = round(m_exp + m_feed_cost, 2)
            monthly_trend.append({
                "label":     m_start.strftime("%b %Y"),
                "revenue":   round(m_rev, 2),
                "cost":      m_cost,
                "profit":    round(m_rev - m_cost, 2),
                "feed_cost": m_feed_cost,
                "other_exp": round(m_exp, 2),
            })
 
    # ── Combined transaction list ─────────────────────────────────────────────
    transactions = []
    for h in harvests_qs:
        transactions.append({
            "date":        h.harvest_date,
            "type":        "revenue",
            "description": f"Harvest — {h.batch}",
            "amount":      round(h.gross_revenue, 2),
            "sign":        "+",
        })
    for exp in expenses_qs:
        transactions.append({
            "date":        exp.date,
            "type":        "expense",
            "description": f"{exp.get_category_display()} — {exp.description}",
            "amount":      float(exp.amount),
            "sign":        "−",
        })
    transactions.sort(key=lambda x: x["date"], reverse=True)
 
    return render(request, "farm/profit_loss.html", {
        "is_guest":          is_guest,
        "month_str":         month_str,
        "start":             start,
        "end":               end,
        "harvests":          harvests_qs,
        "expenses":          expenses_qs,
        "revenue":           round(revenue, 2),
        "feed_cost":         feed_cost,
        "feed_kg":           round(feed_kg, 2),
        "total_expense":     total_expense,
        "total_cost":        total_cost,
        "net_profit":        net_profit,
        "margin_pct":        margin_pct,
        "by_category":       by_category,
        "monthly_trend":     monthly_trend,
        "expense_cat_labels": expense_cat_labels,
        "expense_cat_values": expense_cat_values,
        "transactions":      transactions,
    })

# ─────────────────────────────────────────────────────────────────────────────
# FEATURE 3: Mortality Report — PUBLIC (read-only)
# ─────────────────────────────────────────────────────────────────────────────

def mortality_report(request):
    """
    Dedicated mortality tracking page with:
    - Monthly summary (total deaths, mortality rate, most common cause)
    - Doughnut chart — deaths by cause
    - Line chart — monthly trend (last 6 months)
    - Full mortality log table with color coding
    """
    today = timezone.now().date()
    month_str = request.GET.get("month", today.strftime("%Y-%m"))
    try:
        year, month = int(month_str.split("-")[0]), int(month_str.split("-")[1])
    except Exception:
        year, month = today.year, today.month

    start = date(year, month, 1)
    end   = date(year + 1, 1, 1) if month == 12 else date(year, month + 1, 1)

    # ── All mortality logs (for full table) ───────────────────────────────────
    is_guest = not request.user.is_authenticated
    user     = request.user if not is_guest else None

    if is_guest:
        all_logs           = MortalityLog.objects.none()
        total_deaths_month = 0
        total_initial      = 1
    else:
        all_logs = (
            _user_mortality_logs(user)
            .select_related("batch__pond")
            .order_by("-date")
        )
        # ── This month's logs ─────────────────────────────────────────────────
        month_logs = all_logs.filter(date__gte=start, date__lt=end)
        total_deaths_month = month_logs.aggregate(t=Sum("count"))["t"] or 0
        total_initial      = _user_batches(user).aggregate(t=Sum("initial_count"))["t"] or 1
    mortality_rate_pct = round(total_deaths_month / total_initial * 100, 2) if total_initial else 0

    # Most common cause this month
    cause_agg = (
        month_logs.values("cause")
        .annotate(total=Sum("count"))
        .order_by("-total")
    )
    most_common_cause = cause_agg[0]["cause"] if cause_agg else None
    most_common_cause_label = dict(MortalityLog.CAUSE_CHOICES).get(most_common_cause, "—") if most_common_cause else "—"

    # ── Deaths by cause (doughnut chart) ──────────────────────────────────────
    cause_labels = []
    cause_values = []
    for row in cause_agg:
        cause_labels.append(dict(MortalityLog.CAUSE_CHOICES).get(row["cause"], row["cause"]))
        cause_values.append(row["total"])

    # ── Monthly trend (last 6 months) ─────────────────────────────────────────
    trend_labels  = []
    trend_values  = []
    pond_breakdown  = []
    all_cause_agg   = []
    total_deaths_all = 0

    if not is_guest:
        for i in range(5, -1, -1):
            m_start = (today.replace(day=1) - timedelta(days=i * 30)).replace(day=1)
            m_end   = date(m_start.year + 1, 1, 1) if m_start.month == 12 else date(m_start.year, m_start.month + 1, 1)
            deaths  = _user_mortality_logs(user).filter(date__gte=m_start, date__lt=m_end).aggregate(t=Sum("count"))["t"] or 0
            trend_labels.append(m_start.strftime("%b %Y"))
            trend_values.append(deaths)

        # ── Deaths by pond (for additional breakdown) ─────────────────────────
        pond_breakdown = (
            month_logs.values("batch__pond__name")
            .annotate(total=Sum("count"))
            .order_by("-total")
        )

        # ── All-time totals by cause ───────────────────────────────────────────
        all_cause_agg = (
            all_logs.values("cause")
            .annotate(total=Sum("count"))
            .order_by("-total")
        )
        total_deaths_all = all_logs.aggregate(t=Sum("count"))["t"] or 0

    return render(request, "farm/mortality_report.html", {
        "is_guest": is_guest,
        "month_str": month_str,
        "start": start,
        "end": end,
        "total_deaths_month": total_deaths_month,
        "mortality_rate_pct": mortality_rate_pct,
        "most_common_cause_label": most_common_cause_label,
        "cause_labels": cause_labels,
        "cause_values": cause_values,
        "trend_labels": trend_labels,
        "trend_values": trend_values,
        "all_logs": all_logs,
        "month_logs": month_logs,
        "pond_breakdown": pond_breakdown,
        "all_cause_agg": all_cause_agg,
        "total_deaths_all": total_deaths_all,
        "cause_choices": MortalityLog.CAUSE_CHOICES,
    })


# ─────────────────────────────────────────────────────────────────────────────
# Write views — LOGIN REQUIRED
# ─────────────────────────────────────────────────────────────────────────────

@login_required
def weather_create(request):
    if request.method == "POST":
        form = forms.WeatherRecordForm(request.POST, user=request.user)
        if form.is_valid():
            record = form.save()
            _generate_water_alerts(record, request.user)
            messages.success(request, "Water record saved. Alerts checked.")
            return redirect("farm:dashboard")
    else:
        form = forms.WeatherRecordForm(user=request.user)
    return render(request, "farm/simple_form.html", {"form": form, "title": "Log Water Quality"})


@login_required
def growth_create(request):
    if request.method == "POST":
        form = forms.GrowthRecordForm(request.POST, user=request.user)
        if form.is_valid():
            form.save()
            messages.success(request, "Growth record saved.")
            return redirect("farm:dashboard")
    else:
        form = forms.GrowthRecordForm(user=request.user)
    return render(request, "farm/simple_form.html", {"form": form, "title": "Log Growth"})


@login_required
def feed_log_create(request):
    if request.method == "POST":
        form = forms.FeedLogForm(request.POST, user=request.user)
        if form.is_valid():
            form.save()
            messages.success(request, "Feed log saved.")
            return redirect("farm:dashboard")
    else:
        form = forms.FeedLogForm(user=request.user)
    return render(request, "farm/simple_form.html", {"form": form, "title": "Log Feed"})


@login_required
def harvest_create(request):
    if request.method == "POST":
        form = forms.HarvestRecordForm(request.POST, user=request.user)
        if form.is_valid():
            form.save()
            messages.success(request, "Harvest record saved.")
            return redirect("farm:harvest_list")
    else:
        form = forms.HarvestRecordForm(user=request.user)
    return render(request, "farm/simple_form.html", {"form": form, "title": "Log Harvest"})


@login_required
def expense_create(request):
    if request.method == "POST":
        form = forms.ExpenseForm(request.POST, user=request.user)
        if form.is_valid():
            form.save()
            messages.success(request, "Expense recorded.")
            return redirect("farm:expense_list")
    else:
        form = forms.ExpenseForm(user=request.user)
    return render(request, "farm/simple_form.html", {"form": form, "title": "Add Expense"})


@login_required
def mortality_create(request):
    if request.method == "POST":
        form = forms.MortalityLogForm(request.POST, user=request.user)
        if form.is_valid():
            ml = form.save()
            if ml.count > 50:
                FarmAlert.objects.create(
                    pond=ml.batch.pond,
                    alert_type="high_mortality",
                    level="critical",
                    message=(
                        f"High mortality event: {ml.count} fish lost in {ml.batch} "
                        f"({ml.get_cause_display()}) on {ml.date}."
                    ),
                )
            messages.success(request, "Mortality log saved.")
            return redirect("farm:batch_detail", pk=ml.batch.pk)
    else:
        form = forms.MortalityLogForm(user=request.user)
    return render(request, "farm/simple_form.html", {"form": form, "title": "Log Mortality"})


@require_POST
@login_required
def alert_resolve(request, pk):
    # Ensure the alert belongs to this user's pond
    alert = get_object_or_404(FarmAlert, pk=pk, pond__owner=request.user)
    alert.resolve()
    messages.success(request, "Alert resolved.")
    return redirect("farm:alert_list")


@login_required
def send_test_alert(request):
    if request.method != "POST":
        return redirect("farm:dashboard")
    try:
        send_daily_feed_alert.delay()
        messages.success(request, "Test alert queued successfully.")
    except Exception:
        send_daily_feed_alert()
        messages.warning(request, "Broker unavailable — sent synchronously.")
    return redirect("farm:dashboard")


@require_POST
@login_required
def refresh_weather_view(request):
    try:
        from farm.models import FarmProfile
        from .services.weather_ingest import get_weather_for_location, get_weather_by_city
        fp = request.user.farm_profile
        data = None

        if fp.latitude and fp.longitude:
            data = get_weather_for_location(
                float(fp.latitude), float(fp.longitude)
            )
        elif fp.district:
            location_query = f"{fp.upazila},{fp.district},BD" if fp.upazila else f"{fp.district},BD"
            data = get_weather_by_city(location_query)

        if data:
            from django.utils import timezone
            fp.weather_temp_c       = data["temp_c"]
            fp.weather_humidity_pct = data["humidity"]
            fp.weather_rain_mm      = data["rain_mm"]
            fp.weather_condition    = data["condition"]
            fp.weather_fetched_at   = timezone.now()
            fp.save()
            messages.success(request, "Weather updated successfully!")
        else:
            messages.error(request, "Could not fetch weather. Try again.")

    except Exception:
        messages.error(request, "Farm profile not found.")
    return redirect("farm:dashboard")


@require_POST
@login_required
def mark_feeding_done_view(request):
    """Mark a feeding reminder as done — only for this user's batches."""
    reminder_id = request.POST.get("reminder_id")
    if reminder_id:
        reminder = FeedingReminder.objects.filter(
            pk=reminder_id, batch__pond__owner=request.user
        ).first()
        if reminder:
            reminder.sent = True
            reminder.save()
            messages.success(request, "Feeding marked as done!")
    return redirect("farm:dashboard")

@staff_member_required
def benchmark_dashboard(request):
    """
    Performance benchmarking dashboard.
    শুধু Django superuser / staff দেখতে পারবে।
    Regular user চেষ্টা করলে → admin login page এ redirect হবে।
    """
    from .services.benchmarking import get_benchmark_stats_for_paper
    from .models import PerformanceLog, BenchmarkRun
 
    stats       = get_benchmark_stats_for_paper()
    recent_logs = PerformanceLog.objects.order_by("-created_at")[:100]
    recent_runs = BenchmarkRun.objects.order_by("-created_at")[:5]
 
    return render(request, "farm/benchmark_dashboard.html", {
        "stats":       stats,
        "recent_logs": recent_logs,
        "recent_runs": recent_runs,
    })
 
 
@staff_member_required
@require_POST
def run_benchmark_view(request):
    """Benchmark suite চালাও — admin only।"""
    from .services.benchmarking import run_full_benchmark
 
    try:
        n_iter = int(request.POST.get("iterations", 10))
        n_iter = max(3, min(n_iter, 50))
        suite  = run_full_benchmark(n_iterations=n_iter)
        messages.success(
            request,
            f"✅ Benchmark complete — {len(suite.results)} operations measured. "
            f"Avg response: {suite.summary.get('avg_response_ms', 0):.1f} ms"
        )
    except Exception as e:
        messages.error(request, f"Benchmark failed: {e}")
 
    return redirect("farm:benchmark_dashboard")
 
 
@staff_member_required
def benchmark_export_json(request):
    """Benchmark data JSON হিসেবে export করো — admin only।"""
    from django.http import JsonResponse
    from .models import PerformanceLog, BenchmarkRun
 
    data = {
        "performance_logs": list(PerformanceLog.objects.values()),
        "benchmark_runs":   list(BenchmarkRun.objects.values()),
        "exported_at":      timezone.now().isoformat(),
    }
    response = JsonResponse(data, safe=False, json_dumps_params={"indent": 2})
    response["Content-Disposition"] = 'attachment; filename="aquasmart_benchmark.json"'
    return response

# ── Analytics Dashboard ───────────────────────────────────────────────────────
 
@login_required
def analytics_dashboard(request):
    """
    Unified analytics page with:
      1. Predictive Alerts — temperature & mortality trends
      2. FCR Analytics     — feed efficiency ranking & history
      3. Water Quality Heatmap — 7-day multi-pond heatmap
    """
    from .services.predictive_alerts import (
        run_predictive_alerts,
        get_temperature_trend_data,
    )
    from .services.fcr_analytics import (
        get_feed_efficiency_ranking,
        get_fcr_history,
        calculate_batch_fcr,
    )
    from .services.water_heatmap import build_water_quality_heatmap
    import json
 
    user = request.user
 
    # ── 1. Run predictive alerts ──────────────────────────────────────────────
    new_alerts_count = 0
    try:
        new_alerts_count = run_predictive_alerts(user=user)
    except Exception as e:
        logger.warning(f"[Analytics] Predictive alert error: {e}")
 
    # Get all unresolved predictive alerts for this user
    predictive_alerts = (
        _user_alerts(user)
        .filter(resolved=False, message__contains="PREDICTIVE")
        .order_by("-created_at")[:20]
    )
 
    # ── 2. Temperature trend for each pond ────────────────────────────────────
    ponds = _user_ponds(user)
    temp_trends = []
    for pond in ponds:
        try:
            trend = get_temperature_trend_data(pond, days=7)
            if trend["labels"]:
                trend["pond_name"] = pond.name
                trend["pond_id"]   = pond.id
                temp_trends.append(trend)
        except Exception:
            pass
 
    # ── 3. FCR Analytics ──────────────────────────────────────────────────────
    fcr_ranking = []
    try:
        fcr_ranking = get_feed_efficiency_ranking(user=user)
    except Exception as e:
        logger.warning(f"[Analytics] FCR ranking error: {e}")
 
    # FCR history for the best batch (lowest FCR)
    fcr_history_data = None
    best_batch       = None
    if fcr_ranking:
        try:
            from .models import FishBatch
            best_batch_id = fcr_ranking[0]["batch_id"]
            best_batch    = FishBatch.objects.get(pk=best_batch_id)
            from .services.fcr_analytics import get_fcr_history
            fcr_history_data = get_fcr_history(best_batch, weeks=8)
        except Exception as e:
            logger.warning(f"[Analytics] FCR history error: {e}")
 
    # ── 4. Water Quality Heatmap ──────────────────────────────────────────────
    heatmap_data = {}
    try:
        heatmap_data = build_water_quality_heatmap(user=user, days=7)
    except Exception as e:
        logger.warning(f"[Analytics] Heatmap error: {e}")
 
    # ── Prepare JSON for template ─────────────────────────────────────────────
    temp_trend_json = {}
    if temp_trends:
        # Use first pond's trend for main chart
        t = temp_trends[0]
        temp_trend_json = {
            "labels":        t["labels"] + t.get("proj_labels", []),
            "temps":         t["temps"],
            "proj_temps":    t.get("proj_temps", []),
            "do_values":     t["do_values"],
            "warning_line":  t.get("warning_line", 31),
            "critical_line": t.get("critical_line", 34),
            "slope":         t.get("slope", 0),
            "pond_name":     t.get("pond_name", ""),
        }
 
    fcr_chart_json = {}
    if fcr_history_data and fcr_history_data.get("has_data"):
        fcr_chart_json = {
            "labels":         fcr_history_data["labels"],
            "fcr_values":     fcr_history_data["fcr_values"],
            "feed_values":    fcr_history_data["feed_values"],
            "benchmark_low":  fcr_history_data["benchmark_low"],
            "benchmark_high": fcr_history_data["benchmark_high"],
            "species":        fcr_history_data["species"],
        }
 
    return render(request, "farm/analytics_dashboard.html", {
        # Predictive alerts
        "predictive_alerts":  predictive_alerts,
        "new_alerts_count":   new_alerts_count,
        "temp_trends":        temp_trends,
        "temp_trend_json":    json.dumps(temp_trend_json),
 
        # FCR analytics
        "fcr_ranking":        fcr_ranking,
        "fcr_history_data":   fcr_history_data,
        "fcr_chart_json":     json.dumps(fcr_chart_json),
        "best_batch":         best_batch,
 
        # Heatmap
        "heatmap_data":       heatmap_data,
        "heatmap_json":       json.dumps(heatmap_data, default=str),
 
        # Summary
        "total_ponds":        ponds.count(),
        "total_batches":      _user_batches(user).count(),
    })
 
 
# ── FCR detail for a single batch ─────────────────────────────────────────────
 
@login_required
def fcr_batch_detail(request, pk):
    """FCR history chart for a specific batch — AJAX JSON response."""
    from django.http import JsonResponse
    from .services.fcr_analytics import get_fcr_history, calculate_batch_fcr
 
    batch = get_object_or_404(FishBatch, pk=pk, pond__owner=request.user)
 
    fcr_data     = calculate_batch_fcr(batch)
    history_data = get_fcr_history(batch, weeks=8)
 
    return JsonResponse({
        "fcr_data":    fcr_data,
        "history":     history_data,
        "batch_name":  str(batch),
    })