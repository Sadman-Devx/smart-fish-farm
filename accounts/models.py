# accounts/models.py

import secrets
import string
from datetime import timedelta

from django.contrib.auth.models import AbstractUser
from django.contrib.auth import get_user_model
from django.db import models                          # ← this was missing
from django.utils import timezone


# ── Custom User Model ─────────────────────────────────────────────────────────
class User(AbstractUser):
    ROLE_CHOICES = [
        ("owner",   "Farm Owner"),
        ("manager", "Farm Manager"),
        ("worker",  "Farm Worker"),
        ("viewer",  "Viewer (Read-only)"),
    ]
    METHOD_CHOICES = [
        ("email", "Email OTP"),
        ("totp",  "Authenticator App"),
    ]

    email              = models.EmailField(unique=True)
    phone              = models.CharField(max_length=20, blank=True)
    avatar_initials    = models.CharField(max_length=3, blank=True)
    role               = models.CharField(max_length=20, choices=ROLE_CHOICES, default="manager")
    two_factor_enabled = models.BooleanField(default=True)
    two_factor_method  = models.CharField(max_length=10, choices=METHOD_CHOICES, default="email")
    last_login_ip      = models.GenericIPAddressField(null=True, blank=True)
    last_login_ua      = models.TextField(blank=True)
    created_at         = models.DateTimeField(auto_now_add=True)

    USERNAME_FIELD  = "email"
    REQUIRED_FIELDS = ["username"]

    class Meta:
        verbose_name = "User"

    @property
    def display_name(self):
        full = self.get_full_name().strip()
        return full if full else self.email.split("@")[0]

    def save(self, *args, **kwargs):
        if not self.avatar_initials:
            parts = self.display_name.split()
            self.avatar_initials = "".join(p[0].upper() for p in parts[:2])
        super().save(*args, **kwargs)


# ── OTP helper functions ──────────────────────────────────────────────────────
def _generate_otp():
    """Generate a 6-digit numeric OTP."""
    return "".join(secrets.choice(string.digits) for _ in range(6))


def _otp_expiry():
    return timezone.now() + timedelta(minutes=10)


# ── OTP Token ─────────────────────────────────────────────────────────────────
class OTPToken(models.Model):
    """Short-lived email OTP for 2FA login step."""
    user       = models.ForeignKey(
                     'accounts.User', on_delete=models.CASCADE,
                     related_name="otp_tokens"
                 )
    token      = models.CharField(max_length=6, default=_generate_otp)
    expires_at = models.DateTimeField(default=_otp_expiry)
    used       = models.BooleanField(default=False)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["-created_at"]

    def is_valid(self):
        return not self.used and timezone.now() < self.expires_at

    def consume(self):
        self.used = True
        self.save()

    def __str__(self):
        return f"OTP for {self.user} (valid={self.is_valid()})"


# ── Login Attempt Log ─────────────────────────────────────────────────────────
class LoginAttempt(models.Model):
    """Audit log for every login attempt — success and failure."""
    email      = models.EmailField()
    ip_address = models.GenericIPAddressField(null=True, blank=True)
    user_agent = models.TextField(blank=True)
    success    = models.BooleanField(default=False)
    reason     = models.CharField(max_length=100, blank=True)
    timestamp  = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["-timestamp"]

    def __str__(self):
        status = "OK" if self.success else "FAIL"
        return f"[{status}] {self.email} @ {self.timestamp:%Y-%m-%d %H:%M}"


# ── Active Session ────────────────────────────────────────────────────────────
class UserSession(models.Model):
    """Track active sessions so users can revoke them."""
    user        = models.ForeignKey(
                      'accounts.User', on_delete=models.CASCADE,
                      related_name="sessions_tracked"
                  )
    session_key = models.CharField(max_length=40, unique=True)
    ip_address  = models.GenericIPAddressField(null=True, blank=True)
    user_agent  = models.TextField(blank=True)
    device_hint = models.CharField(max_length=120, blank=True)
    created_at  = models.DateTimeField(auto_now_add=True)
    last_active = models.DateTimeField(auto_now=True)
    is_active   = models.BooleanField(default=True)

    class Meta:
        ordering = ["-last_active"]

    def __str__(self):
        return f"{self.user} – {self.device_hint or self.ip_address}"