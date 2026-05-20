"""
farm/forms.py
─────────────
All forms that have a Pond or FishBatch dropdown accept a `user` kwarg so
the queryset is scoped to that user's data only.

Usage in views:
    form = WeatherRecordForm(request.POST, user=request.user)
    form = WeatherRecordForm(user=request.user)   # GET

Date display:
    All date fields use FlatpickrDateInput which renders DD/MM/YYYY
    consistently across all browsers and devices.

    To activate, add this to your base template <head>:
        <link rel="stylesheet"
              href="https://cdn.jsdelivr.net/npm/flatpickr/dist/flatpickr.min.css">

    And before </body>:
        <script src="https://cdn.jsdelivr.net/npm/flatpickr"></script>
        <script>
          document.addEventListener("DOMContentLoaded", function () {
            flatpickr(".flatpickr-date", {
              dateFormat: "Y-m-d",   // submitted to Django  → 2025-05-20
              altInput:   true,      // show a user-friendly input
              altFormat:  "d/m/Y",   // what the user sees   → 20/05/2025
              allowInput: true,      // allow manual typing
              locale: { firstDayOfWeek: 1 },
            });
          });
        </script>
"""
from django import forms
from .models import (
    FeedLog, GrowthRecord, WeatherRecord, FishBatch, Pond,
    HarvestRecord, Expense, MortalityLog, FarmAlert, PondNote, FarmProfile,
)
from .bd_geo import DISTRICT_CHOICES, get_upazila_choices


# ── Reusable date widget ──────────────────────────────────────────────────────

class FlatpickrDateInput(forms.DateInput):
    """
    A <input type="date"> that Flatpickr enhances to always show DD/MM/YYYY,
    regardless of the user's browser locale or OS region settings.

    - Adds the CSS class "flatpickr-date" so the JS snippet in base.html
      picks it up automatically.
    - Django still receives the value in YYYY-MM-DD (the native <input type="date">
      wire format), so no server-side changes are needed.
    - input_formats on each form field covers the fallback path when JS is
      disabled (manual typing).
    """
    input_type = "date"

    def __init__(self, *args, **kwargs):
        kwargs.setdefault("attrs", {})
        # Merge with any caller-supplied classes
        existing = kwargs["attrs"].get("class", "")
        kwargs["attrs"]["class"] = (existing + " flatpickr-date").strip()
        super().__init__(*args, **kwargs)


# Shared input_formats accepted by every DateField in this file.
# Order matters: DD/MM/YYYY first so manual entry is intuitive;
# YYYY-MM-DD second as the programmatic/HTML wire format.
DATE_INPUT_FORMATS = ["%d/%m/%Y", "%Y-%m-%d"]


# ── Mixin: inject user-scoped querysets ───────────────────────────────────────

class UserScopedFormMixin:
    """
    Call super().__init__() first, then call _limit_to_user(user).
    Subclasses declare which fields need limiting via `pond_fields` and
    `batch_fields` class attributes.
    """
    pond_fields  = []   # form field names that are Pond FKs
    batch_fields = []   # form field names that are FishBatch FKs

    def _limit_to_user(self, user):
        if user is None:
            return
        for fname in self.pond_fields:
            if fname in self.fields:
                self.fields[fname].queryset = Pond.objects.filter(owner=user)
        for fname in self.batch_fields:
            if fname in self.fields:
                self.fields[fname].queryset = FishBatch.objects.filter(pond__owner=user)


# ── WeatherRecordForm ─────────────────────────────────────────────────────────

class WeatherRecordForm(UserScopedFormMixin, forms.ModelForm):
    pond_fields = ["pond"]

    def __init__(self, *args, user=None, **kwargs):
        super().__init__(*args, **kwargs)
        self._limit_to_user(user)

    class Meta:
        model  = WeatherRecord
        fields = ["pond", "water_temp_c", "dissolved_oxygen_mg_l", "ph", "rainfall_mm"]
        # WeatherRecord has no date field exposed in this form, nothing to change.


# ── GrowthRecordForm ──────────────────────────────────────────────────────────

class GrowthRecordForm(UserScopedFormMixin, forms.ModelForm):
    batch_fields = ["batch"]

    date = forms.DateField(
        widget=FlatpickrDateInput(),
        input_formats=DATE_INPUT_FORMATS,
    )

    def __init__(self, *args, user=None, **kwargs):
        super().__init__(*args, **kwargs)
        self._limit_to_user(user)

    class Meta:
        model   = GrowthRecord
        fields  = ["batch", "date", "surviving_count", "avg_weight_g"]


# ── FeedLogForm ───────────────────────────────────────────────────────────────

class FeedLogForm(UserScopedFormMixin, forms.ModelForm):
    batch_fields = ["batch"]

    date = forms.DateField(
        widget=FlatpickrDateInput(),
        input_formats=DATE_INPUT_FORMATS,
    )

    def __init__(self, *args, batch=None, initial_amount_kg=None, user=None, **kwargs):
        super().__init__(*args, **kwargs)
        self._limit_to_user(user)
        if batch is not None:
            self.fields["batch"].initial = batch
            self.fields["batch"].widget  = forms.HiddenInput()
        if initial_amount_kg is not None:
            self.fields["feed_amount_kg"].initial = round(initial_amount_kg, 2)

    class Meta:
        model   = FeedLog
        fields  = ["batch", "date", "feed_amount_kg"]


# ── HarvestRecordForm ─────────────────────────────────────────────────────────

