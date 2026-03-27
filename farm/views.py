from datetime import timedelta

from django.db.models import Avg, Sum
from django.db.models.functions import TruncDate
from django.contrib import messages
from django.conf import settings
from django.shortcuts import get_object_or_404, redirect, render
from django.utils import timezone

from .models import (
    FeedLog,
    FeedingProfile,
    FeedingReminder,
    FishBatch,
    GrowthRecord,
    Pond,
    WeatherRecord,
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


def dashboard(request):
    daily_api_weather = get_or_update_daily_weather()
    ponds = Pond.objects.all().annotate(
        total_biomass_kg=Sum("batches__growth_records__avg_weight_g")
    )
    active_batches = (
        FishBatch.objects.all()
        .prefetch_related("growth_records", "feed_logs")
        .order_by("pond__name", "stocking_date")
    )
    recent_feed = FeedLog.objects.order_by("-date")[:7]
    today = timezone.now().date()
    pending_reminders = FeedingReminder.objects.filter(
        scheduled_for__date=today, sent=False
    ).order_by("scheduled_for")
    feed_cost_per_kg = float(getattr(settings, "FEED_COST_PER_KG", 1.0))

    biomass_labels = []
    biomass_values = []
    for batch in active_batches:
        biomass_labels.append(f"{batch.pond.name} - {batch.get_species_display()}")
        biomass_values.append(round(batch.latest_biomass_kg, 2))

    mortality_labels = []
    mortality_values = []
    for batch in active_batches:
        latest_growth = batch.growth_records.order_by("-date").first()
        current_count = latest_growth.surviving_count if latest_growth else batch.initial_count
        if batch.initial_count > 0:
            mortality_pct = ((batch.initial_count - current_count) / batch.initial_count) * 100.0
        else:
            mortality_pct = 0.0
        mortality_labels.append(f"{batch.pond.name} - {batch.get_species_display()}")
        mortality_values.append(round(max(mortality_pct, 0.0), 2))

    feed_cost_labels = []
    feed_cost_values = []
    feed_consumption_values = []
    for log in reversed(recent_feed):
        feed_cost_labels.append(str(log.date))
        feed_cost_values.append(round(float(log.feed_amount_kg) * feed_cost_per_kg, 2))
        feed_consumption_values.append(round(float(log.feed_amount_kg), 2))

    # Weather trend (recent points)
    weather_points = list(
        WeatherRecord.objects.order_by("-timestamp").values("timestamp", "water_temp_c")[:14]
    )
    weather_points.reverse()
    weather_labels = [point["timestamp"].strftime("%Y-%m-%d") for point in weather_points]
    weather_temp_values = [float(point["water_temp_c"]) for point in weather_points]

    # Feed vs Growth correlation points
    feed_growth_points = []
    for batch in active_batches:
        feed_by_date = {log.date: float(log.feed_amount_kg) for log in batch.feed_logs.all()}
        for gr in batch.growth_records.all():
            feed_amount = feed_by_date.get(gr.date)
            if feed_amount is None:
                continue
            feed_growth_points.append({"x": round(feed_amount, 2), "y": float(gr.avg_weight_g)})
    feed_growth_points = feed_growth_points[-30:]

    # Temperature vs Appetite: appetite = feed / biomass (%)
    temp_appetite_points = []
    for batch in active_batches:
        growth_records = list(batch.growth_records.all().order_by("date"))
        if not growth_records:
            continue
        for log in batch.feed_logs.all().order_by("date"):
            matching_growth = None
            for gr in growth_records:
                if gr.date <= log.date:
                    matching_growth = gr
                else:
                    break
            if matching_growth is None or matching_growth.surviving_count <= 0:
                continue
            biomass_kg = (matching_growth.surviving_count * float(matching_growth.avg_weight_g)) / 1000.0
            if biomass_kg <= 0:
                continue
            weather = (
                WeatherRecord.objects.filter(pond=batch.pond, timestamp__date__lte=log.date)
                .order_by("-timestamp")
                .first()
            )
            if weather is None:
                continue
            appetite_pct = (float(log.feed_amount_kg) / biomass_kg) * 100.0
            temp_appetite_points.append({"x": float(weather.water_temp_c), "y": round(appetite_pct, 2)})
    temp_appetite_points = temp_appetite_points[-30:]

    total_ponds = ponds.count()
    total_batches = active_batches.count()
    reminders_today = pending_reminders.count()
    feed_last_7_days_kg = round(sum(float(log.feed_amount_kg) for log in recent_feed), 2)
    avg_recent_temp_c = (
        round(sum(weather_temp_values) / len(weather_temp_values), 1)
        if weather_temp_values
        else None
    )
    today_feed_given_kg = (
        FeedLog.objects.filter(date=today).aggregate(total=Sum("feed_amount_kg"))["total"] or 0
    )
    # Recommended feed for today based on today's temperature (DailyWeather)
    recommended_feed_today_kg = 0.0
    for batch in active_batches:
        suggested = smart_feed_kg_for_batch(batch, day=today)
        if suggested is not None:
            recommended_feed_today_kg += float(suggested)
    recommended_feed_today_kg = round(recommended_feed_today_kg, 2)

    # Daily operation summary: total feed per day + average water temperature per day
    feed_daily = list(
        FeedLog.objects.values("date")
        .annotate(total_feed_kg=Sum("feed_amount_kg"))
        .order_by("-date")[:14]
    )
    feed_daily.reverse()

    weather_daily = list(
        WeatherRecord.objects.annotate(day=TruncDate("timestamp"))
        .values("day")
        .annotate(avg_temp_c=Avg("water_temp_c"))
        .order_by("-day")[:21]
    )
    temp_by_day = {row["day"]: float(row["avg_temp_c"]) for row in weather_daily if row["day"] is not None}

    daily_feed_temp_rows = []
    for row in feed_daily:
        day = row["date"]
        recommended_feed_kg = 0.0
        has_any_reco = False
        for batch in active_batches:
            suggested = smart_feed_kg_for_batch(batch, day=day)
            if suggested is not None:
                recommended_feed_kg += float(suggested)
                has_any_reco = True
        daily_feed_temp_rows.append(
            {
                "date": day,
                "feed_kg": round(float(row["total_feed_kg"]), 2),
                "temp_c": round(temp_by_day[day], 1) if day in temp_by_day else None,
                "recommended_feed_kg": round(recommended_feed_kg, 2) if has_any_reco else None,
            }
        )
    target_actual_labels = [str(row["date"]) for row in daily_feed_temp_rows]
    target_actual_actual_values = [row["feed_kg"] for row in daily_feed_temp_rows]
    target_actual_target_values = [
        row["recommended_feed_kg"] if row["recommended_feed_kg"] is not None else None
        for row in daily_feed_temp_rows
    ]

    context = {
        "ponds": ponds,
        "active_batches": active_batches,
        "recent_feed": recent_feed,
        "pending_reminders": pending_reminders,
        "total_ponds": total_ponds,
        "total_batches": total_batches,
        "reminders_today": reminders_today,
        "feed_last_7_days_kg": feed_last_7_days_kg,
        "today_feed_given_kg": today_feed_given_kg,
        "recommended_feed_today_kg": recommended_feed_today_kg,
        "avg_recent_temp_c": avg_recent_temp_c,
        "daily_api_temp_c": daily_api_weather.temperature_c if daily_api_weather else None,
        "daily_api_condition": daily_api_weather.condition if daily_api_weather else None,
        "daily_api_feed_percent": daily_api_weather.feed_percent if daily_api_weather else None,
        "daily_api_date": daily_api_weather.date if daily_api_weather else today,
        "daily_api_location": daily_api_weather.location_query if daily_api_weather else None,
        "daily_feed_temp_rows": daily_feed_temp_rows,
        "target_actual_labels": target_actual_labels,
        "target_actual_actual_values": target_actual_actual_values,
        "target_actual_target_values": target_actual_target_values,
        "biomass_labels": biomass_labels,
        "biomass_values": biomass_values,
        "mortality_labels": mortality_labels,
        "mortality_values": mortality_values,
        "feed_cost_labels": feed_cost_labels,
        "feed_cost_values": feed_cost_values,
        "feed_consumption_values": feed_consumption_values,
        "weather_labels": weather_labels,
        "weather_temp_values": weather_temp_values,
        "feed_growth_points": feed_growth_points,
        "temp_appetite_points": temp_appetite_points,
    }
    return render(request, "farm/dashboard.html", context)


def pond_list(request):
    ponds = Pond.objects.all()
    return render(request, "farm/pond_list.html", {"ponds": ponds})


def pond_detail(request, pk: int):
    pond = get_object_or_404(Pond, pk=pk)
    batches = pond.batches.all().prefetch_related("growth_records")
    latest_weather = pond.weather_records.first()
    return render(
        request,
        "farm/pond_detail.html",
        {"pond": pond, "batches": batches, "latest_weather": latest_weather},
    )


def batch_detail(request, pk: int):
    batch = get_object_or_404(FishBatch, pk=pk)
    growth_records = batch.growth_records.all()
    feed_logs = batch.feed_logs.all()
    latest_weather = (
        WeatherRecord.objects.filter(pond=batch.pond).order_by("-timestamp").first()
    )
    today = timezone.now().date()
    today_feed_log = feed_logs.filter(date=today).first()

    # smart automatic feed calculation
    auto_feed_kg = smart_feed_kg_for_batch(batch)
    assumed_fcr = float(getattr(settings, "DEFAULT_FCR", 1.5))
    projected_gain_kg = None
    projected_next_avg_weight_g = None
    ai_prediction = None
    if auto_feed_kg is not None:
        projected_gain_kg = projected_weight_gain_kg(auto_feed_kg, assumed_fcr)
        projected_next_avg_weight_g = projected_avg_weight_g(batch, auto_feed_kg, assumed_fcr)
    ai_prediction = predict_batch_growth(batch, feed_kg=auto_feed_kg)

    if request.method == "POST":
        form = forms.FeedLogForm(request.POST, batch=batch, initial_amount_kg=auto_feed_kg)
        if form.is_valid():
            feed_log = form.save()
            FeedingReminder.objects.get_or_create(
                batch=batch,
                scheduled_for=timezone.now() + timedelta(hours=24),
                defaults={"message": "Time to feed this batch again."},
            )
            return redirect("farm:batch_detail", pk=batch.pk)
    else:
        form = forms.FeedLogForm(batch=batch, initial_amount_kg=auto_feed_kg)

    return render(
        request,
        "farm/batch_detail.html",
        {
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
        },
    )


def weather_create(request):
    if request.method == "POST":
        form = forms.WeatherRecordForm(request.POST)
        if form.is_valid():
            form.save()
            return redirect("farm:dashboard")
    else:
        form = forms.WeatherRecordForm()
    return render(request, "farm/simple_form.html", {"form": form, "title": "Log Weather"})


def growth_create(request):
    if request.method == "POST":
        form = forms.GrowthRecordForm(request.POST)
        if form.is_valid():
            form.save()
            return redirect("farm:dashboard")
    else:
        form = forms.GrowthRecordForm()
    return render(request, "farm/simple_form.html", {"form": form, "title": "Log Growth"})


def feed_log_create(request):
    if request.method == "POST":
        form = forms.FeedLogForm(request.POST)
        if form.is_valid():
            form.save()
            return redirect("farm:dashboard")
    else:
        form = forms.FeedLogForm()
    return render(request, "farm/simple_form.html", {"form": form, "title": "Log Feed"})


def reminder_list(request):
    reminders = FeedingReminder.objects.order_by("scheduled_for")
    return render(request, "farm/reminder_list.html", {"reminders": reminders})


def daily_feed_report(request):
    today = timezone.now().date()
    batches = (
        FishBatch.objects.all()
        .select_related("pond")
        .prefetch_related("growth_records")
    )

    rows = []
    for batch in batches:
        biomass_kg = batch.latest_biomass_kg
        latest_weather = (
            WeatherRecord.objects.filter(pond=batch.pond).order_by("-timestamp").first()
        )
        temp = latest_weather.water_temp_c if latest_weather else None
        suggested_feed_kg = smart_feed_kg_for_batch(batch)

        rows.append(
            {
                "pond": batch.pond,
                "batch": batch,
                "biomass_kg": biomass_kg,
                "temperature": temp,
                "suggested_feed_kg": suggested_feed_kg,
            }
        )

    context = {
        "today": today,
        "rows": rows,
    }
    return render(request, "farm/daily_feed_report.html", context)


def send_test_alert(request):
    if request.method != "POST":
        return redirect("farm:dashboard")

    try:
        send_daily_feed_alert.delay()
        messages.success(request, "Test alert queued successfully.")
    except Exception:
        # Fallback keeps testing possible even if broker is unavailable.
        send_daily_feed_alert()
        messages.warning(request, "Broker unavailable, sent test alert synchronously.")

    return redirect("farm:dashboard")

