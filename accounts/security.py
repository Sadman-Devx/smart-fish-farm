"""
Security helpers: rate limiting, IP extraction, device detection,
session tracking, brute-force lockout.
"""
from __future__ import annotations

import hashlib
from datetime import timedelta

from django.core.cache import cache
from django.utils import timezone


# ── IP extraction ─────────────────────────────────────────────────────────────

def get_client_ip(request) -> str | None:
    x_forwarded = request.META.get("HTTP_X_FORWARDED_FOR")
    if x_forwarded:
        return x_forwarded.split(",")[0].strip()
    return request.META.get("REMOTE_ADDR")


# ── Device hint ───────────────────────────────────────────────────────────────

def device_hint_from_ua(ua: str) -> str:
    ua = ua.lower()
    if "mobile" in ua or "android" in ua:
        device = "Mobile"
    elif "tablet" in ua or "ipad" in ua:
        device = "Tablet"
    else:
        device = "Desktop"

    if "chrome" in ua:
        browser = "Chrome"
    elif "firefox" in ua:
        browser = "Firefox"
    elif "safari" in ua:
        browser = "Safari"
    elif "edge" in ua:
        browser = "Edge"
    else:
        browser = "Browser"

    if "windows" in ua:
        os_ = "Windows"
    elif "mac" in ua:
        os_ = "Mac"
    elif "linux" in ua:
        os_ = "Linux"
    elif "android" in ua:
        os_ = "Android"
    elif "iphone" in ua or "ipad" in ua:
        os_ = "iOS"
    else:
        os_ = "Unknown OS"

    return f"{device} · {browser} on {os_}"


# ── Brute-force rate limiting ─────────────────────────────────────────────────

MAX_ATTEMPTS   = 5          # max failures before lockout
LOCKOUT_SECS   = 15 * 60   # 15-minute lockout
ATTEMPT_WINDOW = 10 * 60   # sliding 10-minute window


def _cache_key(email: str, ip: str | None) -> str:
    raw = f"login:{email}:{ip or 'noip'}"
    return hashlib.sha256(raw.encode()).hexdigest()[:32]


def is_locked_out(email: str, ip: str | None) -> bool:
    key   = _cache_key(email, ip)
    count = cache.get(key, 0)
    return count >= MAX_ATTEMPTS


def record_failure(email: str, ip: str | None) -> int:
    key   = _cache_key(email, ip)
    count = cache.get(key, 0) + 1
    cache.set(key, count, LOCKOUT_SECS)
    return count


def clear_failures(email: str, ip: str | None) -> None:
    cache.delete(_cache_key(email, ip))


def remaining_lockout_seconds(email: str, ip: str | None) -> int:
    key = _cache_key(email, ip)
    ttl = cache.ttl(key) if hasattr(cache, "ttl") else LOCKOUT_SECS
    return max(int(ttl or 0), 0)


# ── Session tracking ──────────────────────────────────────────────────────────

def register_session(user, request) -> None:
    from .models import UserSession

    # session save করো আগে, তারপর key নাও
    if not request.session.session_key:
        request.session.save()

    sk   = request.session.session_key or ""
    ip   = get_client_ip(request)
    ua   = request.META.get("HTTP_USER_AGENT", "")
    hint = device_hint_from_ua(ua)

    if not sk:
        return  # session key না থাকলে skip করো

    UserSession.objects.update_or_create(
        session_key=sk,
        defaults=dict(
            user=user, ip_address=ip,
            user_agent=ua, device_hint=hint,
            is_active=True,
        ),
    )


def deactivate_session(session_key: str) -> None:
    from .models import UserSession
    UserSession.objects.filter(session_key=session_key).update(is_active=False)


# ── OTP helpers ───────────────────────────────────────────────────────────────

def create_otp(user) -> "OTPToken":
    from .models import OTPToken
    # Invalidate any unused previous OTPs
    OTPToken.objects.filter(user=user, used=False).update(used=True)
    return OTPToken.objects.create(user=user)


def send_otp_email(user, otp_token) -> None:
    from django.core.mail import send_mail
    from django.conf import settings

    subject = "AquaSmart — Your login code"
    message = (
        f"Hello {user.display_name},\n\n"
        f"Your one-time login code is:\n\n"
        f"  {otp_token.token}\n\n"
        f"This code expires in 10 minutes.\n"
        f"If you did not request this, please ignore this email.\n\n"
        f"— AquaSmart Security"
    )

    # ── Always print to terminal so you never get locked out ──────────────────
    print("\n" + "=" * 50)
    print(f"  OTP FOR: {user.email}")
    print(f"  CODE:    {otp_token.token}")
    print(f"  EXPIRES: 10 minutes")
    print("=" * 50 + "\n")

    # ── Send real email (works when EMAIL_BACKEND=smtp in .env) ───────────────
    try:
        send_mail(
            subject=subject,
            message=message,
            from_email=getattr(
                settings, "DEFAULT_FROM_EMAIL", "noreply@aquasmart.local"
            ),
            recipient_list=[user.email],
            fail_silently=False,
        )
        print(f"[OTP] Email sent to {user.email}")

    except Exception as e:
        print(f"[OTP] Email sending failed: {e}")
        print("[OTP] Use the code printed in terminal above.")

