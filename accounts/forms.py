from django import forms
from django.core.exceptions import ValidationError


class LoginForm(forms.Form):
    email = forms.EmailField(
        widget=forms.EmailInput(attrs={
            "placeholder": "you@example.com",
            "autofocus": True,
        }),
        label="Email address",
    )
    password = forms.CharField(
        widget=forms.PasswordInput(attrs={"placeholder": "••••••••"}),
        label="Password",
    )
    remember_me = forms.BooleanField(
        required=False, label="Stay signed in for 30 days"
    )

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