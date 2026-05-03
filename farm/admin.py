from django.contrib import admin
from .models import PerformanceLog, BenchmarkRun
from .models import (
    Pond, FishBatch, GrowthRecord, WeatherRecord, DailyWeather,
    FeedingProfile, FeedLog, FeedingReminder, SensorReading,
    HarvestRecord, Expense, MortalityLog, FarmAlert, PondNote, FarmProfile,
)


@admin.register(Pond)
class PondAdmin(admin.ModelAdmin):
    list_display = ("name", "owner", "area_m2", "max_depth_m", "created_at") # ✅ Added owner
    list_filter = ("owner",) # ✅ Filter option by user
    search_fields = ("name", "owner__email", "owner__username")


@admin.register(FishBatch)
class FishBatchAdmin(admin.ModelAdmin):
    list_display = ("pond", "species", "stocking_date", "initial_count", "initial_avg_weight_g", "get_owner") # ✅ Added owner
    list_filter = ("species", "pond__owner") # ✅ Filter by owner through pond
    search_fields = ("pond__name", "pond__owner__email")

    def get_owner(self, obj):
        return obj.pond.owner
    get_owner.short_description = "Owner"
    get_owner.admin_order_field = "pond__owner"


@admin.register(GrowthRecord)
class GrowthRecordAdmin(admin.ModelAdmin):
    list_display = ("batch", "date", "surviving_count", "avg_weight_g")
    list_filter = ("batch__pond__owner", "date") # ✅ Owner filter added
    date_hierarchy = "date" # ✅ Added calendar navigation


@admin.register(WeatherRecord)
class WeatherRecordAdmin(admin.ModelAdmin):
    list_display = ("pond", "timestamp", "water_temp_c", "dissolved_oxygen_mg_l", "ph", "source")
    list_filter = ("pond__owner", "source") # ✅ Owner filter added
    date_hierarchy = "timestamp" # ✅ Added calendar navigation


@admin.register(DailyWeather)
class DailyWeatherAdmin(admin.ModelAdmin):
    list_display = ("date", "temperature_c", "condition", "feed_percent")
    ordering = ("-date",)
    date_hierarchy = "date" # ✅ Added calendar navigation


@admin.register(FeedingProfile)
class FeedingProfileAdmin(admin.ModelAdmin):
    list_display = ("name", "min_temp_c", "max_temp_c", "feeding_rate_pct")


@admin.register(FeedLog)
class FeedLogAdmin(admin.ModelAdmin):
    list_display = ("batch", "date", "feed_amount_kg", "auto_calculated")
    list_filter = ("batch__pond__owner", "date") # ✅ Owner filter added
    date_hierarchy = "date" # ✅ Added calendar navigation


@admin.register(FeedingReminder)
class FeedingReminderAdmin(admin.ModelAdmin):
    list_display = ("batch", "scheduled_for", "sent")
    list_filter = ("sent", "batch__pond__owner") # ✅ Owner filter added


@admin.register(SensorReading)
class SensorReadingAdmin(admin.ModelAdmin):
    list_display = ("pond", "sensor_type", "value", "recorded_at", "source")
    list_filter = ("pond__owner", "sensor_type") # ✅ Owner filter added
    date_hierarchy = "recorded_at" # ✅ Added calendar navigation


@admin.register(HarvestRecord)
class HarvestRecordAdmin(admin.ModelAdmin):
    list_display = ("batch", "harvest_date", "harvested_count", "total_weight_kg", "price_per_kg", "buyer_name", "get_owner")
    list_filter = ("harvest_date", "batch__pond__owner") # ✅ Owner filter added
    search_fields = ("batch__pond__name", "buyer_name", "batch__pond__owner__email")
    date_hierarchy = "harvest_date" # ✅ Added calendar navigation

    def get_owner(self, obj):
        return obj.batch.pond.owner
    get_owner.short_description = "Owner"
    get_owner.admin_order_field = "batch__pond__owner"


