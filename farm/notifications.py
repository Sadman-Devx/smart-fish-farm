from __future__ import annotations

from django.conf import settings
from django.core.mail import send_mail

try:
    from twilio.rest import Client
except Exception:  # pragma: no cover
    Client = None


def send_email_notification(subject: str, message: str) -> None:
    recipient = getattr(settings, "FARM_NOTIFICATION_EMAIL", "")
    if not recipient:
        return
    send_mail(
        subject=subject,
        message=message,
        from_email=getattr(settings, "DEFAULT_FROM_EMAIL", "noreply@example.com"),
        recipient_list=[recipient],
        fail_silently=True,
    )


def send_sms_notification(message: str) -> bool:
    sid = getattr(settings, "TWILIO_ACCOUNT_SID", "")
    token = getattr(settings, "TWILIO_AUTH_TOKEN", "")
    from_no = getattr(settings, "TWILIO_FROM_NUMBER", "")
    to_no = getattr(settings, "TWILIO_TO_NUMBER", "")

    if not (sid and token and from_no and to_no and Client is not None):
        return False

    client = Client(sid, token)
    client.messages.create(
        body=message,
        from_=from_no,
        to=to_no,
    )
    return True

def send_whatsapp_notification(message: str) -> bool:
    """Send WhatsApp message via Twilio Sandbox."""
    sid     = getattr(settings, "TWILIO_ACCOUNT_SID", "")
    token   = getattr(settings, "TWILIO_AUTH_TOKEN", "")
    from_no = getattr(settings, "TWILIO_FROM_NUMBER", "")
    to_no   = getattr(settings, "TWILIO_TO_NUMBER", "")

    if not (sid and token and from_no and to_no and Client is not None):
        return False

    try:
        client = Client(sid, token)
        client.messages.create(
            body=message[:1600],  # WhatsApp max length
            from_=from_no,
            to=to_no,
        )
        print(f"[WhatsApp] Message sent to {to_no}")
        return True
    except Exception as e:
        print(f"[WhatsApp] Failed: {e}")
        return False