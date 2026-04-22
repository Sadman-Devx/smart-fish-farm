"""
farm/onboarding_forms.py
─────────────────────────────────────────────────────────────────────────────
Four Django forms, one per onboarding step.

Step 1 — Farm basics       (farm_name, size_acres, num_ponds, water_source)
Step 2 — Location          (GPS coords OR district/upazila dropdown)
Step 3 — Fish info         (species multi-select, farming_experience_years)
Step 4 — Weather confirm   (no user input — auto-fetches and displays result)
"""
from __future__ import annotations

from django import forms
from django.core.exceptions import ValidationError

from .models import FarmProfile
from .bd_geo import DISTRICT_CHOICES, get_upazila_choices


# ─────────────────────────────────────────────────────────────────────────────
# Step 1 — Farm Basics
# ─────────────────────────────────────────────────────────────────────────────

class OnboardingStep1Form(forms.ModelForm):
    """Collect core farm information."""

    class Meta:
        model  = FarmProfile
        fields = ["farm_name", "size_acres", "num_ponds", "water_source"]
        widgets = {
            "farm_name": forms.TextInput(attrs={
                "placeholder": "e.g. Rahim's Fish Farm",
                "autofocus":   True,
            }),
            "size_acres": forms.NumberInput(attrs={
                "placeholder": "e.g. 5.5",
                "min": "0.1",
                "step": "0.1",
            }),
            "num_ponds": forms.NumberInput(attrs={
                "placeholder": "e.g. 3",
                "min": "1",
            }),
        }
        labels = {
            "farm_name":   "Farm name",
            "size_acres":  "Total farm size (acres)",
            "num_ponds":   "Number of ponds",
            "water_source": "Primary water source",
        }

    def clean_farm_name(self):
        name = self.cleaned_data.get("farm_name", "").strip()
        if not name:
            raise ValidationError("Please enter your farm name.")
        return name

    def clean_size_acres(self):
        size = self.cleaned_data.get("size_acres")
        if size is not None and size <= 0:
            raise ValidationError("Farm size must be greater than 0.")
        return size

    def clean_num_ponds(self):
        n = self.cleaned_data.get("num_ponds")
        if n is not None and n < 1:
            raise ValidationError("You must have at least 1 pond.")
        return n


# ─────────────────────────────────────────────────────────────────────────────
# Step 2 — Location
# ─────────────────────────────────────────────────────────────────────────────

class OnboardingStep2Form(forms.Form):
    """
    Location step.

    The template tries browser GPS first (via JavaScript).
    If coordinates are obtained, they are posted in hidden lat/lng fields.
    If the user denies GPS, the district/upazila dropdowns become visible.

    Validation rules:
      • Either (latitude AND longitude) must be present, OR
      • (district AND upazila) must be present.
      • If none are provided the form is still valid — location is optional.
    """
    # Hidden fields populated by JavaScript GPS
    latitude  = forms.DecimalField(
        max_digits=10, decimal_places=7,
        required=False,
        widget=forms.HiddenInput(),
    )
    longitude = forms.DecimalField(
        max_digits=10, decimal_places=7,
        required=False,
        widget=forms.HiddenInput(),
    )

    # Dropdown fallback (shown only when GPS is denied)
    district = forms.ChoiceField(
        choices=DISTRICT_CHOICES,
        required=False,
        label="District",
    )
    upazila  = forms.CharField(
        required=False,
        label="Upazila",
        widget=forms.Select(choices=[("", "— Select District first —")]),
    )

    # Tracks which method the user used (set by JS before submit)
    location_method = forms.ChoiceField(
        choices=[("gps", "gps"), ("manual", "manual"), ("skip", "skip")],
        required=False,
        widget=forms.HiddenInput(),
        initial="skip",
    )

    def clean(self):
        cleaned = super().clean()
        method  = cleaned.get("location_method", "skip")
        lat     = cleaned.get("latitude")
        lng     = cleaned.get("longitude")
        district = cleaned.get("district", "").strip()
        upazila  = cleaned.get("upazila", "").strip()

        if method == "gps":
            if lat is None or lng is None:
                raise ValidationError(
                    "GPS coordinates were not received. "
                    "Please allow location access or use the district/upazila dropdown."
                )
        elif method == "manual":
            if not district:
                self.add_error("district", "Please select your district.")
            if not upazila:
                self.add_error("upazila", "Please select your upazila.")

        return cleaned


# ─────────────────────────────────────────────────────────────────────────────
# Step 3 — Fish Information
# ─────────────────────────────────────────────────────────────────────────────

SPECIES_CHOICES = [
    ("tilapia", "Tilapia"),
    ("catfish", "Catfish"),
    ("rui",     "Rui (Rohu)"),
    ("katla",   "Katla"),
    ("pangash", "Pangash (Pangasius)"),
]

class OnboardingStep3Form(forms.Form):
    """Fish species (multi-select checkboxes) and farming experience."""

    species = forms.MultipleChoiceField(
        choices=SPECIES_CHOICES,
        widget=forms.CheckboxSelectMultiple(),
        label="Which species do you farm?",
        help_text="Select all that apply.",
        error_messages={"required": "Please select at least one species."},
    )
    farming_experience_years = forms.IntegerField(
        min_value=0,
        max_value=80,
        label="Years of fish farming experience",
        widget=forms.NumberInput(attrs={
            "placeholder": "e.g. 5",
            "min": "0",
            "max": "80",
        }),
        help_text="Enter 0 if you are just starting out.",
    )

    def clean_species(self):
        species = self.cleaned_data.get("species", [])
        if not species:
            raise ValidationError("Please select at least one species.")
        # Validate against allowed values
        valid = {s[0] for s in SPECIES_CHOICES}
        for s in species:
            if s not in valid:
                raise ValidationError(f"'{s}' is not a valid species choice.")
        return list(species)


# ─────────────────────────────────────────────────────────────────────────────
# Step 4 — Weather confirmation (no user input)
# ─────────────────────────────────────────────────────────────────────────────

class OnboardingStep4Form(forms.Form):
    """
    No user-facing fields.
    The view fetches weather using saved coordinates / district
    and presents the result. User just clicks "Finish".
    """
    pass