"""
farm/onboarding_views.py
─────────────────────────────────────────────────────────────────────────────
Four-step onboarding wizard for new users.

Flow
────
  POST /accounts/register/ → user created → redirect to onboarding:step1
  step1 → step2 → step3 → step4 → dashboard

Guard
─────
  Any view in the main farm app checks request.user.farm_profile.onboarding_complete.
  If False, the user is bounced back to the next incomplete step.
  The decorator `require_onboarding_complete` handles this.

Session key
───────────
  We use the database (FarmProfile) as the single source of truth.
  No onboarding state is stored in the session to avoid stale data.
"""
from __future__ import annotations

import functools
import requests

from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.http import JsonResponse
from django.shortcuts import get_object_or_404, redirect, render
from django.utils import timezone
from django.views.decorators.http import require_POST

from .models import FarmProfile
from .onboarding_forms import (
    OnboardingStep1Form,
    OnboardingStep2Form,
    OnboardingStep3Form,
    OnboardingStep4Form,
)
from .bd_geo import get_upazila_choices


# ─────────────────────────────────────────────────────────────────────────────
# Guard decorator — redirects incomplete users back to onboarding
# ─────────────────────────────────────────────────────────────────────────────

def require_onboarding_complete(view_func):
    """
    Wrap a farm view to bounce users with incomplete onboarding back to step 1.
    Applied to the main dashboard view only — other views are open.
    """
    @functools.wraps(view_func)
    @login_required
    def _wrapped(request, *args, **kwargs):
        try:
            profile = request.user.farm_profile
            if not profile.onboarding_complete:
                return redirect("farm:onboarding_step1")
        except FarmProfile.DoesNotExist:
            # New user — create a blank profile and start onboarding
            FarmProfile.objects.create(user=request.user)
            return redirect("farm:onboarding_step1")
        return view_func(request, *args, **kwargs)
    return _wrapped


def _get_or_create_profile(user) -> FarmProfile:
    """Return the FarmProfile for user, creating it if absent."""
    profile, _ = FarmProfile.objects.get_or_create(user=user)
    return profile


# ─────────────────────────────────────────────────────────────────────────────
# Step 1 — Farm Basics
# ─────────────────────────────────────────────────────────────────────────────

@login_required
def onboarding_step1(request):
    profile = _get_or_create_profile(request.user)

    # Already completed? Skip to dashboard.
    if profile.onboarding_complete:
        return redirect("farm:dashboard")

    if request.method == "POST":
        form = OnboardingStep1Form(request.POST, instance=profile)
        if form.is_valid():
            form.save()
            return redirect("farm:onboarding_step2")
    else:
        form = OnboardingStep1Form(instance=profile)

    return render(request, "farm/onboarding/step1.html", {
        "form":          form,
        "current_step":  1,
        "total_steps":   4,
        "step_title":    "Farm Information",
        "step_subtitle": "Tell us about your farm",
    })


# ─────────────────────────────────────────────────────────────────────────────
# Step 2 — Location
# ─────────────────────────────────────────────────────────────────────────────

@login_required
def onboarding_step2(request):
    profile = _get_or_create_profile(request.user)

    if profile.onboarding_complete:
        return redirect("farm:dashboard")

    if request.method == "POST":
        form = OnboardingStep2Form(request.POST)
        if form.is_valid():
            cd     = form.cleaned_data
            method = cd.get("location_method", "skip")

            if method == "gps":
                profile.latitude  = cd["latitude"]
                profile.longitude = cd["longitude"]
                profile.district  = ""
                profile.upazila   = ""
            elif method == "manual":
                profile.latitude  = None
                profile.longitude = None
                profile.district  = cd.get("district", "")
                profile.upazila   = cd.get("upazila", "")
            # "skip" — leave location fields unchanged

            profile.save(update_fields=["latitude", "longitude", "district", "upazila"])
            return redirect("farm:onboarding_step3")
    else:
        form = OnboardingStep2Form(initial={
            "latitude":        profile.latitude,
            "longitude":       profile.longitude,
            "district":        profile.district,
            "upazila":         profile.upazila,
            "location_method": "gps" if profile.latitude else ("manual" if profile.district else "skip"),
        })

    return render(request, "farm/onboarding/step2.html", {
        "form":          form,
        "current_step":  2,
        "total_steps":   4,
        "step_title":    "Your Location",
        "step_subtitle": "We use your location for accurate weather data",
        # Pass existing profile values so JS can pre-populate
        "saved_lat":     profile.latitude,
        "saved_lng":     profile.longitude,
        "saved_district":profile.district,
        "saved_upazila": profile.upazila,
    })


@login_required
def upazila_options(request):
    """
    AJAX endpoint: GET /onboarding/upazilas/?district=Chandpur
    Returns JSON list of upazila options for a district.
    """
    district = request.GET.get("district", "")
    choices  = get_upazila_choices(district)
    # Return as list of {value, label} dicts
    options  = [{"value": v, "label": l} for v, l in choices if v]
    return JsonResponse({"options": options})


# ─────────────────────────────────────────────────────────────────────────────
# Step 3 — Fish Info
# ─────────────────────────────────────────────────────────────────────────────