class HarvestRecordForm(UserScopedFormMixin, forms.ModelForm):
    batch_fields = ["batch"]

    harvest_date = forms.DateField(
        widget=FlatpickrDateInput(),
        input_formats=DATE_INPUT_FORMATS,
    )

    def __init__(self, *args, user=None, **kwargs):
        super().__init__(*args, **kwargs)
        self._limit_to_user(user)

    class Meta:
        model  = HarvestRecord
        fields = [
            "batch", "harvest_date", "harvested_count",
            "avg_weight_g", "total_weight_kg", "price_per_kg",
            "buyer_name", "notes",
        ]
        widgets = {
            "notes": forms.Textarea(attrs={"rows": 3}),
        }
        help_texts = {
            "price_per_kg":    "Sale price in BDT per kg",
            "total_weight_kg": "Total weight of fish harvested (kg)",
        }


# ── ExpenseForm ───────────────────────────────────────────────────────────────

class ExpenseForm(UserScopedFormMixin, forms.ModelForm):
    pond_fields = ["pond"]

    date = forms.DateField(
        widget=FlatpickrDateInput(),
        input_formats=DATE_INPUT_FORMATS,
    )

    def __init__(self, *args, user=None, **kwargs):
        super().__init__(*args, **kwargs)
        self._limit_to_user(user)

    class Meta:
        model   = Expense
        fields  = ["date", "pond", "category", "amount", "description", "notes"]
        widgets = {
            "notes": forms.Textarea(attrs={"rows": 2}),
        }
        help_texts = {
            "category": "Choose a category like Feed, Transport, Doctor, Medicine, Labour, etc.",
            "amount":   "Amount spent in BDT. Enter the actual cost for the expense.",
        }


# ── MortalityLogForm ──────────────────────────────────────────────────────────

class MortalityLogForm(UserScopedFormMixin, forms.ModelForm):
    batch_fields = ["batch"]

    date = forms.DateField(
        widget=FlatpickrDateInput(),
        input_formats=DATE_INPUT_FORMATS,
    )

    def __init__(self, *args, user=None, **kwargs):
        super().__init__(*args, **kwargs)
        self._limit_to_user(user)

    class Meta:
        model   = MortalityLog
        fields  = ["batch", "date", "count", "cause", "notes"]
        widgets = {
            "notes": forms.Textarea(attrs={"rows": 2}),
        }


# ── FarmAlertForm ─────────────────────────────────────────────────────────────

class FarmAlertForm(UserScopedFormMixin, forms.ModelForm):
    pond_fields = ["pond"]

    def __init__(self, *args, user=None, **kwargs):
        super().__init__(*args, **kwargs)
        self._limit_to_user(user)

    class Meta:
        model   = FarmAlert
        fields  = ["pond", "alert_type", "level", "message"]
        widgets = {"message": forms.Textarea(attrs={"rows": 2})}
        # FarmAlert has no date field exposed here.


# ── PondNoteForm ──────────────────────────────────────────────────────────────

class PondNoteForm(UserScopedFormMixin, forms.ModelForm):
    pond_fields = ["pond"]

    def __init__(self, *args, user=None, **kwargs):
        super().__init__(*args, **kwargs)
        self._limit_to_user(user)

    class Meta:
        model   = PondNote
        fields  = ["pond", "author", "body"]
        widgets = {"body": forms.Textarea(attrs={"rows": 3})}
        # PondNote has no date field exposed here.


# ── PondForm ──────────────────────────────────────────────────────────────────
# owner is set in the view (not shown to the user)

class PondForm(forms.ModelForm):
    class Meta:
        model  = Pond
        fields = ["name", "area_m2", "max_depth_m"]
        help_texts = {
            "area_m2":     "Surface area in square meters",
            "max_depth_m": "Maximum depth in meters",
        }


# ── FishBatchForm ─────────────────────────────────────────────────────────────

class FishBatchForm(UserScopedFormMixin, forms.ModelForm):
    pond_fields = ["pond"]

    stocking_date = forms.DateField(
        widget=FlatpickrDateInput(),
        input_formats=DATE_INPUT_FORMATS,
    )
    target_harvest_date = forms.DateField(
        widget=FlatpickrDateInput(),
        input_formats=DATE_INPUT_FORMATS,
        required=False,   # keep consistent with model's blank=True/null=True
    )

    def __init__(self, *args, user=None, **kwargs):
        super().__init__(*args, **kwargs)
        self._limit_to_user(user)

    class Meta:
        model   = FishBatch
        fields  = ["pond", "species", "stocking_date", "initial_count",
                   "initial_avg_weight_g", "target_harvest_date", "notes"]
        widgets = {
            "notes": forms.Textarea(attrs={"rows": 2}),
        }


# ── FarmProfileForm (For Onboarding) ─────────────────────────────────────────

class FarmProfileForm(forms.ModelForm):
    # District data comes from bd_geo
    district = forms.ChoiceField(choices=DISTRICT_CHOICES)
    # Upazila will be empty initially; populated by JS on district change
    upazila  = forms.ChoiceField(choices=[("", "— Select Upazila —")])

    class Meta:
        model  = FarmProfile
        fields = [
            "farm_name", "size_acres", "num_ponds", "water_source",
            "district", "upazila", "species", "farming_experience_years",
        ]
        widgets = {
            "notes": forms.Textarea(attrs={"rows": 2}),
        }

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)

        # If editing an existing profile that already has a district,
        # load the matching upazila list so the form renders correctly.
        if self.instance and getattr(self.instance, "district", None):
            self.fields["upazila"].choices = get_upazila_choices(self.instance.district)

    def clean_upazila(self):
        """Security check: ensure the upazila belongs to the chosen district."""
        district = self.cleaned_data.get("district")
        upazila  = self.cleaned_data.get("upazila")

        valid_upazilas = [u[0] for u in get_upazila_choices(district)]
        if upazila not in valid_upazilas:
            raise forms.ValidationError(
                "Selected upazila is not valid for the chosen district."
            )
        return upazila