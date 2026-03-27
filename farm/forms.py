from django import forms

from .models import FeedLog, GrowthRecord, WeatherRecord, FishBatch


class WeatherRecordForm(forms.ModelForm):
    class Meta:
        model = WeatherRecord
        fields = ["pond", "water_temp_c", "dissolved_oxygen_mg_l", "ph", "rainfall_mm"]


class GrowthRecordForm(forms.ModelForm):
    class Meta:
        model = GrowthRecord
        fields = ["batch", "date", "surviving_count", "avg_weight_g"]
        widgets = {
            "date": forms.DateInput(attrs={"type": "date"}),
        }


class FeedLogForm(forms.ModelForm):
    def __init__(self, *args, batch: FishBatch | None = None, initial_amount_kg: float | None = None, **kwargs):
        super().__init__(*args, **kwargs)
        if batch is not None:
            self.fields["batch"].initial = batch
            self.fields["batch"].widget = forms.HiddenInput()
        if initial_amount_kg is not None:
            self.fields["feed_amount_kg"].initial = round(initial_amount_kg, 2)

    class Meta:
        model = FeedLog
        fields = ["batch", "date", "feed_amount_kg"]
        widgets = {
            "date": forms.DateInput(attrs={"type": "date"}),
        }

