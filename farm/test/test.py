"""
farm/tests.py
─────────────────────────────────────────────────────────────────────────────
Test suite for Smart Fish Farm Management System.

Coverage areas:
  1. GuestAccessTests         — anonymous users can browse all read-only pages
  2. GuestBlockedTests        — anonymous POSTs redirect to login (403/302)
  3. AuthenticatedWriteTests  — logged-in users can submit all forms
  4. APIPermissionTests       — DRF endpoints: GET public, POST auth-only
  5. AlertAutoGenerationTests — water-quality alerts fire correctly
  6. ModelPropertyTests       — batch biomass, age, harvest revenue calculations
  7. ServiceTests             — feed calculator & growth prediction logic
"""

import json
from datetime import date, timedelta
from decimal import Decimal

from django.test import TestCase, Client
from django.urls import reverse
from django.utils import timezone

from accounts.models import User
from farm.models import (
    Pond, FishBatch, GrowthRecord, WeatherRecord, FeedingProfile,
    FeedLog, FeedingReminder, HarvestRecord, Expense, MortalityLog,
    FarmAlert, DailyWeather,
)
from farm.services import smart_feed_kg_for_batch, predict_batch_growth


# ─────────────────────────────────────────────────────────────────────────────
# Shared fixtures
# ─────────────────────────────────────────────────────────────────────────────

def make_pond(name="Test Pond", area=500, depth=2.0):
    return Pond.objects.create(name=name, area_m2=area, max_depth_m=depth)


def make_batch(pond, species="tilapia", count=1000, weight_g=50.0):
    return FishBatch.objects.create(
        pond=pond,
        species=species,
        stocking_date=date.today() - timedelta(days=30),
        initial_count=count,
        initial_avg_weight_g=weight_g,
    )


def make_user(email="farmer@test.com", password="pass1234!", role="manager"):
    return User.objects.create_user(
        username=email.split("@")[0],
        email=email,
        password=password,
        role=role,
        two_factor_enabled=False,   # skip OTP flow in tests
    )


def make_feeding_profile():
    return FeedingProfile.objects.create(
        name="Standard",
        min_temp_c=Decimal("20.0"),
        max_temp_c=Decimal("32.0"),
        feeding_rate_pct=Decimal("3.00"),
    )


def make_weather(pond, temp=27.0, do=6.5, ph=7.2, rainfall=0):
    return WeatherRecord.objects.create(
        pond=pond,
        water_temp_c=temp,
        dissolved_oxygen_mg_l=do,
        ph=ph,
        rainfall_mm=rainfall,
    )


def make_daily_weather(temp=27.0, condition="Clear", feed_pct=100.0):
    return DailyWeather.objects.create(
        date=date.today(),
        location_query="TestCity",
        temperature_c=temp,
        condition=condition,
        feed_percent=feed_pct,
    )


# ─────────────────────────────────────────────────────────────────────────────
# 1. Guest can access all read-only pages
# ─────────────────────────────────────────────────────────────────────────────

