"""
farm/forms.py
─────────────
All forms that have a Pond or FishBatch dropdown accept a `user` kwarg so
the queryset is scoped to that user's data only.

Usage in views:
    form = WeatherRecordForm(request.POST, user=request.user)
    form = WeatherRecordForm(user=request.user)   # GET
"""
from django import forms
from .models import (
    FeedLog, GrowthRecord, WeatherRecord, FishBatch, Pond,
    HarvestRecord, Expense, MortalityLog, FarmAlert, PondNote, FarmProfile,
)
from .bd_geo import DISTRICT_CHOICES, get_upazila_choices


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


# ── GrowthRecordForm ──────────────────────────────────────────────────────────

class GrowthRecordForm(UserScopedFormMixin, forms.ModelForm):
    batch_fields = ["batch"]

    def __init__(self, *args, user=None, **kwargs):
        super().__init__(*args, **kwargs)
        self._limit_to_user(user)

    class Meta:
        model   = GrowthRecord
        fields  = ["batch", "date", "surviving_count", "avg_weight_g"]
        widgets = {"date": forms.DateInput(attrs={"type": "date"})}


# ── FeedLogForm ───────────────────────────────────────────────────────────────

class FeedLogForm(UserScopedFormMixin, forms.ModelForm):
    batch_fields = ["batch"]

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
        widgets = {"date": forms.DateInput(attrs={"type": "date"})}


# ── HarvestRecordForm ─────────────────────────────────────────────────────────

class HarvestRecordForm(UserScopedFormMixin, forms.ModelForm):
    batch_fields = ["batch"]

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
            "harvest_date": forms.DateInput(attrs={"type": "date"}),
            "notes":        forms.Textarea(attrs={"rows": 3}),
        }
        help_texts = {
            "price_per_kg":    "Sale price in BDT per kg",
            "total_weight_kg": "Total weight of fish harvested (kg)",
        }


# ── ExpenseForm ───────────────────────────────────────────────────────────────

class ExpenseForm(UserScopedFormMixin, forms.ModelForm):
    pond_fields = ["pond"]

    def __init__(self, *args, user=None, **kwargs):
        super().__init__(*args, **kwargs)
        self._limit_to_user(user)

    class Meta:
        model   = Expense
        fields  = ["date", "pond", "category", "amount", "description", "notes"]
        widgets = {
            "date":  forms.DateInput(attrs={"type": "date"}),
            "notes": forms.Textarea(attrs={"rows": 2}),
        }
        help_texts = {
            "category": "Choose a category like Feed, Transport, Doctor, Medicine, Labour, etc.",
            "amount": "Amount spent in BDT. Enter the actual cost for the expense.",
        }


# ── MortalityLogForm ──────────────────────────────────────────────────────────

class MortalityLogForm(UserScopedFormMixin, forms.ModelForm):
    batch_fields = ["batch"]

    def __init__(self, *args, user=None, **kwargs):
        super().__init__(*args, **kwargs)
        self._limit_to_user(user)

    class Meta:
        model   = MortalityLog
        fields  = ["batch", "date", "count", "cause", "notes"]
        widgets = {
            "date":  forms.DateInput(attrs={"type": "date"}),
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


# ── PondForm ──────────────────────────────────────────────────────────────────
# owner is set in the view (not shown to the user)

class PondForm(forms.ModelForm):
    class Meta:
        model  = Pond
        fields = ["name", "area_m2", "max_depth_m"]
        help_texts = {
            "area_m2":    "Surface area in square meters",
            "max_depth_m": "Maximum depth in meters",
        }


# ── FishBatchForm ─────────────────────────────────────────────────────────────

class FishBatchForm(UserScopedFormMixin, forms.ModelForm):
    pond_fields = ["pond"]

    def __init__(self, *args, user=None, **kwargs):
        super().__init__(*args, **kwargs)
        self._limit_to_user(user)

    class Meta:
        model   = FishBatch
        fields  = ["pond", "species", "stocking_date", "initial_count",
                   "initial_avg_weight_g", "target_harvest_date", "notes"]
        widgets = {
            "stocking_date":       forms.DateInput(attrs={"type": "date"}),
            "target_harvest_date": forms.DateInput(attrs={"type": "date"}),
            "notes":               forms.Textarea(attrs={"rows": 2}),
        }


# ── FarmProfileForm (For Onboarding) ────────────────────────────────────────

class FarmProfileForm(forms.ModelForm):
    # District data comes from bd_geo
    district = forms.ChoiceField(choices=DISTRICT_CHOICES)
    # Upazila will be empty initially
    upazila = forms.ChoiceField(choices=[("", "— Select Upazila —")])

    class Meta:
        model = FarmProfile
        fields = [
            "farm_name", "size_acres", "num_ponds", "water_source",
            "district", "upazila", "species", "farming_experience_years",
        ]
        widgets = {
            "notes": forms.Textarea(attrs={"rows": 2}),
        }

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        
        # If the user has already selected a district (e.g., on an edit page)
        # Then load the upazilas for that district
        if self.instance and getattr(self.instance, 'district', None):
            self.fields['upazila'].choices = get_upazila_choices(self.instance.district)

    def clean_upazila(self):
        """Security check: Ensure user cannot select an upazila from the wrong district."""
        district = self.cleaned_data.get("district")
        upazila = self.cleaned_data.get("upazila")
        
        valid_upazilas = [u[0] for u in get_upazila_choices(district)]
        if upazila not in valid_upazilas:
            raise forms.ValidationError("Selected upazila is not valid for the chosen district.")
        return upazila