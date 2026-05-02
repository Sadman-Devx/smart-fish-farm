"""
farm/tests_feed_recommendation.py
──────────────────────────────────────────────────────────────────────────────
Regression tests for the two dashboard feed-recommendation bugs:

  Bug 1 — "Recommended (KG)" column in 14-day table always showed "—"
  Bug 2 — "Recommended feed today" KPI always showed 0.00 kg

Both bugs had the same root cause: smart_feed_kg_for_batch() returned None
when no DailyWeather row existed for a given date and the OpenWeather API
key was not configured.

Run with:
    python manage.py test farm.tests_feed_recommendation
"""

from datetime import date, timedelta
from decimal import Decimal

from django.test import TestCase, Client
from django.urls import reverse
from django.utils import timezone

from accounts.models import User
from farm.models import (
    DailyWeather, FeedingProfile, FeedLog, FishBatch,
    GrowthRecord, Pond, WeatherRecord,
)
from farm.services.feed_calculator import smart_feed_kg_for_batch


# ─────────────────────────────────────────────────────────────────────────────
# Helpers
# ─────────────────────────────────────────────────────────────────────────────

def _pond(name="Bug Test Pond"):
    return Pond.objects.create(name=name, area_m2=500, max_depth_m=2)


def _batch(pond, count=1000, weight_g=100.0):
    return FishBatch.objects.create(
        pond=pond,
        species="tilapia",
        stocking_date=date.today() - timedelta(days=60),
        initial_count=count,
        initial_avg_weight_g=Decimal(str(weight_g)),
    )


def _profile(min_t=20, max_t=35, rate=3.0):
    return FeedingProfile.objects.create(
        name=f"Profile {min_t}-{max_t}",
        min_temp_c=Decimal(str(min_t)),
        max_temp_c=Decimal(str(max_t)),
        feeding_rate_pct=Decimal(str(rate)),
    )


def _daily_weather(d=None, temp=27.0):
    return DailyWeather.objects.create(
        date=d or date.today(),
        location_query="TestCity",
        temperature_c=Decimal(str(temp)),
        condition="Clear",
        feed_percent=Decimal("100.0"),
    )


def _pond_weather(pond, temp=27.0):
    return WeatherRecord.objects.create(
        pond=pond,
        water_temp_c=Decimal(str(temp)),
        dissolved_oxygen_mg_l=Decimal("6.50"),
        ph=Decimal("7.20"),
        rainfall_mm=Decimal("0"),
    )


# ─────────────────────────────────────────────────────────────────────────────
# 1. Unit tests for smart_feed_kg_for_batch() fallback chain
# ─────────────────────────────────────────────────────────────────────────────

class FeedCalculatorFallbackTests(TestCase):
    """
    Verify the 3-level temperature fallback so the calculator never
    returns None when a FeedingProfile exists.
    """

    def setUp(self):
        self.pond  = _pond("Fallback Pond")
        self.batch = _batch(self.pond, count=1000, weight_g=100.0)
        # Biomass = 1000 × 100g = 100 kg
        # Profile rate 3 % → base feed = 3.0 kg/day
        _profile(min_t=18, max_t=35, rate=3.0)

    # ── Level 1: exact-day DailyWeather ──────────────────────────────────────

    def test_returns_value_with_exact_daily_weather(self):
        _daily_weather(d=date.today(), temp=27.0)
        result = smart_feed_kg_for_batch(self.batch, day=date.today())
        self.assertIsNotNone(result)
        self.assertGreater(result, 0)

    def test_correct_calculation_with_daily_weather(self):
        """
        Biomass=100kg, rate=3%, temp=27°C → factor=1.0
        Expected = 100 × 0.03 × 1.0 = 3.00 kg
        """
        _daily_weather(d=date.today(), temp=27.0)
        result = smart_feed_kg_for_batch(self.batch, day=date.today())
        self.assertAlmostEqual(result, 3.0, delta=0.05)

    # ── Level 2: no exact-day record → fall back to most-recent DailyWeather ──

    def test_returns_value_with_only_recent_daily_weather(self):
        """
        No DailyWeather for today, but there IS one from yesterday.
        The calculator must fall back to yesterday's record.
        """
        yesterday = date.today() - timedelta(days=1)
        _daily_weather(d=yesterday, temp=27.0)
        # Ensure no record for today
        DailyWeather.objects.filter(date=date.today()).delete()

        result = smart_feed_kg_for_batch(self.batch, day=date.today())
        self.assertIsNotNone(result,
            "Should fall back to most-recent DailyWeather when today's is missing")
        self.assertGreater(result, 0)

    def test_returns_value_with_past_daily_weather_for_historical_date(self):
        """
        Requesting recommendation for a date 5 days ago — no exact record
        exists for that day, only the most-recent one (from yesterday).
        """
        yesterday  = date.today() - timedelta(days=1)
        five_days_ago = date.today() - timedelta(days=5)
        _daily_weather(d=yesterday, temp=25.0)

        result = smart_feed_kg_for_batch(self.batch, day=five_days_ago)
        self.assertIsNotNone(result,
            "Past-date recommendation must use most-recent DailyWeather as fallback")
        self.assertGreater(result, 0)

    # ── Level 3: no DailyWeather at all → use pond WeatherRecord ─────────────

    def test_returns_value_with_only_pond_weather_record(self):
        """
        No DailyWeather rows at all, but a pond WeatherRecord exists.
        Calculator must use pond water temperature.
        """
        DailyWeather.objects.all().delete()
        _pond_weather(self.pond, temp=27.0)

        result = smart_feed_kg_for_batch(self.batch, day=date.today())
        self.assertIsNotNone(result,
            "Should use pond WeatherRecord when no DailyWeather exists")
        self.assertGreater(result, 0)

    # ── Level 4: nothing at all → 26°C default ───────────────────────────────

    def test_returns_value_with_no_weather_data_at_all(self):
        """
        No DailyWeather, no WeatherRecord → calculator falls back to 26°C.
        With profile covering 18-35°C and rate=3%, result should be 3.0 kg.
        """
        DailyWeather.objects.all().delete()
        WeatherRecord.objects.all().delete()

        result = smart_feed_kg_for_batch(self.batch, day=date.today())
        self.assertIsNotNone(result,
            "Must return a value even with zero weather data (26°C default)")
        self.assertAlmostEqual(result, 3.0, delta=0.05,
            msg="Default 26°C with factor=1.0 should give 100×0.03×1.0=3.0 kg")

    # ── No profile → None is still correct ───────────────────────────────────

    def test_returns_none_without_feeding_profile(self):
        """Without any FeedingProfile the service cannot recommend — returns None."""
        FeedingProfile.objects.all().delete()
        result = smart_feed_kg_for_batch(self.batch, day=date.today())
        self.assertIsNone(result,
            "Must return None when no FeedingProfile is configured")