class GuestAccessTests(TestCase):
    """Anonymous visitors must be able to reach every read-only URL with HTTP 200."""

    def setUp(self):
        self.client = Client()
        self.pond   = make_pond()
        self.batch  = make_batch(self.pond)

    def _get(self, url_name, **kwargs):
        url = reverse(f"farm:{url_name}", **kwargs)
        return self.client.get(url)

    def test_dashboard_accessible_to_guest(self):
        resp = self._get("dashboard")
        self.assertEqual(resp.status_code, 200, "Dashboard must be public")

    def test_pond_list_accessible_to_guest(self):
        resp = self._get("pond_list")
        self.assertEqual(resp.status_code, 200)

    def test_pond_detail_accessible_to_guest(self):
        resp = self._get("pond_detail", kwargs={"pk": self.pond.pk})
        self.assertEqual(resp.status_code, 200)

    def test_batch_detail_accessible_to_guest(self):
        resp = self._get("batch_detail", kwargs={"pk": self.batch.pk})
        self.assertEqual(resp.status_code, 200)

    def test_harvest_list_accessible_to_guest(self):
        resp = self._get("harvest_list")
        self.assertEqual(resp.status_code, 200)

    def test_expense_list_accessible_to_guest(self):
        resp = self._get("expense_list")
        self.assertEqual(resp.status_code, 200)

    def test_alert_list_accessible_to_guest(self):
        resp = self._get("alert_list")
        self.assertEqual(resp.status_code, 200)

    def test_daily_feed_report_accessible_to_guest(self):
        resp = self._get("daily_feed_report")
        self.assertEqual(resp.status_code, 200)

    def test_reminder_list_accessible_to_guest(self):
        resp = self._get("reminder_list")
        self.assertEqual(resp.status_code, 200)

    def test_profit_loss_report_accessible_to_guest(self):
        resp = self._get("profit_loss_report")
        self.assertEqual(resp.status_code, 200)

    def test_guest_dashboard_contains_no_js_redirect(self):
        """The old base.html had a JS redirect. Ensure it's gone."""
        resp = self._get("dashboard")
        self.assertNotIn(b"window.location.href", resp.content,
                         "JS redirect must be removed so guests can access the site")

    def test_guest_sees_guest_banner(self):
        """Guests should see the 'browsing as a guest' info banner."""
        resp = self._get("dashboard")
        self.assertContains(resp, "guest", msg_prefix="Guest banner should be visible")

    def test_guest_dashboard_shows_sign_in_links(self):
        resp = self._get("dashboard")
        self.assertContains(resp, reverse("accounts:login"))


# ─────────────────────────────────────────────────────────────────────────────
# 2. Guest POSTs are blocked (redirect to login)
# ─────────────────────────────────────────────────────────────────────────────

class GuestBlockedTests(TestCase):
    """POST requests from unauthenticated users must be redirected to login."""

    def setUp(self):
        self.client = Client()
        self.pond   = make_pond()
        self.batch  = make_batch(self.pond)

    def _assert_redirects_to_login(self, url_name, post_data=None, kwargs=None):
        url  = reverse(f"farm:{url_name}", kwargs=kwargs or {})
        resp = self.client.post(url, post_data or {})
        login_url = reverse("accounts:login")
        self.assertIn(resp.status_code, [302, 403],
                      f"{url_name} POST should block guests (got {resp.status_code})")
        if resp.status_code == 302:
            self.assertIn(login_url, resp["Location"],
                          f"{url_name} should redirect to login")

    def test_guest_cannot_post_weather(self):
        self._assert_redirects_to_login("weather_create", {
            "pond": self.pond.pk,
            "water_temp_c": 27.0,
            "dissolved_oxygen_mg_l": 6.5,
            "ph": 7.2,
            "rainfall_mm": 0,
        })

    def test_guest_cannot_post_growth(self):
        self._assert_redirects_to_login("growth_create", {
            "batch": self.batch.pk,
            "date": date.today().isoformat(),
            "surviving_count": 950,
            "avg_weight_g": 120.0,
        })

    def test_guest_cannot_post_feed_log(self):
        self._assert_redirects_to_login("feed_log_create", {
            "batch": self.batch.pk,
            "date": date.today().isoformat(),
            "feed_amount_kg": 5.0,
        })

    def test_guest_cannot_post_harvest(self):
        self._assert_redirects_to_login("harvest_create", {
            "batch": self.batch.pk,
            "harvest_date": date.today().isoformat(),
            "harvested_count": 800,
            "avg_weight_g": 480,
            "total_weight_kg": 384,
            "price_per_kg": 220,
        })

    def test_guest_cannot_post_expense(self):
        self._assert_redirects_to_login("expense_create", {
            "date": date.today().isoformat(),
            "category": "feed",
            "amount": 5000,
            "description": "Monthly feed purchase",
        })

    def test_guest_cannot_post_mortality(self):
        self._assert_redirects_to_login("mortality_create", {
            "batch": self.batch.pk,
            "date": date.today().isoformat(),
            "count": 10,
            "cause": "unknown",
        })

    def test_guest_cannot_resolve_alert(self):
        alert = FarmAlert.objects.create(
            pond=self.pond,
            alert_type="custom",
            level="info",
            message="Test alert",
        )
        self._assert_redirects_to_login("alert_resolve", kwargs={"pk": alert.pk})

    def test_guest_cannot_send_test_alert(self):
        url  = reverse("farm:send_test_alert")
        resp = self.client.post(url)
        self.assertIn(resp.status_code, [302, 403])

    def test_guest_batch_detail_post_redirects_to_login(self):
        """POSTing the feed form on batch_detail as a guest → login redirect."""
        url  = reverse("farm:batch_detail", kwargs={"pk": self.batch.pk})
        resp = self.client.post(url, {
            "date": date.today().isoformat(),
            "feed_amount_kg": 3.5,
        })
        self.assertEqual(resp.status_code, 302)
        self.assertIn(reverse("accounts:login"), resp["Location"])


