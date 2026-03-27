from django.db import models
from django.utils import timezone


class Pond(models.Model):
    name = models.CharField(max_length=100, unique=True)
    area_m2 = models.DecimalField(max_digits=8, decimal_places=2, help_text="Surface area in square meters")
    max_depth_m = models.DecimalField(max_digits=5, decimal_places=2, help_text="Maximum depth in meters")
    created_at = models.DateTimeField(auto_now_add=True)

    def __str__(self) -> str:
        return self.name


class FishBatch(models.Model):
    SPECIES_CHOICES = [
        ("tilapia", "Tilapia"),
        ("catfish", "Catfish"),
        ("carp", "Carp"),
        ("other", "Other"),
    ]

    pond = models.ForeignKey(Pond, on_delete=models.CASCADE, related_name="batches")
    species = models.CharField(max_length=50, choices=SPECIES_CHOICES)
    stocking_date = models.DateField()
    initial_count = models.PositiveIntegerField()
    initial_avg_weight_g = models.DecimalField(
        max_digits=6,
        decimal_places=2,
        help_text="Average weight per fish at stocking (grams)",
    )
    target_harvest_date = models.DateField(blank=True, null=True)
    notes = models.TextField(blank=True)

    def __str__(self) -> str:
        return f"{self.get_species_display()} batch in {self.pond.name}"

    @property
    def current_age_days(self) -> int:
        return (timezone.now().date() - self.stocking_date).days

    @property
    def latest_biomass_kg(self) -> float:
        latest_growth = self.growth_records.order_by("-date").first()
        if not latest_growth:
            total_weight_g = self.initial_count * float(self.initial_avg_weight_g)
        else:
            total_weight_g = latest_growth.surviving_count * float(latest_growth.avg_weight_g)
        return total_weight_g / 1000.0


class GrowthRecord(models.Model):
    batch = models.ForeignKey(FishBatch, on_delete=models.CASCADE, related_name="growth_records")
    date = models.DateField(default=timezone.now)
    surviving_count = models.PositiveIntegerField()
    avg_weight_g = models.DecimalField(max_digits=7, decimal_places=2, help_text="Average weight per fish (grams)")

    class Meta:
        unique_together = ("batch", "date")
        ordering = ["date"]

    def __str__(self) -> str:
        return f"Growth {self.date} - {self.batch}"


class WeatherRecord(models.Model):
    pond = models.ForeignKey(Pond, on_delete=models.CASCADE, related_name="weather_records")
    timestamp = models.DateTimeField(default=timezone.now)
    water_temp_c = models.DecimalField(max_digits=4, decimal_places=1, help_text="Water temperature (°C)")
    dissolved_oxygen_mg_l = models.DecimalField(
        max_digits=4,
        decimal_places=2,
        help_text="Dissolved oxygen (mg/L)",
    )
    ph = models.DecimalField(max_digits=4, decimal_places=2, help_text="Water pH")
    rainfall_mm = models.DecimalField(max_digits=6, decimal_places=2, default=0, help_text="Rainfall (mm)")

    class Meta:
        ordering = ["-timestamp"]

    def __str__(self) -> str:
        return f"Weather {self.timestamp:%Y-%m-%d %H:%M} - {self.pond.name}"


class DailyWeather(models.Model):
    date = models.DateField(unique=True)
    location_query = models.CharField(max_length=100, default="")
    temperature_c = models.DecimalField(max_digits=4, decimal_places=1)
    condition = models.CharField(max_length=50)
    feed_percent = models.DecimalField(
        max_digits=5,
        decimal_places=2,
        help_text="Recommended feed percentage based on ambient weather",
    )
    raw_payload = models.JSONField(blank=True, null=True)

    class Meta:
        ordering = ["-date"]

    def __str__(self) -> str:
        return f"{self.date} [{self.location_query}] - {self.temperature_c} °C - {self.feed_percent}%"


class FeedingProfile(models.Model):
    name = models.CharField(max_length=100, unique=True)
    min_temp_c = models.DecimalField(max_digits=4, decimal_places=1, help_text="Minimum water temperature (°C)")
    max_temp_c = models.DecimalField(max_digits=4, decimal_places=1, help_text="Maximum water temperature (°C)")
    feeding_rate_pct = models.DecimalField(
        max_digits=4,
        decimal_places=2,
        help_text="Daily feed as % of biomass",
    )

    class Meta:
        ordering = ["min_temp_c"]

    def __str__(self) -> str:
        return f"{self.name} ({self.min_temp_c}-{self.max_temp_c} °C)"


class FeedLog(models.Model):
    batch = models.ForeignKey(FishBatch, on_delete=models.CASCADE, related_name="feed_logs")
    date = models.DateField(default=timezone.now)
    feed_amount_kg = models.DecimalField(max_digits=7, decimal_places=2)
    auto_calculated = models.BooleanField(default=True)

    class Meta:
        ordering = ["-date"]

    def __str__(self) -> str:
        return f"{self.date} feed for {self.batch}"


class FeedingReminder(models.Model):
    batch = models.ForeignKey(FishBatch, on_delete=models.CASCADE, related_name="feeding_reminders")
    scheduled_for = models.DateTimeField()
    message = models.CharField(max_length=255, default="Time to feed this batch.")
    sent = models.BooleanField(default=False)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["scheduled_for"]

    def __str__(self) -> str:
        return f"Reminder for {self.batch} at {self.scheduled_for}"


class SensorReading(models.Model):
    SENSOR_TYPE_CHOICES = [
        ("temperature", "Temperature"),
        ("oxygen", "Dissolved Oxygen"),
        ("ph", "pH"),
    ]

    pond = models.ForeignKey(Pond, on_delete=models.CASCADE, related_name="sensor_readings")
    sensor_type = models.CharField(max_length=20, choices=SENSOR_TYPE_CHOICES)
    value = models.DecimalField(max_digits=7, decimal_places=2)
    recorded_at = models.DateTimeField(default=timezone.now)
    source = models.CharField(max_length=50, default="iot")

    class Meta:
        ordering = ["-recorded_at"]

    def __str__(self) -> str:
        return f"{self.pond.name} {self.sensor_type}={self.value} at {self.recorded_at}"

