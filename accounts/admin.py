"""
Farm Admin Configuration
======================

Registers admin interfaces for authentication, sessions, and security logs.
Ensures sensitive fields remain read-only and cascading delete is disabled.
"""

from django.contrib import admin
from django.utils.html import format_html
from django.utils.timezone import now

from .models import OTPToken, LoginAttempt, UserSession


@admin.register(OTPToken)
class OTPTokenAdmin(admin.ModelAdmin):
    """
    Manages OTP tokens.
    Uses select_related to optimize DB queries on list view.
    """
    list_display = ("user", "token", "expires_at", "used", "created_at")
    list_filter = ("used", "user")
    search_fields = ("user__email",)
    list_select_related = ("user",)  # Prevents N+1 queries for user lookups

    readonly_fields = ("token", "created_at")
    date_hierarchy = "created_at"

    fieldsets = (
        ("Token Info", {
            "fields": ("user", "token", "expires_at", "used"),
        }),
        ("System Info", {
            "fields": ("created_at",),
            "classes": ("collapse",),
        }),
    )


@admin.register(LoginAttempt)
class LoginAttemptAdmin(admin.ModelAdmin):
    """
    Logs all login attempts (successful or failed).
    Fields are strictly read-only to maintain forensic integrity.
    """
    list_display = ("email", "success", "ip_address", "reason", "timestamp")
    list_display_links = ("email", "timestamp")
    list_filter = ("success", "reason")
    search_fields = ("email", "ip_address")
    readonly_fields = (
        "email", "ip_address", "user_agent", "success", "reason", "timestamp"
    )
    date_hierarchy = "timestamp"
    actions = None  # Block bulk delete to prevent accidental forensic data loss

    fieldsets = (
        ("Attempt Info", {
            "fields": ("email", "success", "ip_address", "reason"),
        }),
        ("Details", {
            "fields": ("user_agent", "timestamp"),
            "classes": ("collapse",),
        }),
    )

    def has_add_permission(self, request):
        return False

    def has_delete_permission(self, request):
        return False


@admin.register(UserSession)
class UserSessionAdmin(admin.ModelAdmin):
    """
    Tracks active user sessions and their IP addresses.
    Sessions are purged automatically by the app; manual deletion is blocked to prevent bugs.
    """
    list_display = ("user", "device_hint", "ip_address", "last_active", "is_active")
    list_filter = ("is_active", "device_hint")
    search_fields = ("user__email", "ip_address")

    date_hierarchy = "last_active"
    list_display_links = ("user", "last_active")

    fieldsets = (
        ("Session Info", {
            "fields": ("user", "ip_address", "device_hint", "is_active"),
        }),
        ("Timing", {
            "fields": ("last_active",),
            "classes": ("collapse",),
        }),
    )

    def has_add_permission(self, request):
        return False

    def has_delete_permission(self, request):
        return False