# ─────────────────────────────────────────────────────────────────────────────
# 3. Authenticated users can use all write features
# ─────────────────────────────────────────────────────────────────────────────

class AuthenticatedWriteTests(TestCase):
    """Logged-in users should be able to create records via form submission."""

    def setUp(self):
        self.client = Client()
        self.user   = make_user()
        self.client.force_login(self.user)
        self.pond   = make_pond()
        self.batch  = make_batch(self.pond)
        make_feeding_profile()
        make_daily_weather()

    def test_authenticated_can_log_weather(self):
        url  = reverse("farm:weather_create")
        resp = self.client.post(url, {
            "pond": self.pond.pk,
            "water_temp_c": "27.0",
            "dissolved_oxygen_mg_l": "6.50",
            "ph": "7.20",
            "rainfall_mm": "0",
        })
        # Should redirect (success) not stay on the form
        self.assertIn(resp.status_code, [302], "Weather form should redirect on success")
        self.assertTrue(WeatherRecord.objects.filter(pond=self.pond).exists())

    def test_authenticated_can_log_growth(self):
        url  = reverse("farm:growth_create")
        resp = self.client.post(url, {
            "batch": self.batch.pk,
            "date": date.today().isoformat(),
            "surviving_count": 950,
            "avg_weight_g": "120.00",
        })
        self.assertIn(resp.status_code, [302])
        self.assertTrue(GrowthRecord.objects.filter(batch=self.batch).exists())

    def test_authenticated_can_log_feed(self):
        url  = reverse("farm:feed_log_create")
        resp = self.client.post(url, {
            "batch": self.batch.pk,
            "date": date.today().isoformat(),
            "feed_amount_kg": "5.00",
        })
        self.assertIn(resp.status_code, [302])
        self.assertTrue(FeedLog.objects.filter(batch=self.batch).exists())

    def test_authenticated_can_log_harvest(self):
        url  = reverse("farm:harvest_create")
        resp = self.client.post(url, {
            "batch": self.batch.pk,
            "harvest_date": date.today().isoformat(),
            "harvested_count": 800,
            "avg_weight_g": "480.00",
            "total_weight_kg": "384.00",
            "price_per_kg": "220.00",
            "buyer_name": "Local Market",
        })
        self.assertIn(resp.status_code, [302])
        self.assertTrue(HarvestRecord.objects.filter(batch=self.batch).exists())

    def test_authenticated_can_log_expense(self):
        url  = reverse("farm:expense_create")
        resp = self.client.post(url, {
            "date": date.today().isoformat(),
            "category": "feed",
            "amount": "5000.00",
            "description": "Monthly pellet purchase",
        })
        self.assertIn(resp.status_code, [302])
        self.assertTrue(Expense.objects.exists())

    def test_authenticated_can_log_transport_expense(self):
        url  = reverse("farm:expense_create")
        resp = self.client.post(url, {
            "date": date.today().isoformat(),
            "category": "transport",
            "amount": "750.00",
            "description": "Fuel for feed delivery",
        })
        self.assertIn(resp.status_code, [302])
        self.assertTrue(Expense.objects.filter(category="transport").exists())

    def test_authenticated_can_log_mortality(self):
        url  = reverse("farm:mortality_create")
        resp = self.client.post(url, {
            "batch": self.batch.pk,
            "date": date.today().isoformat(),
            "count": 10,
            "cause": "disease",
        })
        self.assertIn(resp.status_code, [302])
        self.assertTrue(MortalityLog.objects.filter(batch=self.batch).exists())

    def test_authenticated_can_resolve_alert(self):
        alert = FarmAlert.objects.create(
            pond=self.pond,
            alert_type="custom",
            level="info",
            message="Test alert",
        )
        url  = reverse("farm:alert_resolve", kwargs={"pk": alert.pk})
        resp = self.client.post(url)
        self.assertIn(resp.status_code, [302])
        alert.refresh_from_db()
        self.assertTrue(alert.resolved)

    def test_batch_detail_feed_form_saves_for_auth_user(self):
        url  = reverse("farm:batch_detail", kwargs={"pk": self.batch.pk})
        resp = self.client.post(url, {
            "batch": self.batch.pk,
            "date": date.today().isoformat(),
            "feed_amount_kg": "4.50",
        })
        self.assertIn(resp.status_code, [302])
        self.assertTrue(FeedLog.objects.filter(batch=self.batch, feed_amount_kg="4.50").exists())