@admin.register(Expense)
class ExpenseAdmin(admin.ModelAdmin):
    list_display = ("date", "category", "description", "amount", "pond", "get_owner")
    list_filter = ("category", "pond__owner") # ✅ Owner filter added
    search_fields = ("description", "pond__owner__email")
    date_hierarchy = "date" # ✅ Added calendar navigation

    def get_owner(self, obj):
        return obj.pond.owner
    get_owner.short_description = "Owner"
    get_owner.admin_order_field = "pond__owner"


@admin.register(MortalityLog)
class MortalityLogAdmin(admin.ModelAdmin):
    list_display = ("batch", "date", "count", "cause", "get_owner")
    list_filter = ("cause", "batch__pond__owner") # ✅ Owner filter added
    date_hierarchy = "date" # ✅ Added calendar navigation

    def get_owner(self, obj):
        return obj.batch.pond.owner
    get_owner.short_description = "Owner"
    get_owner.admin_order_field = "batch__pond__owner"


@admin.register(FarmAlert)
class FarmAlertAdmin(admin.ModelAdmin):
    list_display = ("alert_type", "level", "pond", "resolved", "created_at", "get_owner")
    list_filter = ("level", "alert_type", "resolved", "pond__owner") # ✅ Owner filter added
    search_fields = ("pond__name", "pond__owner__email", "message") # ✅ Message search added
    actions = ["mark_resolved"]

    def get_owner(self, obj):
        return obj.pond.owner
    get_owner.short_description = "Owner"
    get_owner.admin_order_field = "pond__owner"

    def mark_resolved(self, request, queryset):
        from django.utils import timezone
        queryset.update(resolved=True, resolved_at=timezone.now())
    mark_resolved.short_description = "Mark selected alerts as resolved"


@admin.register(PondNote)
class PondNoteAdmin(admin.ModelAdmin):
    list_display = ("pond", "author", "created_at")
    list_filter = ("pond__owner",) # ✅ Owner filter added


@admin.register(FarmProfile)
class FarmProfileAdmin(admin.ModelAdmin):
    list_display  = (
        "user", "farm_name", "size_acres", "num_ponds",
        "water_source", "location_display", "species_display",
        "farming_experience_years", "onboarding_complete", "created_at",
    )
    list_filter   = ("water_source", "onboarding_complete")
    search_fields = ("farm_name", "user__email", "district", "upazila")
    readonly_fields = (
        "created_at", "updated_at", "weather_fetched_at",
        "location_display", "species_display",
    )
 
    fieldsets = (
        ("Ownership", {
            "fields": ("user", "onboarding_complete"),
        }),
        ("Farm Basics (Step 1)", {
            "fields": ("farm_name", "size_acres", "num_ponds", "water_source"),
        }),
        ("Location (Step 2)", {
            "fields": ("latitude", "longitude", "district", "upazila", "location_display"),
        }),
        ("Fish Info (Step 3)", {
            "fields": ("species", "species_display", "farming_experience_years"),
        }),
        ("Cached Weather (Step 4)", {
            "fields": (
                "weather_temp_c", "weather_humidity_pct",
                "weather_rain_mm", "weather_condition", "weather_fetched_at",
            ),
        }),
        ("Timestamps", {
            "fields": ("created_at", "updated_at"),
            "classes": ("collapse",),
        }),
    )

@admin.register(PerformanceLog)
class PerformanceLogAdmin(admin.ModelAdmin):
    list_display  = ("endpoint", "method", "elapsed_ms", "db_query_count",
                     "memory_after_mb", "success", "created_at")
    list_filter   = ("endpoint", "method", "success")
    ordering      = ("-created_at",)
    readonly_fields = ("created_at",)
 
    def has_add_permission(self, request):
        return False   # logs are auto-generated only
 
 
@admin.register(BenchmarkRun)
class BenchmarkRunAdmin(admin.ModelAdmin):
    list_display  = ("suite_name", "total_operations", "created_at")
    ordering      = ("-created_at",)
    readonly_fields = ("created_at", "aggregated_results", "system_info", "summary")
 
    def has_add_permission(self, request):
        return False