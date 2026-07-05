"""
farm/worker_forms.py
────────────────────
Forms for Worker and SalaryPayment models.
Follows the same pattern as farm/forms.py — FlatpickrDateInput, UserScopedFormMixin, etc.
"""
from django import forms
from .models import Worker, SalaryPayment, Pond, FarmProfile
from .forms import FlatpickrDateInput, DATE_INPUT_FORMATS


# ── Worker Form ───────────────────────────────────────────────────────────────

class WorkerForm(forms.ModelForm):
    """Add / Edit a worker."""

    class Meta:
        model  = Worker
        fields = [
            "name", "phone", "nid", "role",
            "status", "join_date", "monthly_salary",
            "assigned_ponds", "notes",
        ]
        widgets = {
            "name": forms.TextInput(attrs={
                "class": "form-control",
                "placeholder": "Worker-full name",
            }),
            "phone": forms.TextInput(attrs={
                "class": "form-control",
                "placeholder": "01XXXXXXXXX"
            }),
            "nid": forms.TextInput(attrs={
                "class": "form-control",
                "placeholder": "National ID Number (optional)"
            }),
            "role": forms.Select(attrs={"class": "form-control"}),
            "status": forms.Select(attrs={"class": "form-control"}),
            "join_date": FlatpickrDateInput(attrs={"class": "form-control"}),
            "monthly_salary": forms.NumberInput(attrs={
                "class": "form-control",
                "placeholder": "Monthly Salary (BDT)",
                "min": "0",
                "step": "100",
            }),
            "assigned_ponds": forms.CheckboxSelectMultiple(),
            "notes": forms.Textarea(attrs={
                "class": "form-control",
                "rows": 3,
                "placeholder": "Additional Information (Optional)"
            }),
        }

    def __init__(self, *args, user=None, **kwargs):
        super().__init__(*args, **kwargs)
        # Only show ponds belonging to this user
        if user is not None:
            self.fields["assigned_ponds"].queryset = Pond.objects.filter(owner=user)
        self.fields["join_date"].input_formats = DATE_INPUT_FORMATS
        self.fields["assigned_ponds"].required = False


# ── Salary Payment Form ───────────────────────────────────────────────────────

class SalaryPaymentForm(forms.ModelForm):
    """Record a salary payment for a worker."""

    class Meta:
        model  = SalaryPayment
        fields = ["worker", "month", "amount_paid", "status", "paid_on", "notes"]
        widgets = {
            "worker": forms.Select(attrs={"class": "form-control"}),
            "month": FlatpickrDateInput(attrs={
                "class": "form-control",
                "placeholder": "First day of the month (YYYY-MM-01)"
            }),
            "amount_paid": forms.NumberInput(attrs={
                "class": "form-control",
                "placeholder": "Amount Paid (BDT)",
                "min": "0",
                "step": "100",
            }),
            "status": forms.Select(attrs={"class": "form-control"}),
            "paid_on": FlatpickrDateInput(attrs={"class": "form-control"}),
            "notes": forms.Textarea(attrs={
                "class": "form-control",
                "rows": 2,
                "placeholder": "Comment (optional)"
            }),
        }

    def __init__(self, *args, user=None, **kwargs):
        super().__init__(*args, **kwargs)
        # Only show workers belonging to this user's farm
        if user is not None:
            try:
                farm = user.farm_profile
                self.fields["worker"].queryset = Worker.objects.filter(farm=farm)
            except FarmProfile.DoesNotExist:
                self.fields["worker"].queryset = Worker.objects.none()
        self.fields["month"].input_formats   = DATE_INPUT_FORMATS
        self.fields["paid_on"].input_formats = DATE_INPUT_FORMATS
        self.fields["paid_on"].required = False