# ─────────────────────────────────────────────────────────────────────────────
# 4. DRF API permission tests
# ─────────────────────────────────────────────────────────────────────────────

class APIPermissionTests(TestCase):
    """
    REST API:
      GET  endpoints → HTTP 200 for anonymous
      POST endpoints → HTTP 403 for anonymous, 201 for authenticated
    """

    def setUp(self):
        self.client = Client()
        self.pond   = make_pond("API Pond")
        self.batch  = make_batch(self.pond)
        self.user   = make_user("api_user@test.com")

    def _api(self, path):
        return f"/api/{path}"

    # ── GET (public) ──────────────────────────────────────────────────────────

    def test_api_pond_list_get_is_public(self):
        resp = self.client.get(self._api("ponds/"))
        self.assertEqual(resp.status_code, 200)

    def test_api_batch_list_get_is_public(self):
        resp = self.client.get(self._api("batches/"))
        self.assertEqual(resp.status_code, 200)

    def test_api_batch_detail_get_is_public(self):
        resp = self.client.get(self._api(f"batches/{self.batch.pk}/"))
        self.assertEqual(resp.status_code, 200)

    def test_api_growth_records_get_is_public(self):
        resp = self.client.get(self._api("growth-records/"))
        self.assertEqual(resp.status_code, 200)

    def test_api_weather_records_get_is_public(self):
        resp = self.client.get(self._api("weather-records/"))
        self.assertEqual(resp.status_code, 200)

    def test_api_feed_logs_get_is_public(self):
        resp = self.client.get(self._api("feed-logs/"))
        self.assertEqual(resp.status_code, 200)

    def test_api_batch_prediction_get_is_public(self):
        resp = self.client.get(self._api(f"batches/{self.batch.pk}/prediction/"))
        self.assertEqual(resp.status_code, 200)

    # ── POST (auth required) ──────────────────────────────────────────────────

    def test_api_pond_post_blocked_for_guest(self):
        resp = self.client.post(
            self._api("ponds/"),
            json.dumps({"name": "New Pond", "area_m2": "200.00", "max_depth_m": "1.50"}),
            content_type="application/json",
        )
        self.assertEqual(resp.status_code, 403,
                         "Anonymous POST to /api/ponds/ must return 403")

    def test_api_batch_post_blocked_for_guest(self):
        resp = self.client.post(
            self._api("batches/"),
            json.dumps({
                "pond": self.pond.pk,
                "species": "tilapia",
                "stocking_date": date.today().isoformat(),
                "initial_count": 500,
                "initial_avg_weight_g": "30.00",
            }),
            content_type="application/json",
        )
        self.assertEqual(resp.status_code, 403)

    def test_api_feed_log_post_blocked_for_guest(self):
        resp = self.client.post(
            self._api("feed-logs/"),
            json.dumps({
                "batch": self.batch.pk,
                "date": date.today().isoformat(),
                "feed_amount_kg": "3.00",
            }),
            content_type="application/json",
        )
        self.assertEqual(resp.status_code, 403)

    def test_api_pond_post_allowed_for_auth(self):
        self.client.force_login(self.user)
        resp = self.client.post(
            self._api("ponds/"),
            json.dumps({"name": "Auth Pond", "area_m2": "300.00", "max_depth_m": "2.00"}),
            content_type="application/json",
        )
        self.assertEqual(resp.status_code, 201,
                         "Authenticated POST to /api/ponds/ must return 201")
        self.assertTrue(Pond.objects.filter(name="Auth Pond").exists())

    def test_api_batch_prediction_returns_expected_fields(self):
        resp = self.client.get(self._api(f"batches/{self.batch.pk}/prediction/"))
        data = resp.json()
        for field in ["batch_id", "species", "pond", "prediction"]:
            self.assertIn(field, data, f"Prediction response missing '{field}'")
        prediction = data["prediction"]
        for key in ["current_avg_weight_g", "estimated_days_to_market", "effective_fcr"]:
            self.assertIn(key, prediction)

    def test_api_pond_list_returns_correct_data(self):
        resp = self.client.get(self._api("ponds/"))
        data = resp.json()
        # DRF returns paginated or list; handle both
        results = data.get("results", data) if isinstance(data, dict) else data
        names = [p["name"] for p in results]
        self.assertIn("API Pond", names)


