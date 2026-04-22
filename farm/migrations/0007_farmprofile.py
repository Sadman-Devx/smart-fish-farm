"""
farm/migrations/0007_farmprofile.py
"""
import django.db.models.deletion
import django.utils.timezone
from django.conf import settings
from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("farm", "0006_seed_feeding_profiles"),
        migrations.swappable_dependency(settings.AUTH_USER_MODEL),
    ]

    operations = [
        migrations.CreateModel(
            name="FarmProfile",
            fields=[
                ("id", models.BigAutoField(
                    auto_created=True, primary_key=True,
                    serialize=False, verbose_name="ID",
                )),
                ("user", models.OneToOneField(
                    on_delete=django.db.models.deletion.CASCADE,
                    related_name="farm_profile",
                    to=settings.AUTH_USER_MODEL,
                )),
                # Step 1
                ("farm_name",   models.CharField(max_length=150, blank=True)),
                ("size_acres",  models.DecimalField(
                    max_digits=8, decimal_places=2, null=True, blank=True,
                    help_text="Total farm area in acres",
                )),
                ("num_ponds",   models.PositiveIntegerField(
                    null=True, blank=True,
                    help_text="Number of fish ponds",
                )),
                ("water_source", models.CharField(
                    max_length=20, blank=True,
                    choices=[
                        ("river",       "River / Canal"),
                        ("groundwater", "Groundwater / Tube Well"),
                        ("rainwater",   "Rainwater"),
                        ("reservoir",   "Reservoir / Lake"),
                        ("mixed",       "Mixed Sources"),
                        ("other",       "Other"),
                    ],
                )),
                # Step 2
                ("latitude",  models.DecimalField(
                    max_digits=10, decimal_places=7, null=True, blank=True,
                    help_text="GPS latitude",
                )),
                ("longitude", models.DecimalField(
                    max_digits=10, decimal_places=7, null=True, blank=True,
                    help_text="GPS longitude",
                )),
                ("district",  models.CharField(max_length=60, blank=True)),
                ("upazila",   models.CharField(max_length=60, blank=True)),
                # Step 3
                ("species", models.JSONField(default=list, blank=True)),
                ("farming_experience_years", models.PositiveIntegerField(null=True, blank=True)),
                # Step 4 — cached weather
                ("weather_temp_c",       models.DecimalField(
                    max_digits=5, decimal_places=2, null=True, blank=True,
                )),
                ("weather_humidity_pct", models.PositiveIntegerField(null=True, blank=True)),
                ("weather_rain_mm",      models.DecimalField(
                    max_digits=6, decimal_places=2, null=True, blank=True,
                )),
                ("weather_condition",    models.CharField(max_length=60, blank=True)),
                ("weather_fetched_at",   models.DateTimeField(null=True, blank=True)),
                # Progress
                ("onboarding_complete", models.BooleanField(default=False)),
                ("created_at", models.DateTimeField(auto_now_add=True)),
                ("updated_at", models.DateTimeField(auto_now=True)),
            ],
            options={"verbose_name": "Farm Profile"},
        ),
    ]