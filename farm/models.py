from django.db import models
from django.utils import timezone


# ── Pond ──────────────────────────────────────────────────────────────────────
class Pond(models.Model):
    name = models.CharField(max_length=100, unique=True)
    area_m2 = models.DecimalField(max_digits=8, decimal_places=2, help_text="Surface area in square meters")
    max_depth_m = models.DecimalField(max_digits=5, decimal_places=2, help_text="Maximum depth in meters")
    created_at = models.DateTimeField(auto_now_add=True)

    def __str__(self):
        return self.name


# ── FishBatch ─────────────────────────────────────────────────────────────────
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
        max_digits=6, decimal_places=2,
        help_text="Average weight per fish at stocking (grams)",
    )
    target_harvest_date = models.DateField(blank=True, null=True)
    notes = models.TextField(blank=True)

    def __str__(self):
        return f"{self.get_species_display()} batch in {self.pond.name}"

    @property
    def current_age_days(self):
        return (timezone.now().date() - self.stocking_date).days

    @property
    def latest_biomass_kg(self):
        latest = self.growth_records.order_by("-date").first()
        if not latest:
            total_g = self.initial_count * float(self.initial_avg_weight_g)
        else:
            total_g = latest.surviving_count * float(latest.avg_weight_g)
        return total_g / 1000.0


# ── GrowthRecord ──────────────────────────────────────────────────────────────
class GrowthRecord(models.Model):
    batch = models.ForeignKey(FishBatch, on_delete=models.CASCADE, related_name="growth_records")
    date = models.DateField(default=timezone.now)
    surviving_count = models.PositiveIntegerField()
    avg_weight_g = models.DecimalField(max_digits=7, decimal_places=2,
                                       help_text="Average weight per fish (grams)")

    class Meta:
        unique_together = ("batch", "date")
        ordering = ["date"]

    def __str__(self):
        return f"Growth {self.date} – {self.batch}"


# ── WeatherRecord ─────────────────────────────────────────────────────────────
class WeatherRecord(models.Model):
    pond = models.ForeignKey(Pond, on_delete=models.CASCADE, related_name="weather_records")
    timestamp = models.DateTimeField(default=timezone.now)
    water_temp_c = models.DecimalField(max_digits=4, decimal_places=1,
                                       help_text="Water temperature (°C)")
    dissolved_oxygen_mg_l = models.DecimalField(max_digits=4, decimal_places=2,
                                                help_text="Dissolved oxygen (mg/L)")
    ph = models.DecimalField(max_digits=4, decimal_places=2, help_text="Water pH")
    rainfall_mm = models.DecimalField(max_digits=6, decimal_places=2, default=0,
                                      help_text="Rainfall (mm)")

    class Meta:
        ordering = ["-timestamp"]

    def __str__(self):
        return f"Weather {self.timestamp:%Y-%m-%d %H:%M} – {self.pond.name}"


# ── DailyWeather ──────────────────────────────────────────────────────────────
class DailyWeather(models.Model):
    date = models.DateField(unique=True)
    location_query = models.CharField(max_length=100, default="")
    temperature_c = models.DecimalField(max_digits=4, decimal_places=1)
    condition = models.CharField(max_length=50)
    feed_percent = models.DecimalField(max_digits=5, decimal_places=2,
                                       help_text="Recommended feed percentage based on ambient weather")
    raw_payload = models.JSONField(blank=True, null=True)

    class Meta:
        ordering = ["-date"]

    def __str__(self):
        return f"{self.date} [{self.location_query}] – {self.temperature_c}°C"


# ── FeedingProfile ────────────────────────────────────────────────────────────
class FeedingProfile(models.Model):
    name = models.CharField(max_length=100, unique=True)
    min_temp_c = models.DecimalField(max_digits=4, decimal_places=1,
                                     help_text="Minimum water temperature (°C)")
    max_temp_c = models.DecimalField(max_digits=4, decimal_places=1,
                                     help_text="Maximum water temperature (°C)")
    feeding_rate_pct = models.DecimalField(max_digits=4, decimal_places=2,
                                           help_text="Daily feed as % of biomass")

    class Meta:
        ordering = ["min_temp_c"]

    def __str__(self):
        return f"{self.name} ({self.min_temp_c}–{self.max_temp_c}°C)"


# ── FeedLog ───────────────────────────────────────────────────────────────────
class FeedLog(models.Model):
    batch = models.ForeignKey(FishBatch, on_delete=models.CASCADE, related_name="feed_logs")
    date = models.DateField(default=timezone.now)
    feed_amount_kg = models.DecimalField(max_digits=7, decimal_places=2)
    auto_calculated = models.BooleanField(default=True)

    class Meta:
        ordering = ["-date"]

    def __str__(self):
        return f"{self.date} feed for {self.batch}"


# ── FeedingReminder ───────────────────────────────────────────────────────────
class FeedingReminder(models.Model):
    batch = models.ForeignKey(FishBatch, on_delete=models.CASCADE, related_name="feeding_reminders")
    scheduled_for = models.DateTimeField()
    message = models.CharField(max_length=255, default="Time to feed this batch.")
    sent = models.BooleanField(default=False)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["scheduled_for"]

    def __str__(self):
        return f"Reminder for {self.batch} at {self.scheduled_for}"