# ─────────────────────────────────────────────────────────────────────────────
# 5. Alert auto-generation
# ─────────────────────────────────────────────────────────────────────────────

class AlertAutoGenerationTests(TestCase):
    """Water quality recordings should fire FarmAlert rows automatically."""

    def setUp(self):
        self.client = Client()
        self.user   = make_user("alert_user@test.com")
        self.client.force_login(self.user)
        self.pond   = make_pond("Alert Pond")
        self.batch  = make_batch(self.pond)

    def _post_weather(self, temp=27.0, do=6.5, ph=7.2):
        url  = reverse("farm:weather_create")
        resp = self.client.post(url, {
            "pond": self.pond.pk,
            "water_temp_c": str(temp),
            "dissolved_oxygen_mg_l": str(do),
            "ph": str(ph),
            "rainfall_mm": "0",
        })
        return resp

    def test_low_do_critical_creates_alert(self):
        self._post_weather(do=3.5)  # below 4.0 → critical
        alert = FarmAlert.objects.filter(pond=self.pond, alert_type="low_oxygen", level="critical")
        self.assertTrue(alert.exists(), "Critical low-DO alert should be created")

    def test_low_do_warning_creates_alert(self):
        self._post_weather(do=4.5)  # between 4.0 and 5.0 → warning
        alert = FarmAlert.objects.filter(pond=self.pond, alert_type="low_oxygen", level="warning")
        self.assertTrue(alert.exists())

    def test_high_temp_critical_creates_alert(self):
        self._post_weather(temp=35.0)
        alert = FarmAlert.objects.filter(pond=self.pond, alert_type="high_temp", level="critical")
        self.assertTrue(alert.exists())

    def test_high_temp_warning_creates_alert(self):
        self._post_weather(temp=32.0)
        alert = FarmAlert.objects.filter(pond=self.pond, alert_type="high_temp", level="warning")
        self.assertTrue(alert.exists())

    def test_low_temp_warning_creates_alert(self):
        self._post_weather(temp=13.0)
        alert = FarmAlert.objects.filter(pond=self.pond, alert_type="low_temp", level="warning")
        self.assertTrue(alert.exists())

    def test_ph_out_of_range_creates_alert(self):
        self._post_weather(ph=5.9)   # below 6.5
        alert = FarmAlert.objects.filter(pond=self.pond, alert_type="ph_out")
        self.assertTrue(alert.exists())

    def test_normal_conditions_do_not_create_alerts(self):
        self._post_weather(temp=27.0, do=6.5, ph=7.2)
        self.assertFalse(FarmAlert.objects.filter(pond=self.pond).exists(),
                         "Healthy readings must not generate alerts")

    def test_duplicate_unresolved_alert_not_created(self):
        """Posting bad readings twice should not duplicate the same alert."""
        self._post_weather(do=3.5)
        self._post_weather(do=3.5)
        count = FarmAlert.objects.filter(
            pond=self.pond, alert_type="low_oxygen", level="critical", resolved=False
        ).count()
        self.assertEqual(count, 1, "Duplicate unresolved alerts must not be created")

    def test_high_mortality_auto_alert(self):
        """Logging >50 deaths should create a critical mortality alert."""
        url  = reverse("farm:mortality_create")
        resp = self.client.post(url, {
            "batch": self.batch.pk,
            "date": date.today().isoformat(),
            "count": 75,
            "cause": "disease",
        })
        alert = FarmAlert.objects.filter(alert_type="high_mortality", level="critical")
        self.assertTrue(alert.exists(), "High mortality alert should fire for >50 deaths")

    def test_small_mortality_does_not_create_alert(self):
        url  = reverse("farm:mortality_create")
        self.client.post(url, {
            "batch": self.batch.pk,
            "date": date.today().isoformat(),
            "count": 5,
            "cause": "unknown",
        })
        self.assertFalse(
            FarmAlert.objects.filter(alert_type="high_mortality").exists(),
            "Mortality ≤ 50 must not trigger alert",
        )


