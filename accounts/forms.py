from django import forms
from django.core.exceptions import ValidationError
from django.contrib.auth import get_user_model
from django.contrib.auth.password_validation import validate_password
import random

User = get_user_model()


class ProfileForm(forms.ModelForm):
    class Meta:
        model = User
        fields = ["first_name", "last_name", "phone"]


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


class RegisterForm(forms.Form):
    first_name = forms.CharField(
        max_length=50,
        widget=forms.TextInput(attrs={"placeholder": "John"}),
        label="First name",
    )
    last_name = forms.CharField(
        max_length=50,
        widget=forms.TextInput(attrs={"placeholder": "Doe"}),
        label="Last name",
    )
    email = forms.EmailField(
        widget=forms.EmailInput(attrs={"placeholder": "you@example.com"}),
        label="Email address",
    )
    password1 = forms.CharField(
        widget=forms.PasswordInput(attrs={"placeholder": "Min. 8 characters"}),
        label="Password",
    )
    password2 = forms.CharField(
        widget=forms.PasswordInput(attrs={"placeholder": "Repeat password"}),
        label="Confirm password",
    )

    def clean_email(self):
        email = self.cleaned_data["email"].strip().lower()
        if User.objects.filter(email__iexact=email).exists():
            raise forms.ValidationError("An account with this email already exists.")
        return email

    def clean_password1(self):
        """Django's built-in password validators (e.g., common passwords, numeric only)"""
        password = self.cleaned_data.get("password1")
        validate_password(password)
        return password

    def clean(self):
        cleaned = super().clean()
        p1 = cleaned.get("password1")
        p2 = cleaned.get("password2")
        if p1 and p2 and p1 != p2:
            self.add_error("password2", "Passwords do not match.")
        return cleaned

    def save(self):
        data = self.cleaned_data
        email = data["email"]
        base_username = email.split("@")[0]
        
        # Safe username generation to avoid Race Conditions & multiple DB hits
        username = base_username
        if User.objects.filter(username=username).exists():
            username = f"{base_username}{random.randint(1000, 9999)}"

        user = User.objects.create_user(
            username=username,
            email=email,
            password=data["password1"],
            first_name=data["first_name"],
            last_name=data["last_name"],
            role="viewer",                 # default role for self-registered users
            two_factor_enabled=False,      # can enable later from profile
        )
        return user