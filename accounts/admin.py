from django.contrib import admin
from .models import OTPToken, LoginAttempt, UserSession


@admin.register(OTPToken)
class OTPTokenAdmin(admin.ModelAdmin):
    list_display = ("user", "token", "expires_at", "used", "created_at")
    list_filter  = ("used",)
    readonly_fields = ("token", "created_at")


@admin.register(LoginAttempt)
class LoginAttemptAdmin(admin.ModelAdmin):
    list_display  = ("email", "success", "ip_address", "reason", "timestamp")
    list_filter   = ("success", "reason")
    search_fields = ("email", "ip_address")
    readonly_fields = ("email", "ip_address", "user_agent",
                       "success", "reason", "timestamp")

    def has_add_permission(self, request):
        return False


@admin.register(UserSession)
class UserSessionAdmin(admin.ModelAdmin):
    list_display = ("user", "device_hint", "ip_address",
                    "last_active", "is_active")
    list_filter  = ("is_active",)
    search_fields = ("user__email", "ip_address")

