from django.contrib import admin
from .models import (
    Pond, FishBatch, GrowthRecord, WeatherRecord, DailyWeather,
    FeedingProfile, FeedLog, FeedingReminder, SensorReading,
    HarvestRecord, Expense, MortalityLog, FarmAlert, PondNote,
)


@admin.register(Pond)
class PondAdmin(admin.ModelAdmin):
    list_display = ("name", "area_m2", "max_depth_m", "created_at")
    search_fields = ("name",)


@admin.register(FishBatch)
class FishBatchAdmin(admin.ModelAdmin):
    list_display = ("pond", "species", "stocking_date", "initial_count", "initial_avg_weight_g")
    list_filter = ("species", "pond")
    search_fields = ("pond__name",)


@admin.register(GrowthRecord)
class GrowthRecordAdmin(admin.ModelAdmin):
    list_display = ("batch", "date", "surviving_count", "avg_weight_g")
    list_filter = ("batch", "date")


@admin.register(WeatherRecord)
class WeatherRecordAdmin(admin.ModelAdmin):
    list_display = ("pond", "timestamp", "water_temp_c", "dissolved_oxygen_mg_l", "ph")
    list_filter = ("pond", "timestamp")


@admin.register(DailyWeather)
class DailyWeatherAdmin(admin.ModelAdmin):
    list_display = ("date", "temperature_c", "condition", "feed_percent")
    ordering = ("-date",)


@admin.register(FeedingProfile)
class FeedingProfileAdmin(admin.ModelAdmin):
    list_display = ("name", "min_temp_c", "max_temp_c", "feeding_rate_pct")


@admin.register(FeedLog)
class FeedLogAdmin(admin.ModelAdmin):
    list_display = ("batch", "date", "feed_amount_kg", "auto_calculated")
    list_filter = ("batch", "date")


@admin.register(FeedingReminder)
class FeedingReminderAdmin(admin.ModelAdmin):
    list_display = ("batch", "scheduled_for", "sent")
    list_filter = ("sent", "scheduled_for")


@admin.register(SensorReading)
class SensorReadingAdmin(admin.ModelAdmin):
    list_display = ("pond", "sensor_type", "value", "recorded_at", "source")
    list_filter = ("pond", "sensor_type", "recorded_at")


@admin.register(HarvestRecord)
class HarvestRecordAdmin(admin.ModelAdmin):
    list_display = ("batch", "harvest_date", "harvested_count", "total_weight_kg", "price_per_kg", "buyer_name")
    list_filter = ("harvest_date", "batch__pond")
    search_fields = ("batch__pond__name", "buyer_name")


@admin.register(Expense)
class ExpenseAdmin(admin.ModelAdmin):
    list_display = ("date", "category", "description", "amount", "pond")
    list_filter = ("category", "date", "pond")
    search_fields = ("description",)


@admin.register(MortalityLog)
class MortalityLogAdmin(admin.ModelAdmin):
    list_display = ("batch", "date", "count", "cause")
    list_filter = ("cause", "date")


@admin.register(FarmAlert)
class FarmAlertAdmin(admin.ModelAdmin):
    list_display = ("alert_type", "level", "pond", "resolved", "created_at")
    list_filter = ("level", "alert_type", "resolved")
    actions = ["mark_resolved"]

    def mark_resolved(self, request, queryset):
        from django.utils import timezone
        queryset.update(resolved=True, resolved_at=timezone.now())
    mark_resolved.short_description = "Mark selected alerts as resolved"


@admin.register(PondNote)
class PondNoteAdmin(admin.ModelAdmin):
    list_display = ("pond", "author", "created_at")
    list_filter = ("pond",)