@login_required
def onboarding_step3(request):
    profile = _get_or_create_profile(request.user)

    if profile.onboarding_complete:
        return redirect("farm:dashboard")

    if request.method == "POST":
        form = OnboardingStep3Form(request.POST)
        if form.is_valid():
            profile.species                   = form.cleaned_data["species"]
            profile.farming_experience_years  = form.cleaned_data["farming_experience_years"]
            profile.save(update_fields=["species", "farming_experience_years"])
            return redirect("farm:onboarding_step4")
    else:
        form = OnboardingStep3Form(initial={
            "species":                  profile.species or [],
            "farming_experience_years": profile.farming_experience_years,
        })

    return render(request, "farm/onboarding/step3.html", {
        "form":          form,
        "current_step":  3,
        "total_steps":   4,
        "step_title":    "Fish & Experience",
        "step_subtitle": "Tell us what you farm and your experience level",
    })


# ─────────────────────────────────────────────────────────────────────────────
# Step 4 — Weather Integration
# ─────────────────────────────────────────────────────────────────────────────

def _fetch_weather_for_profile(profile: FarmProfile) -> dict:
    """
    Fetch current weather from OpenWeatherMap using the profile's location.
    Note: This is a synchronous call. It is acceptable here because we specifically
    want to show the user the weather result on this confirmation screen before
    they finish. (For general dashboard loading, we use cached data instead).

    Coordinate priority:
      1. GPS lat/lng stored in profile
      2. District name as a text query (e.g. "Chandpur,Bangladesh")
      3. Fall back to the global WEATHER_LOCATION setting

    Returns a dict with keys: temp_c, humidity, rain_mm, condition, success.
    """
    from django.conf import settings as django_settings

    api_key = getattr(django_settings, "WEATHER_API_KEY", "")
    url     = "https://api.openweathermap.org/data/2.5/weather"

    # Build request params
    if profile.latitude and profile.longitude:
        params = {
            "lat":   float(profile.latitude),
            "lon":   float(profile.longitude),
            "appid": api_key,
            "units": "metric",
        }
    elif profile.district:
        location_query = f"{profile.district},Bangladesh"
        params = {"q": location_query, "appid": api_key, "units": "metric"}
    else:
        location_query = getattr(django_settings, "WEATHER_LOCATION", "Dhaka,Bangladesh")
        params = {"q": location_query, "appid": api_key, "units": "metric"}

    if not api_key:
        return {
            "success":   False,
            "error":     "no_api_key",
            "temp_c":    None,
            "humidity":  None,
            "rain_mm":   0,
            "condition": "",
        }

    try:
        resp = requests.get(url, params=params, timeout=10)
        resp.raise_for_status()
        data = resp.json()

        temp_c    = float(data["main"]["temp"])
        humidity  = int(data["main"]["humidity"])
        condition = data["weather"][0]["main"]
        rain_mm   = float(data.get("rain", {}).get("1h", 0))

        # Persist to profile
        profile.weather_temp_c       = temp_c
        profile.weather_humidity_pct = humidity
        profile.weather_rain_mm      = rain_mm
        profile.weather_condition    = condition
        profile.weather_fetched_at   = timezone.now()
        profile.save(update_fields=[
            "weather_temp_c", "weather_humidity_pct",
            "weather_rain_mm", "weather_condition", "weather_fetched_at",
        ])

        return {
            "success":   True,
            "temp_c":    round(temp_c, 1),
            "humidity":  humidity,
            "rain_mm":   round(rain_mm, 2),
            "condition": condition,
        }

    except Exception as exc:
        return {
            "success":   False,
            "error":     str(exc),
            "temp_c":    None,
            "humidity":  None,
            "rain_mm":   0,
            "condition": "",
        }


@login_required
def onboarding_step4(request):
    profile = _get_or_create_profile(request.user)

    if profile.onboarding_complete:
        return redirect("farm:dashboard")

    weather_result = None

    if request.method == "POST":
        # "Finish" button clicked — mark onboarding done and go to dashboard
        profile.onboarding_complete = True
        profile.save(update_fields=["onboarding_complete"])
        
        # ✅ FIXED: Changed request.user.display_name to get_full_name()
        user_name = request.user.get_full_name() or request.user.username
        messages.success(
            request,
            f"Welcome to AquaSmart, {user_name}! "
            "Your farm profile is ready. 🐟",
        )
        return redirect("farm:dashboard")

    # GET — auto-fetch weather and show confirmation screen
    weather_result = _fetch_weather_for_profile(profile)

    # Determine location label for display
    if profile.latitude and profile.longitude:
        location_label = f"{float(profile.latitude):.4f}°N, {float(profile.longitude):.4f}°E"
    elif profile.district:
        parts = [p for p in (profile.upazila, profile.district) if p]
        location_label = ", ".join(parts)
    else:
        location_label = "Default location"

    return render(request, "farm/onboarding/step4.html", {
        "form":           OnboardingStep4Form(),
        "current_step":   4,
        "total_steps":    4,
        "step_title":     "Weather Integration",
        "step_subtitle":  "Live weather data for your farm location",
        "weather":        weather_result,
        "location_label": location_label,
        "profile":        profile,
    })


# ─────────────────────────────────────────────────────────────────────────────
# Skip onboarding (escape hatch)
# ─────────────────────────────────────────────────────────────────────────────

@require_POST
@login_required
def onboarding_skip(request):
    """
    Allow the user to skip the entire onboarding flow.
    Marks it complete so they won't be redirected again.
    """
    profile = _get_or_create_profile(request.user)
    profile.onboarding_complete = True
    profile.save(update_fields=["onboarding_complete"])
    messages.info(
        request,
        "Onboarding skipped. You can update your farm profile anytime from Settings.",
    )
    return redirect("farm:dashboard")