# ── SensorReading ─────────────────────────────────────────────────────────────
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

    def __str__(self):
        return f"{self.pond.name} {self.sensor_type}={self.value} at {self.recorded_at}"


# ── NEW: HarvestRecord ────────────────────────────────────────────────────────
class HarvestRecord(models.Model):
    batch = models.ForeignKey(FishBatch, on_delete=models.CASCADE, related_name="harvests")
    harvest_date = models.DateField(default=timezone.now)
    harvested_count = models.PositiveIntegerField(help_text="Number of fish harvested")
    avg_weight_g = models.DecimalField(max_digits=7, decimal_places=2,
                                       help_text="Average weight per fish (grams)")
    total_weight_kg = models.DecimalField(max_digits=9, decimal_places=2,
                                          help_text="Total harvest weight (kg)")
    price_per_kg = models.DecimalField(max_digits=7, decimal_places=2, default=0,
                                       help_text="Sale price per kg (BDT)")
    buyer_name = models.CharField(max_length=150, blank=True)
    notes = models.TextField(blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["-harvest_date"]

    def __str__(self):
        return f"Harvest {self.harvest_date} – {self.batch}"

    @property
    def gross_revenue(self):
        return round(float(self.total_weight_kg) * float(self.price_per_kg), 2)


# ── NEW: Expense ──────────────────────────────────────────────────────────────
class Expense(models.Model):
    CATEGORY_CHOICES = [
        ("feed", "Feed"),
        ("medicine", "Medicine / Treatment"),
        ("labour", "Labour"),
        ("equipment", "Equipment"),
        ("electricity", "Electricity"),
        ("fingerlings", "Fingerlings / Stocking"),
        ("other", "Other"),
    ]
    pond = models.ForeignKey(Pond, on_delete=models.CASCADE, related_name="expenses",
                             null=True, blank=True,
                             help_text="Leave blank for farm-wide expense")
    date = models.DateField(default=timezone.now)
    category = models.CharField(max_length=20, choices=CATEGORY_CHOICES)
    amount = models.DecimalField(max_digits=10, decimal_places=2, help_text="Amount (BDT)")
    description = models.CharField(max_length=255)
    notes = models.TextField(blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["-date"]

    def __str__(self):
        return f"{self.get_category_display()} – {self.amount} BDT ({self.date})"


# ── NEW: MortalityLog ─────────────────────────────────────────────────────────
class MortalityLog(models.Model):
    CAUSE_CHOICES = [
        ("disease", "Disease"),
        ("oxygen", "Low Oxygen"),
        ("temperature", "Temperature Stress"),
        ("predator", "Predator"),
        ("unknown", "Unknown"),
        ("other", "Other"),
    ]
    batch = models.ForeignKey(FishBatch, on_delete=models.CASCADE, related_name="mortality_logs")
    date = models.DateField(default=timezone.now)
    count = models.PositiveIntegerField(help_text="Number of dead fish")
    cause = models.CharField(max_length=20, choices=CAUSE_CHOICES, default="unknown")
    notes = models.TextField(blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["-date"]

    def __str__(self):
        return f"{self.count} dead ({self.get_cause_display()}) – {self.batch} – {self.date}"


# ── NEW: FarmAlert ────────────────────────────────────────────────────────────
class FarmAlert(models.Model):
    LEVEL_CHOICES = [
        ("info", "Info"),
        ("warning", "Warning"),
        ("critical", "Critical"),
    ]
    TYPE_CHOICES = [
        ("low_oxygen", "Low Dissolved Oxygen"),
        ("high_temp", "High Temperature"),
        ("low_temp", "Low Temperature"),
        ("ph_out", "pH Out of Range"),
        ("high_mortality", "High Mortality"),
        ("harvest_due", "Harvest Due"),
        ("feed_overdue", "Feed Overdue"),
        ("custom", "Custom"),
    ]
    pond = models.ForeignKey(Pond, on_delete=models.CASCADE, related_name="alerts",
                             null=True, blank=True)
    alert_type = models.CharField(max_length=20, choices=TYPE_CHOICES)
    level = models.CharField(max_length=10, choices=LEVEL_CHOICES, default="warning")
    message = models.TextField()
    resolved = models.BooleanField(default=False)
    resolved_at = models.DateTimeField(null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["-created_at"]

    def __str__(self):
        return f"[{self.level.upper()}] {self.get_alert_type_display()}"

    def resolve(self):
        self.resolved = True
        self.resolved_at = timezone.now()
        self.save()


# ── NEW: PondNote ─────────────────────────────────────────────────────────────
class PondNote(models.Model):
    pond = models.ForeignKey(Pond, on_delete=models.CASCADE, related_name="notes")
    author = models.CharField(max_length=100, default="Farm Manager")
    body = models.TextField()
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["-created_at"]

    def __str__(self):
        return f"Note – {self.pond.name} – {self.created_at:%Y-%m-%d}"
