from django.contrib import admin
from django.contrib.auth.admin import UserAdmin as BaseUserAdmin
from .models import User, OTPToken, LoginAttempt, UserSession


@admin.register(User)
class UserAdmin(BaseUserAdmin):
    list_display  = ("email", "get_full_name", "role", "two_factor_enabled",
                     "is_active", "last_login")
    list_filter   = ("role", "two_factor_enabled", "is_active", "is_staff")
    search_fields = ("email", "first_name", "last_name")
    ordering      = ("email",)
    fieldsets     = BaseUserAdmin.fieldsets + (
        ("Farm Profile", {
            "fields": ("phone", "role", "avatar_initials",
                       "two_factor_enabled", "two_factor_method",
                       "last_login_ip"),
        }),
    )
    add_fieldsets = (
        (None, {
            "classes": ("wide",),
            "fields": ("email", "username", "password1", "password2",
                       "role", "two_factor_enabled"),
        }),
    )


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
