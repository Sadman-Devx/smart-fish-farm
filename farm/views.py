"""
farm/views.py — Smart Fish Farm Management System
─────────────────────────────────────────────────
Access policy:
  • GET  (read)  → open to everyone including anonymous guests
  • POST (write) → @login_required (data-modifying actions)

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
"""
from datetime import timedelta, date
from decimal import Decimal

from django.db.models import Avg, Sum, Count, Q
from django.db.models.functions import TruncDate, TruncMonth
from django.contrib import messages
from django.conf import settings
from django.http import JsonResponse
from django.shortcuts import get_object_or_404, redirect, render
from django.utils import timezone
from django.views.decorators.http import require_POST
from django.contrib.auth.decorators import login_required

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
)
from .tasks import send_daily_feed_alert


# ─────────────────────────────────────────────────────────────────────────────
# Internal helpers
# ─────────────────────────────────────────────────────────────────────────────

def _generate_water_alerts(weather_record: WeatherRecord) -> None:
    """Auto-create FarmAlert entries when water readings are out of range."""
    pond = weather_record.pond
    temp = float(weather_record.water_temp_c)
    do   = float(weather_record.dissolved_oxygen_mg_l)
    ph   = float(weather_record.ph)

    checks = [
        (do < 4.0,              "low_oxygen", "critical", f"Pond {pond.name}: DO critically low at {do} mg/L (min 4.0)"),
        (do < 5.0,              "low_oxygen", "warning",  f"Pond {pond.name}: DO below optimum at {do} mg/L"),
        (temp > 34.0,           "high_temp",  "critical", f"Pond {pond.name}: Water temp critically high at {temp}°C"),
        (temp > 31.0,           "high_temp",  "warning",  f"Pond {pond.name}: Water temp elevated at {temp}°C"),
        (temp < 15.0,           "low_temp",   "warning",  f"Pond {pond.name}: Water temp low at {temp}°C — reduce feed"),
        (ph < 6.5 or ph > 9.0, "ph_out",     "warning",  f"Pond {pond.name}: pH out of range at {ph}"),
    ]

    for condition, atype, level, msg in checks:
        if condition:
            exists = FarmAlert.objects.filter(
                pond=pond, alert_type=atype, resolved=False
            ).exists()
            if not exists:
                FarmAlert.objects.create(
                    pond=pond, alert_type=atype, level=level, message=msg
                )