# ─────────────────────────────────────────────────────────────────────────────
# 6. Model property tests
# ─────────────────────────────────────────────────────────────────────────────

class ModelPropertyTests(TestCase):
    """Unit tests for model-level computed properties."""

    def setUp(self):
        self.pond  = make_pond()
        self.batch = make_batch(self.pond, count=1000, weight_g=50.0)

    def test_batch_initial_biomass_kg(self):
        # No growth records: 1000 × 50g = 50 000g = 50.0 kg
        self.assertAlmostEqual(self.batch.latest_biomass_kg, 50.0, places=2)

    def test_batch_biomass_updates_with_growth_record(self):
        GrowthRecord.objects.create(
            batch=self.batch,
            date=date.today(),
            surviving_count=950,
            avg_weight_g=Decimal("200.00"),
        )
        # 950 × 200g = 190 000g = 190.0 kg
        self.assertAlmostEqual(self.batch.latest_biomass_kg, 190.0, places=2)

    def test_batch_current_age_days(self):
        # Stocked 30 days ago in make_batch
        self.assertGreaterEqual(self.batch.current_age_days, 29)
        self.assertLessEqual(self.batch.current_age_days, 31)

    def test_harvest_gross_revenue(self):
        harvest = HarvestRecord.objects.create(
            batch=self.batch,
            harvest_date=date.today(),
            harvested_count=800,
            avg_weight_g=Decimal("480.00"),
            total_weight_kg=Decimal("384.00"),
            price_per_kg=Decimal("220.00"),
        )
        expected = 384.00 * 220.00
        self.assertAlmostEqual(harvest.gross_revenue, expected, places=2)

    def test_farm_alert_resolve(self):
        alert = FarmAlert.objects.create(
            pond=self.pond,
            alert_type="custom",
            level="info",
            message="Manual test",
        )
        self.assertFalse(alert.resolved)
        alert.resolve()
        self.assertTrue(alert.resolved)
        self.assertIsNotNone(alert.resolved_at)

    def test_pond_str(self):
        self.assertEqual(str(self.pond), "Test Pond")

    def test_fish_batch_str_contains_species_and_pond(self):
        s = str(self.batch)
        self.assertIn("Tilapia", s)
        self.assertIn("Test Pond", s)


