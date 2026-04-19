from __future__ import annotations

from django.contrib import messages
from django.contrib.auth import (
    authenticate, get_user_model,
    login as auth_login,
    logout as auth_logout,
    update_session_auth_hash,
)
from django.contrib.auth.decorators import login_required
from django.shortcuts import get_object_or_404, redirect, render
from django.utils import timezone
from django.views.decorators.http import require_POST
from django.views.decorators.cache import never_cache
from django.views.decorators.debug import sensitive_post_parameters

from .forms import LoginForm, OTPForm, ProfileForm, PasswordChangeForm
from .models import LoginAttempt, OTPToken, UserSession
from .security import (
    clear_failures, create_otp, deactivate_session,
    device_hint_from_ua, get_client_ip,
    is_locked_out, record_failure,
    register_session, send_otp_email,
)

User = get_user_model()

# Session key used to carry the pre-auth user between step-1 and step-2
_PENDING_USER_KEY = "_pending_auth_user_id"


# ── Step 1: Email + Password ──────────────────────────────────────────────────

@never_cache
@sensitive_post_parameters("password")
def login_view(request):
    if request.user.is_authenticated:
        return redirect("farm:dashboard")

    form = LoginForm(request.POST or None)

    if request.method == "POST" and form.is_valid():
        email    = form.cleaned_data["email"]
        password = form.cleaned_data["password"]
        remember = form.cleaned_data["remember_me"]
        ip       = get_client_ip(request)
        ua       = request.META.get("HTTP_USER_AGENT", "")

        # ── Brute-force check ──
        if is_locked_out(email, ip):
            LoginAttempt.objects.create(
                email=email, ip_address=ip, user_agent=ua,
                success=False, reason="locked_out",
            )
            form.add_error(None,
                "Too many failed attempts. Account temporarily locked for 15 minutes.")
            return render(request, "accounts/login.html", {"form": form})

        # ── Authenticate ──
        user = authenticate(request, username=email, password=password)

        if user is None:
            count = record_failure(email, ip)
            LoginAttempt.objects.create(
                email=email, ip_address=ip, user_agent=ua,
                success=False, reason="bad_credentials",
            )
            remaining = max(0, 5 - count)
            form.add_error(None,
                f"Invalid email or password. "
                f"{remaining} attempt{'s' if remaining != 1 else ''} remaining before lockout.")
            return render(request, "accounts/login.html", {"form": form})

        if not user.is_active:
            form.add_error(None, "This account has been deactivated.")
            return render(request, "accounts/login.html", {"form": form})

        # ── 2FA branch ──
        if user.two_factor_enabled:
            # Store pending user in session (not logged in yet)
            request.session[_PENDING_USER_KEY] = user.pk
            request.session["_pending_remember"] = remember

            otp = create_otp(user)
            send_otp_email(user, otp)

            return redirect("accounts:verify_otp")

        # ── No 2FA — log straight in ──
        _complete_login(request, user, remember, ip, ua)
        return redirect("farm:dashboard")

    return render(request, "accounts/login.html", {"form": form})


# ── Step 2: OTP Verification ──────────────────────────────────────────────────

@never_cache
def verify_otp_view(request):
    user_id = request.session.get(_PENDING_USER_KEY)
    if not user_id:
        return redirect("accounts:login")

    user = get_object_or_404(User, pk=user_id)
    form = OTPForm(request.POST or None)
    error = None

    if request.method == "POST" and form.is_valid():
        code = form.cleaned_data["otp"]
        ip   = get_client_ip(request)
        ua   = request.META.get("HTTP_USER_AGENT", "")

        token = (
            OTPToken.objects
            .filter(user=user, token=code, used=False)
            .order_by("-created_at")
            .first()
        )

        if token and token.is_valid():
            token.consume()
            clear_failures(user.email, ip)
            remember = request.session.pop("_pending_remember", False)
            del request.session[_PENDING_USER_KEY]
            _complete_login(request, user, remember, ip, ua)
            return redirect("farm:dashboard")
        else:
            error = "Invalid or expired code. Please check and try again."
            LoginAttempt.objects.create(
                email=user.email, ip_address=ip, user_agent=ua,
                success=False, reason="bad_otp",
            )

    masked_email = _mask_email(user.email)
    return render(request, "accounts/verify_otp.html", {
        "form": form,
        "masked_email": masked_email,
        "error": error,
        "user_display": user.display_name,
    })


@require_POST
def resend_otp_view(request):
    user_id = request.session.get(_PENDING_USER_KEY)
    if not user_id:
        return redirect("accounts:login")
    user = get_object_or_404(User, pk=user_id)
    otp  = create_otp(user)
    send_otp_email(user, otp)
    messages.success(request, "A new code has been sent to your email.")
    return redirect("accounts:verify_otp")


# ── Logout ────────────────────────────────────────────────────────────────────

@require_POST
@login_required
def logout_view(request):
    sk = request.session.session_key
    if sk:
        deactivate_session(sk)
    auth_logout(request)
    messages.success(request, "You have been signed out.")
    return redirect("accounts:login")


# ── Profile & Password ────────────────────────────────────────────────────────

@login_required
def profile_view(request):
    form = ProfileForm(request.POST or None, instance=request.user)
    if request.method == "POST" and form.is_valid():
        form.save()
        messages.success(request, "Profile updated.")
        return redirect("accounts:profile")
    return render(request, "accounts/profile.html", {"form": form})


@login_required
def change_password_view(request):
    form = PasswordChangeForm(request.user, request.POST or None)
    if request.method == "POST" and form.is_valid():
        user = form.save()
        update_session_auth_hash(request, user)  # keeps user logged in
        messages.success(request, "Password changed successfully.")
        return redirect("accounts:profile")
    return render(request, "accounts/change_password.html", {"form": form})


# ── Active Sessions ───────────────────────────────────────────────────────────

@login_required
def sessions_view(request):
    sessions = UserSession.objects.filter(
        user=request.user, is_active=True
    )
    current_sk = request.session.session_key
    login_log  = LoginAttempt.objects.filter(
        email=request.user.email
    ).order_by("-timestamp")[:20]
    return render(request, "accounts/sessions.html", {
        "sessions": sessions,
        "current_sk": current_sk,
        "login_log": login_log,
    })


@require_POST
@login_required
def revoke_session_view(request, session_id):
    sess = get_object_or_404(
        UserSession, pk=session_id, user=request.user
    )
    deactivate_session(sess.session_key)
    # Also flush Django session if it's the active one
    from django.contrib.sessions.models import Session as DjSession
    try:
        DjSession.objects.filter(session_key=sess.session_key).delete()
    except Exception:
        pass
    messages.success(request, "Session revoked.")
    return redirect("accounts:sessions")


# ── Helpers ───────────────────────────────────────────────────────────────────

def _complete_login(request, user, remember: bool, ip: str, ua: str) -> None:
    """Final login step — set session, log attempt, track session."""
    auth_login(request, user, backend="accounts.backends.EmailBackend")

    if not remember:
        request.session.set_expiry(0)          # expires on browser close
    else:
        request.session.set_expiry(30 * 86400) # 30 days

    user.last_login_ip = ip
    user.last_login_ua = ua
    user.save(update_fields=["last_login_ip", "last_login_ua", "last_login"])

    LoginAttempt.objects.create(
        email=user.email, ip_address=ip,
        user_agent=ua, success=True,
    )
    register_session(user, request)


def _mask_email(email: str) -> str:
    local, domain = email.split("@", 1)
    visible = local[:2] if len(local) > 2 else local[0]
    return f"{visible}{'*' * (len(local) - len(visible))}@{domain}"
