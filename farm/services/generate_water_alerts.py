from ..models import FarmAlert, WeatherRecord
from ..notifications import send_email_notification


def generate_water_alerts(weather_record: WeatherRecord) -> None:
    """
    Auto-create FarmAlert entries and send email when water readings are out of range.
    Email is sent only to the pond owner's registered email address.
    """
    pond = weather_record.pond
    temp = float(weather_record.water_temp_c)
    do   = float(weather_record.dissolved_oxygen_mg_l)
    ph   = float(weather_record.ph)

    checks = [
        (do < 4.0,              "low_oxygen", "critical", f"🚨 CRITICAL: Pond {pond.name}: DO critically low at {do} mg/L (min 4.0) — fish may die!"),
        (do < 5.0,              "low_oxygen", "warning",  f"⚠️ WARNING: Pond {pond.name}: DO below optimum at {do} mg/L — check aeration"),
        (temp > 34.0,           "high_temp",  "critical", f"🚨 CRITICAL: Pond {pond.name}: Water temp critically high at {temp}°C — urgent action needed!"),
        (temp > 31.0,           "high_temp",  "warning",  f"⚠️ WARNING: Pond {pond.name}: Water temp elevated at {temp}°C — reduce feed"),
        (temp < 15.0,           "low_temp",   "warning",  f"⚠️ WARNING: Pond {pond.name}: Water temp low at {temp}°C — reduce feed significantly"),
        (ph < 6.5 or ph > 9.0, "ph_out",     "warning",  f"⚠️ WARNING: Pond {pond.name}: pH out of range at {ph} (safe: 6.5–9.0)"),
    ]

    new_alerts = []
    for condition, atype, level, msg in checks:
        if condition:
            exists = FarmAlert.objects.filter(
                pond=pond, alert_type=atype, resolved=False
            ).exists()
            if not exists:
                alert = FarmAlert.objects.create(
                    pond=pond, alert_type=atype, level=level, message=msg
                )
                new_alerts.append(alert)

    if new_alerts:
        subject = f"🚨 AquaSmart Water Quality Alert — {pond.name}"
        lines = [
            f"Water Quality Alert for Pond: {pond.name}",
            f"Logged at: {weather_record.timestamp.strftime('%Y-%m-%d %H:%M')}",
            "",
            "📊 Current Readings:",
            f"  🌡️  Water Temperature : {temp}°C",
            f"  💧 Dissolved Oxygen  : {do} mg/L",
            f"  🧪 pH Level          : {ph}",
            "",
            "⚠️ Alerts Triggered:",
        ]
        for alert in new_alerts:
            lines.append(f"  • [{alert.level.upper()}] {alert.message}")

        lines += [
            "",
            "Please take immediate action to prevent fish loss.",
            "Login to AquaSmart dashboard to resolve these alerts.",
        ]
        
        # Send only to the pond owner's own email (per-user isolation)
        owner_email = getattr(pond.owner, "email", "") if pond.owner else ""
        send_email_notification(subject, "\n".join(lines), recipient_email=owner_email)