# ─────────────────────────────────────────────────────────────────────────────
# 7. Service / business-logic tests
# ─────────────────────────────────────────────────────────────────────────────

class ServiceTests(TestCase):
    """Unit tests for feed_calculator and growth_prediction services."""
 
    def setUp(self):
        self.pond    = make_pond("Service Pond")
        self.batch   = make_batch(self.pond, count=2000, weight_g=80.0)
        make_feeding_profile()          # 20–32°C → 3% of biomass
        make_daily_weather(temp=27.0)   # factor = 1.0
        make_weather(self.pond, temp=27.0)
 
    def test_smart_feed_returns_positive_value(self):
        result = smart_feed_kg_for_batch(self.batch)
        self.assertIsNotNone(result, "Feed calculator should return a value")
        self.assertGreater(result, 0)
 
    def test_smart_feed_calculation_is_correct(self):
        """
        Biomass = 2000 × 80g = 160 kg
        Profile rate = 3 %
        Temperature factor for 27°C = 1.0
        Expected = 160 × 0.03 × 1.0 = 4.8 kg
        """
        result = smart_feed_kg_for_batch(self.batch)
        self.assertAlmostEqual(result, 4.8, delta=0.05)
 
    def test_smart_feed_falls_back_to_default_rate_without_profile(self):
        """
        FIX (was: test_smart_feed_returns_none_without_profile)
 
        The original test asserted assertIsNone() but that is wrong.
        When no FeedingProfile matches, the calculator uses the built-in
        DEFAULT_FEED_RATE_PCT = 3.0 % and still returns a positive float.
 
        Biomass = 160 kg, default rate 3 %, factor 1.0 → 4.8 kg.
        """
        FeedingProfile.objects.all().delete()
        result = smart_feed_kg_for_batch(self.batch)
        self.assertIsNotNone(result,
            "Feed calculator must use the built-in 3% default when no "
            "FeedingProfile is configured — it must not return None.")
        self.assertGreater(result, 0,
            "Feed calculator must return a positive value even without a profile.")
        # Should still be close to 4.8 kg (same default rate)
        self.assertAlmostEqual(result, 4.8, delta=0.1,
            msg="Default rate should produce approximately the same result "
                "as a 3%-profile for this batch.")
 
    def test_growth_prediction_returns_required_keys(self):
        result = predict_batch_growth(self.batch)
        required = [
            "current_avg_weight_g",
            "predicted_next_avg_weight_g",
            "predicted_daily_gain_g",
            "effective_fcr",
            "estimated_days_to_market",
            "estimated_harvest_date",
            "target_market_weight_g",
        ]
        for key in required:
            self.assertIn(key, result, f"Prediction missing key: {key}")
 
    def test_growth_prediction_current_weight_matches_batch(self):
        result = predict_batch_growth(self.batch)
        self.assertAlmostEqual(result["current_avg_weight_g"], 80.0, delta=1.0)
 
    def test_growth_prediction_uses_latest_growth_record(self):
        from decimal import Decimal
        from datetime import date
        GrowthRecord.objects.create(
            batch=self.batch,
            date=date.today(),
            surviving_count=1900,
            avg_weight_g=Decimal("250.00"),
        )
        result = predict_batch_growth(self.batch)
        self.assertAlmostEqual(result["current_avg_weight_g"], 250.0, delta=1.0)
 
    def test_growth_prediction_days_to_market_decreases_with_higher_weight(self):
        """A heavier batch should need fewer days to reach market weight."""
        light_batch = make_batch(self.pond, species="carp", count=500, weight_g=50.0)
        heavy_batch = make_batch(self.pond, species="carp", count=500, weight_g=450.0)
        pred_light = predict_batch_growth(light_batch)
        pred_heavy = predict_batch_growth(heavy_batch)
        self.assertGreater(
            pred_light["estimated_days_to_market"],
            pred_heavy["estimated_days_to_market"],
        )