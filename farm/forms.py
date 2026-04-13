from django import forms
from .models import (
    FeedLog, GrowthRecord, WeatherRecord, FishBatch,
    HarvestRecord, Expense, MortalityLog, FarmAlert, PondNote,
)


# ── Existing forms ────────────────────────────────────────────────────────────
class WeatherRecordForm(forms.ModelForm):
    class Meta:
        model = WeatherRecord
        fields = ["pond", "water_temp_c", "dissolved_oxygen_mg_l", "ph", "rainfall_mm"]


class GrowthRecordForm(forms.ModelForm):
    class Meta:
        model = GrowthRecord
        fields = ["batch", "date", "surviving_count", "avg_weight_g"]
        widgets = {"date": forms.DateInput(attrs={"type": "date"})}


class FeedLogForm(forms.ModelForm):
    def __init__(self, *args, batch=None, initial_amount_kg=None, **kwargs):
        super().__init__(*args, **kwargs)
        if batch is not None:
            self.fields["batch"].initial = batch
            self.fields["batch"].widget = forms.HiddenInput()
        if initial_amount_kg is not None:
            self.fields["feed_amount_kg"].initial = round(initial_amount_kg, 2)

    class Meta:
        model = FeedLog
        fields = ["batch", "date", "feed_amount_kg"]
        widgets = {"date": forms.DateInput(attrs={"type": "date"})}


# ── NEW: Harvest form ─────────────────────────────────────────────────────────
class HarvestRecordForm(forms.ModelForm):
    class Meta:
        model = HarvestRecord
        fields = [
            "batch", "harvest_date", "harvested_count",
            "avg_weight_g", "total_weight_kg", "price_per_kg",
            "buyer_name", "notes",
        ]
        widgets = {
            "harvest_date": forms.DateInput(attrs={"type": "date"}),
            "notes": forms.Textarea(attrs={"rows": 3}),
        }
        help_texts = {
            "price_per_kg": "Sale price in BDT per kg",
            "total_weight_kg": "Total weight of fish harvested (kg)",
        }


# ── NEW: Expense form ─────────────────────────────────────────────────────────
class ExpenseForm(forms.ModelForm):
    class Meta:
        model = Expense
        fields = ["date", "pond", "category", "amount", "description", "notes"]
        widgets = {
            "date": forms.DateInput(attrs={"type": "date"}),
            "notes": forms.Textarea(attrs={"rows": 2}),
        }


# ── NEW: Mortality log form ───────────────────────────────────────────────────
class MortalityLogForm(forms.ModelForm):
    class Meta:
        model = MortalityLog
        fields = ["batch", "date", "count", "cause", "notes"]
        widgets = {
            "date": forms.DateInput(attrs={"type": "date"}),
            "notes": forms.Textarea(attrs={"rows": 2}),
        }


# ── NEW: Farm alert form ──────────────────────────────────────────────────────
class FarmAlertForm(forms.ModelForm):
    class Meta:
        model = FarmAlert
        fields = ["pond", "alert_type", "level", "message"]
        widgets = {"message": forms.Textarea(attrs={"rows": 2})}


# ── NEW: Pond note form ───────────────────────────────────────────────────────
class PondNoteForm(forms.ModelForm):
    class Meta:
        model = PondNote
        fields = ["pond", "author", "body"]
        widgets = {"body": forms.Textarea(attrs={"rows": 3})}
