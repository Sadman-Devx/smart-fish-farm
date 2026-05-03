from __future__ import annotations

from django.conf import settings
from django.core.mail import send_mail

try:
    from twilio.rest import Client
except Exception:  # pragma: no cover
    Client = None


def send_email_notification(subject: str, message: str, recipient_email: str = "") -> None:
    """
    Send email to a specific user.
    recipient_email: the user's own email — per-user isolation.
    Falls back to settings.FARM_NOTIFICATION_EMAIL if not provided.
    """
    recipient = recipient_email or getattr(settings, "FARM_NOTIFICATION_EMAIL", "")
    if not recipient:
        return
    send_mail(
        subject=subject,
        message=message,
        from_email=getattr(settings, "DEFAULT_FROM_EMAIL", "noreply@example.com"),
        recipient_list=[recipient],
        fail_silently=True,
    )


def send_sms_notification(message: str, to_number: str = "") -> bool:
    """
    Send SMS to a specific user's phone number.
    to_number: the user's own phone number — per-user isolation.
    Falls back to settings.TWILIO_TO_NUMBER if not provided.
    """
    sid     = getattr(settings, "TWILIO_ACCOUNT_SID", "")
    token   = getattr(settings, "TWILIO_AUTH_TOKEN", "")
    from_no = getattr(settings, "TWILIO_FROM_NUMBER", "")
    to_no   = to_number or getattr(settings, "TWILIO_TO_NUMBER", "")

    if not (sid and token and from_no and to_no and Client is not None):
        return False

    try:
        client = Client(sid, token)
        client.messages.create(
            body=message[:1600],
            from_=from_no,
            to=to_no,
        )
        return True
    except Exception as e:
        print(f"[SMS] Failed to {to_no}: {e}")
        return False


def send_whatsapp_notification(message: str, to_number: str = "") -> bool:
    """
    Send WhatsApp message to a specific user's phone number.
    to_number: the user's own phone number — per-user isolation.
    Falls back to settings.TWILIO_TO_NUMBER if not provided.
    """
    sid     = getattr(settings, "TWILIO_ACCOUNT_SID", "")
    token   = getattr(settings, "TWILIO_AUTH_TOKEN", "")
    from_no = getattr(settings, "TWILIO_FROM_NUMBER", "")
    to_no   = to_number or getattr(settings, "TWILIO_TO_NUMBER", "")

    if not (sid and token and from_no and to_no and Client is not None):
        return False

    try:
        client = Client(sid, token)
        client.messages.create(
            body=message[:1600],
            from_=f"whatsapp:{from_no}",
            to=f"whatsapp:{to_no}",
        )
        print(f"[WhatsApp] Message sent to {to_no}")
        return True
    except Exception as e:
        print(f"[WhatsApp] Failed to {to_no}: {e}")
        return False