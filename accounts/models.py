import secrets
import string
from datetime import timedelta

from django.contrib.auth.models import AbstractUser
from django.db import models
from django.utils import timezone


def _generate_otp():
    """Generate a 6-digit numeric OTP."""
    return "".join(secrets.choice(string.digits) for _ in range(6))


def _otp_expiry():
    return timezone.now() + timedelta(minutes=10)


# ── Custom User ───────────────────────────────────────────────────────────────
class User(AbstractUser):
    """
    Extended user with phone, 2FA toggle, and profile fields.
    """
    email = models.EmailField(unique=True)
    phone = models.CharField(max_length=20, blank=True,
                             help_text="Phone number for SMS OTP (optional)")
    avatar_initials = models.CharField(max_length=3, blank=True,
                                       help_text="Auto-set from name")
    role = models.CharField(
        max_length=20,
        choices=[
            ("owner",   "Farm Owner"),
            ("manager", "Farm Manager"),
            ("worker",  "Farm Worker"),
            ("viewer",  "Viewer (Read-only)"),
        ],
        default="manager",
    )
    two_factor_enabled = models.BooleanField(default=True)
    two_factor_method  = models.CharField(
        max_length=10,
        choices=[("email", "Email OTP"), ("totp", "Authenticator App")],
        default="email",
    )
    last_login_ip   = models.GenericIPAddressField(null=True, blank=True)
    last_login_ua   = models.TextField(blank=True)
    created_at      = models.DateTimeField(auto_now_add=True)

    USERNAME_FIELD  = "email"
    REQUIRED_FIELDS = ["username"]

    class Meta:
        verbose_name = "User"

    def save(self, *args, **kwargs):
        if not self.avatar_initials:
            parts = (self.get_full_name() or self.email).split()
            self.avatar_initials = "".join(p[0].upper() for p in parts[:2]) or "?"
        super().save(*args, **kwargs)

    def __str__(self):
        return self.email

    @property
    def display_name(self):
        return self.get_full_name() or self.email

    @property
    def can_edit(self):
        return self.role in ("owner", "manager")


# ── OTP Token ─────────────────────────────────────────────────────────────────
class OTPToken(models.Model):
    """Short-lived email OTP for 2FA login step."""
    user       = models.ForeignKey(User, on_delete=models.CASCADE,
                                   related_name="otp_tokens")
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
        return f"OTP for {self.user.email} (valid={self.is_valid()})"


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
    user        = models.ForeignKey(User, on_delete=models.CASCADE,
                                    related_name="sessions_tracked")
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
        return f"{self.user.email} – {self.device_hint or self.ip_address}"
