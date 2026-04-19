from django import forms
from django.contrib.auth import get_user_model
from django.contrib.auth.forms import (
    PasswordChangeForm as _PasswordChangeForm,
    SetPasswordForm,
)
from django.core.exceptions import ValidationError

User = get_user_model()


class LoginForm(forms.Form):
    email = forms.EmailField(
        widget=forms.EmailInput(attrs={"placeholder": "you@example.com",
                                       "autofocus": True}),
        label="Email address",
    )
    password = forms.CharField(
        widget=forms.PasswordInput(attrs={"placeholder": "••••••••"}),
        label="Password",
    )
    remember_me = forms.BooleanField(required=False, label="Stay signed in for 30 days")

    def clean_email(self):
        return self.cleaned_data["email"].strip().lower()


class OTPForm(forms.Form):
    otp = forms.CharField(
        max_length=6, min_length=6,
        widget=forms.TextInput(attrs={
            "placeholder": "000000",
            "inputmode": "numeric",
            "autocomplete": "one-time-code",
            "autofocus": True,
            "style": "letter-spacing:0.3em;font-size:1.4rem;text-align:center",
        }),
        label="6-digit code",
    )

    def clean_otp(self):
        val = self.cleaned_data["otp"].strip()
        if not val.isdigit():
            raise ValidationError("Enter digits only.")
        return val


class ProfileForm(forms.ModelForm):
    class Meta:
        model  = User
        fields = ["first_name", "last_name", "phone",
                  "two_factor_enabled", "two_factor_method"]
        widgets = {
            "phone": forms.TextInput(attrs={"placeholder": "+880 1xxx-xxxxxx"}),
        }
        help_texts = {
            "two_factor_enabled": "Strongly recommended — adds OTP step after password.",
            "two_factor_method":  "Email OTP works without any extra app.",
        }


class PasswordChangeForm(_PasswordChangeForm):
    """Thin wrapper — just applies our widget style."""
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        for field in self.fields.values():
            field.widget.attrs.setdefault("class", "form-control")