# ─────────────────────────────────────────────────────────────────────────────
# 2. Dashboard view integration tests
# ─────────────────────────────────────────────────────────────────────────────

class DashboardRecommendedFeedTests(TestCase):
    """
    Verify the dashboard renders non-zero recommended values in both
    the KPI card and the 14-day table, using only data already in DB.
    """

    def setUp(self):
        self.client = Client()
        self.pond   = _pond("Dashboard Pond")
        self.batch  = _batch(self.pond, count=2000, weight_g=150.0)
        # Biomass = 2000 × 150g = 300 kg; rate 3% = 9.0 kg/day at 26°C
        _profile(min_t=18, max_t=35, rate=3.0)
        # Log feed for the last 5 days so the 14-day table has rows
        for i in range(5):
            day = date.today() - timedelta(days=i)
            FeedLog.objects.create(
                batch=self.batch,
                date=day,
                feed_amount_kg=Decimal("8.50"),
                auto_calculated=True,
            )

    def _dashboard(self):
        return self.client.get(reverse("farm:dashboard"))

    # ── Bug 2: "Recommended feed today" KPI ──────────────────────────────────

    def test_recommended_feed_today_kpi_not_zero_without_daily_weather(self):
        """
        No DailyWeather, no WeatherRecord → falls back to 26°C default.
        KPI must show a positive number.
        """
        DailyWeather.objects.all().delete()
        WeatherRecord.objects.all().delete()

        resp = self._dashboard()
        self.assertEqual(resp.status_code, 200)
        ctx  = resp.context
        self.assertGreater(
            ctx["recommended_feed_today_kg"], 0,
            "Recommended feed today must be > 0 even without weather data",
        )

    def test_recommended_feed_today_kpi_uses_pond_weather_when_available(self):
        _pond_weather(self.pond, temp=27.0)
        DailyWeather.objects.all().delete()

        resp = self._dashboard()
        self.assertGreater(resp.context["recommended_feed_today_kg"], 0)
        self.assertIn("Pond weather", resp.context["recommended_feed_source_label"])

    def test_recommended_feed_today_kpi_uses_api_weather_when_available(self):
        _daily_weather(d=date.today(), temp=27.0)
        WeatherRecord.objects.all().delete()

        resp = self._dashboard()
        self.assertGreater(resp.context["recommended_feed_today_kg"], 0)
        self.assertIn("API weather", resp.context["recommended_feed_source_label"])

    def test_recommended_feed_today_kpi_shows_default_label_without_any_weather(self):
        DailyWeather.objects.all().delete()
        WeatherRecord.objects.all().delete()

        resp = self._dashboard()
        self.assertIn(
            "Default temp",
            resp.context["recommended_feed_source_label"],
            "Source label should mention 'Default temp' when no weather data exists",
        )

    # ── Bug 1: "Recommended (KG)" column in 14-day table ─────────────────────

    def test_recommended_column_not_all_none_without_daily_weather(self):
        """
        The 14-day rows must have at least one non-None recommended_feed_kg
        even when no DailyWeather rows exist.
        """
        DailyWeather.objects.all().delete()
        WeatherRecord.objects.all().delete()

        resp = self._dashboard()
        rows = resp.context["daily_feed_temp_rows"]
        self.assertTrue(len(rows) > 0, "There should be feed rows in context")

        none_count = sum(1 for r in rows if r["recommended_feed_kg"] is None)
        self.assertLess(
            none_count, len(rows),
            "At least some rows must have a recommended_feed_kg value "
            "(not all None) even without weather data",
        )

    def test_recommended_column_values_are_positive(self):
        """All non-None recommended values must be > 0."""
        DailyWeather.objects.all().delete()
        WeatherRecord.objects.all().delete()

        resp  = self._dashboard()
        rows  = resp.context["daily_feed_temp_rows"]
        for row in rows:
            if row["recommended_feed_kg"] is not None:
                self.assertGreater(
                    row["recommended_feed_kg"], 0,
                    f"recommended_feed_kg for {row['date']} must be > 0",
                )

    def test_recommended_column_with_pond_weather_record(self):
        """With a pond WeatherRecord the column must be populated."""
        DailyWeather.objects.all().delete()
        _pond_weather(self.pond, temp=26.0)

        resp  = self._dashboard()
        rows  = resp.context["daily_feed_temp_rows"]
        total = sum(r["recommended_feed_kg"] or 0 for r in rows)
        self.assertGreater(total, 0,
            "Recommended column sum must be > 0 when pond WeatherRecord exists")

    def test_recommended_column_with_recent_daily_weather_fallback(self):
        """
        DailyWeather exists only for yesterday (not for earlier dates).
        Historical rows must still get a recommended value via fallback.
        """
        WeatherRecord.objects.all().delete()
        yesterday = date.today() - timedelta(days=1)
        _daily_weather(d=yesterday, temp=27.0)

        resp = self._dashboard()
        rows = resp.context["daily_feed_temp_rows"]
        # Look at rows older than yesterday
        old_rows = [r for r in rows if r["date"] < yesterday]
        if old_rows:
            populated = [r for r in old_rows if r["recommended_feed_kg"] is not None]
            self.assertTrue(
                len(populated) > 0,
                "Historical rows must use recent DailyWeather as fallback",
            )

    # ── Sanity: calculation accuracy ──────────────────────────────────────────

    def test_recommended_today_matches_manual_calculation(self):
        """
        300 kg biomass × 3% rate × 1.0 factor (at 26°C) = 9.00 kg.
        """
        DailyWeather.objects.all().delete()
        WeatherRecord.objects.all().delete()

        resp = self._dashboard()
        recommended = resp.context["recommended_feed_today_kg"]
        self.assertAlmostEqual(
            recommended, 9.0, delta=0.5,
            msg=(
                f"Expected ~9.0 kg (300kg × 3% × 1.0) but got {recommended}. "
                "Check FeedingProfile rate or temperature factor."
            ),
        )