def _generate_harvest_due_alerts() -> None:
    """Create harvest-due alerts for batches within 7 days of estimated harvest."""
    for batch in FishBatch.objects.prefetch_related("growth_records"):
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
    Main dashboard. Accessible to guests (read-only).
    Both "Recommended feed today" KPI and the 14-day table column now
    always produce a value as long as a FeedingProfile is configured.
    """
    if request.user.is_authenticated:
        _generate_harvest_due_alerts()

    # ── Weather ────────────────────────────────────────────────────────────────
    daily_api_weather = get_or_update_daily_weather()

    # ── Core querysets ─────────────────────────────────────────────────────────
    ponds = Pond.objects.all().annotate(
        total_biomass_kg=Sum("batches__growth_records__avg_weight_g")
    )
    active_batches = (
        FishBatch.objects.all()
        .prefetch_related("growth_records", "feed_logs")
        .order_by("pond__name", "stocking_date")
    )
    recent_feed       = FeedLog.objects.order_by("-date")[:7]
    today             = timezone.now().date()
    pending_reminders = FeedingReminder.objects.filter(
        scheduled_for__date=today, sent=False
    ).order_by("scheduled_for")

    unresolved_alerts = FarmAlert.objects.filter(resolved=False).count()
    critical_alerts   = FarmAlert.objects.filter(resolved=False, level="critical")

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
    for log in reversed(list(recent_feed)):
        feed_cost_labels.append(str(log.date))
        feed_cost_values.append(round(float(log.feed_amount_kg) * feed_cost_per_kg, 2))
        feed_consumption_values.append(round(float(log.feed_amount_kg), 2))

    weather_points = list(
        WeatherRecord.objects.order_by("-timestamp").values("timestamp", "water_temp_c")[:14]
    )
    weather_points.reverse()
    weather_labels      = [p["timestamp"].strftime("%Y-%m-%d") for p in weather_points]
    weather_temp_values = [float(p["water_temp_c"]) for p in weather_points]

    # ── 14-day feed rows ───────────────────────────────────────────────────────
    feed_daily = list(
        FeedLog.objects.values("date")
        .annotate(total_feed_kg=Sum("feed_amount_kg"))
        .order_by("-date")[:14]
    )
    feed_daily.reverse()

    # Avg pond temperature per day (display only — does not affect calculation)
    weather_daily = list(
        WeatherRecord.objects.annotate(day=TruncDate("timestamp"))
        .values("day").annotate(avg_temp_c=Avg("water_temp_c")).order_by("-day")[:21]
    )
    temp_by_day = {r["day"]: float(r["avg_temp_c"]) for r in weather_daily if r["day"]}

    # ── FIX: recommended-feed column ──────────────────────────────────────────
    # smart_feed_kg_for_batch() now falls back through:
    #   exact DailyWeather → latest DailyWeather → pond WeatherRecord → 26°C
    # so it returns a real value for every past date that had no API record.
    daily_feed_temp_rows        = []
    target_actual_labels        = []
    target_actual_actual_values = []
    target_actual_target_values = []

    for row in feed_daily:
        day    = row["date"]
        rec_kg = 0.0
        for b in active_batches:
            val = smart_feed_kg_for_batch(b, day=day)
            if val is not None:
                rec_kg += val

        daily_feed_temp_rows.append({
            "date":                day,
            "feed_kg":             round(float(row["total_feed_kg"]), 2),
            "temp_c":              round(temp_by_day[day], 1) if day in temp_by_day else None,
            # Only show None (→ "—") if the service genuinely couldn't compute
            # (i.e. no FeedingProfile configured at all).
            "recommended_feed_kg": round(rec_kg, 2) if rec_kg > 0 else None,
        })
        target_actual_labels.append(str(day))
        target_actual_actual_values.append(round(float(row["total_feed_kg"]), 2))
        target_actual_target_values.append(round(rec_kg, 2) if rec_kg > 0 else None)

    # ── FIX: "Recommended feed today" KPI ─────────────────────────────────────
    today_feed_given_kg       = float(
        FeedLog.objects.filter(date=today).aggregate(total=Sum("feed_amount_kg"))["total"] or 0
    )
    recommended_feed_today_kg = 0.0
    recommended_feed_sources  = set()

    for batch in active_batches:
        suggested = smart_feed_kg_for_batch(batch, day=today)
        if suggested is not None:
            recommended_feed_today_kg += float(suggested)
            has_pond_weather = WeatherRecord.objects.filter(pond=batch.pond).exists()
            if has_pond_weather:
                recommended_feed_sources.add("pond")
            elif daily_api_weather:
                recommended_feed_sources.add("api")
            else:
                recommended_feed_sources.add("default")

    recommended_feed_today_kg = round(recommended_feed_today_kg, 2)

    # Source label shown in the weather bar pill
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
    )
    return render(request, "farm/dashboard.html", context)


# ─────────────────────────────────────────────────────────────────────────────
# Pond — PUBLIC (read-only)
# ─────────────────────────────────────────────────────────────────────────────

def pond_list(request):
    ponds = Pond.objects.all()
    return render(request, "farm/pond_list.html", {"ponds": ponds})


def pond_detail(request, pk):
    pond           = get_object_or_404(Pond, pk=pk)
    batches        = pond.batches.all().prefetch_related("growth_records")
    latest_weather = pond.weather_records.first()
    pond_notes     = pond.notes.all()[:10]
    active_alerts  = pond.alerts.filter(resolved=False)
    note_form      = forms.PondNoteForm(initial={"pond": pond})

    if request.method == "POST":
        if not request.user.is_authenticated:
            messages.error(request, "Please sign in to add notes.")
            return redirect("accounts:login")
        if "add_note" in request.POST:
            note_form = forms.PondNoteForm(request.POST)
            if note_form.is_valid():
                note_form.save()
                messages.success(request, "Note added.")
                return redirect("farm:pond_detail", pk=pond.pk)

    return render(request, "farm/pond_detail.html", {
        "pond": pond,
        "batches": batches,
        "latest_weather": latest_weather,
        "pond_notes": pond_notes,
        "active_alerts": active_alerts,
        "note_form": note_form,
    })


# ─────────────────────────────────────────────────────────────────────────────
# Batch detail — PUBLIC (read-only)
# ─────────────────────────────────────────────────────────────────────────────

def batch_detail(request, pk):
    batch          = get_object_or_404(FishBatch, pk=pk)
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
    ai_prediction = predict_batch_growth(batch, feed_kg=auto_feed_kg)

    mortality_logs  = batch.mortality_logs.all()[:10]
    total_mortality = batch.mortality_logs.aggregate(total=Sum("count"))["total"] or 0
    harvests        = batch.harvests.all()

    if request.method == "POST":
        if not request.user.is_authenticated:
            messages.error(request, "Please sign in to log feeding.")
            return redirect("accounts:login")
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
        form = forms.FeedLogForm(batch=batch, initial_amount_kg=auto_feed_kg)

    return render(request, "farm/batch_detail.html", {
        "batch": batch,
        "growth_records": growth_records,
        "feed_logs": feed_logs,
        "latest_weather": latest_weather,
        "auto_feed_kg": auto_feed_kg,
        "assumed_fcr": assumed_fcr,
        "projected_gain_kg": projected_gain_kg,
        "projected_next_avg_weight_g": projected_next_avg_weight_g,
        "ai_prediction": ai_prediction,
        "today_feed_log": today_feed_log,
        "feed_form": form,
        "mortality_logs": mortality_logs,
        "total_mortality": total_mortality,
        "harvests": harvests,
    })


# ─────────────────────────────────────────────────────────────────────────────
# Read-only report views — PUBLIC
# ─────────────────────────────────────────────────────────────────────────────

def reminder_list(request):
    reminders = FeedingReminder.objects.order_by("scheduled_for")
    return render(request, "farm/reminder_list.html", {"reminders": reminders})


def daily_feed_report(request):
    today   = timezone.now().date()
    batches = FishBatch.objects.all().select_related("pond").prefetch_related("growth_records")
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
    harvests  = HarvestRecord.objects.select_related("batch__pond").all()
    total_rev = sum(h.gross_revenue for h in harvests)
    total_kg  = harvests.aggregate(kg=Sum("total_weight_kg"))["kg"] or 0
    return render(request, "farm/harvest_list.html", {
        "harvests": harvests,
        "total_revenue": round(total_rev, 2),
        "total_kg": total_kg,
    })


def expense_list(request):
    expenses = Expense.objects.select_related("pond").all()
    total    = expenses.aggregate(t=Sum("amount"))["t"] or 0
    by_cat   = (
        expenses.values("category")
        .annotate(total=Sum("amount"))
        .order_by("-total")
    )
    return render(request, "farm/expense_list.html", {
        "expenses": expenses,
        "total": total,
        "by_cat": by_cat,
    })


def alert_list(request):
    show_resolved    = request.GET.get("resolved") == "1"
    alerts           = FarmAlert.objects.select_related("pond").filter(resolved=show_resolved)
    unresolved_count = FarmAlert.objects.filter(resolved=False).count()
    return render(request, "farm/alert_list.html", {
        "alerts": alerts,
        "show_resolved": show_resolved,
        "unresolved_count": unresolved_count,
    })


def profit_loss_report(request):
    today     = timezone.now().date()
    month_str = request.GET.get("month", today.strftime("%Y-%m"))
    try:
        year, month = int(month_str.split("-")[0]), int(month_str.split("-")[1])
    except Exception:
        year, month = today.year, today.month

    start = date(year, month, 1)
    end   = date(year + 1, 1, 1) if month == 12 else date(year, month + 1, 1)

    harvests_qs   = HarvestRecord.objects.filter(
        harvest_date__gte=start, harvest_date__lt=end
    ).select_related("batch__pond")
    revenue       = sum(h.gross_revenue for h in harvests_qs)

    expenses_qs   = Expense.objects.filter(date__gte=start, date__lt=end)
    total_expense = float(expenses_qs.aggregate(t=Sum("amount"))["t"] or 0)

    feed_qs       = FeedLog.objects.filter(date__gte=start, date__lt=end)
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

    monthly_trend = []
    for i in range(5, -1, -1):
        m_start = (today.replace(day=1) - timedelta(days=i * 30)).replace(day=1)
        m_end   = date(m_start.year + 1, 1, 1) if m_start.month == 12 else date(m_start.year, m_start.month + 1, 1)
        m_rev   = sum(
            h.gross_revenue for h in
            HarvestRecord.objects.filter(harvest_date__gte=m_start, harvest_date__lt=m_end)
        )
        m_exp   = float(Expense.objects.filter(date__gte=m_start, date__lt=m_end).aggregate(t=Sum("amount"))["t"] or 0)
        m_feed  = float(FeedLog.objects.filter(date__gte=m_start, date__lt=m_end).aggregate(kg=Sum("feed_amount_kg"))["kg"] or 0)
        m_cost  = round(m_exp + m_feed * feed_cost_per_kg, 2)
        monthly_trend.append({
            "label":   m_start.strftime("%b %Y"),
            "revenue": round(m_rev, 2),
            "cost":    m_cost,
            "profit":  round(m_rev - m_cost, 2),
        })

    return render(request, "farm/profit_loss.html", {
        "month_str": month_str,
        "start": start, "end": end,
        "harvests": harvests_qs,
        "expenses": expenses_qs,
        "revenue": round(revenue, 2),
        "feed_cost": feed_cost,
        "feed_kg": round(feed_kg, 2),
        "total_expense": total_expense,
        "total_cost": total_cost,
        "net_profit": net_profit,
        "margin_pct": margin_pct,
        "by_category": by_category,
        "monthly_trend": monthly_trend,
    })


# ─────────────────────────────────────────────────────────────────────────────
# Write views — LOGIN REQUIRED
# ─────────────────────────────────────────────────────────────────────────────

@login_required
def weather_create(request):
    if request.method == "POST":
        form = forms.WeatherRecordForm(request.POST)
        if form.is_valid():
            record = form.save()
            _generate_water_alerts(record)
            messages.success(request, "Water record saved. Alerts checked.")
            return redirect("farm:dashboard")
    else:
        form = forms.WeatherRecordForm()
    return render(request, "farm/simple_form.html", {"form": form, "title": "Log Water Quality"})


@login_required
def growth_create(request):
    if request.method == "POST":
        form = forms.GrowthRecordForm(request.POST)
        if form.is_valid():
            form.save()
            messages.success(request, "Growth record saved.")
            return redirect("farm:dashboard")
    else:
        form = forms.GrowthRecordForm()
    return render(request, "farm/simple_form.html", {"form": form, "title": "Log Growth"})


@login_required
def feed_log_create(request):
    if request.method == "POST":
        form = forms.FeedLogForm(request.POST)
        if form.is_valid():
            form.save()
            messages.success(request, "Feed log saved.")
            return redirect("farm:dashboard")
    else:
        form = forms.FeedLogForm()
    return render(request, "farm/simple_form.html", {"form": form, "title": "Log Feed"})


@login_required
def harvest_create(request):
    if request.method == "POST":
        form = forms.HarvestRecordForm(request.POST)
        if form.is_valid():
            form.save()
            messages.success(request, "Harvest record saved.")
            return redirect("farm:harvest_list")
    else:
        form = forms.HarvestRecordForm()
    return render(request, "farm/simple_form.html", {"form": form, "title": "Log Harvest"})


@login_required
def expense_create(request):
    if request.method == "POST":
        form = forms.ExpenseForm(request.POST)
        if form.is_valid():
            form.save()
            messages.success(request, "Expense recorded.")
            return redirect("farm:expense_list")
    else:
        form = forms.ExpenseForm()
    return render(request, "farm/simple_form.html", {"form": form, "title": "Add Expense"})


@login_required
def mortality_create(request):
    if request.method == "POST":
        form = forms.MortalityLogForm(request.POST)
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
        form = forms.MortalityLogForm()
    return render(request, "farm/simple_form.html", {"form": form, "title": "Log Mortality"})


@require_POST
@login_required
def alert_resolve(request, pk):
    alert = get_object_or_404(FarmAlert, pk=pk)
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