# ─────────────────────────────────────────────────────────────────────────────
# 3. Template rendering tests
# ─────────────────────────────────────────────────────────────────────────────

class DashboardTemplateTests(TestCase):
    """Verify the HTML output contains numeric values not just dashes."""

    def setUp(self):
        self.client = Client()
        self.pond   = _pond("Template Pond")
        self.batch  = _batch(self.pond, count=500, weight_g=200.0)
        _profile(min_t=18, max_t=35, rate=3.0)
        FeedLog.objects.create(
            batch=self.batch,
            date=date.today(),
            feed_amount_kg=Decimal("3.00"),
            auto_calculated=True,
        )

    def test_dashboard_html_contains_recommended_value(self):
        """
        The rendered HTML for the 14-day table should contain at least
        one non-dash value in the Recommended column.
        """
        DailyWeather.objects.all().delete()
        WeatherRecord.objects.all().delete()

        resp    = self.client.get(reverse("farm:dashboard"))
        content = resp.content.decode()

        # The recommended feed at 26°C for 500×200g=100kg biomass × 3% = 3.0 kg
        # So "3.00" should appear in the table
        self.assertIn("3.00", content,
            "Dashboard HTML must contain the recommended feed value '3.00'")

    def test_kpi_card_shows_nonzero_recommended(self):
        """
        The 'Feed Today' KPI card shows 'Recommended: X kg'.
        X must not be 0.00 when a FeedingProfile exists.
        """
        DailyWeather.objects.all().delete()
        WeatherRecord.objects.all().delete()

        resp    = self.client.get(reverse("farm:dashboard"))
        content = resp.content.decode()

        # "Recommended: 0.00 kg" must NOT appear
        self.assertNotIn("Recommended: 0.00 kg", content,
            "KPI card must not show 'Recommended: 0.00 kg' when a FeedingProfile is set")