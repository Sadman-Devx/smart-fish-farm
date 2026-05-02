"""
Fish Doctor AI Agent — Google Gemini Version (FREE) with Multi-language Support
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
INTEGRATION:
  1. pip install google-genai
  2. .env: GOOGLE_API_KEY=your_key
  3. settings.py: GOOGLE_API_KEY = env('GOOGLE_API_KEY', default='')
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
"""

import json
import logging
import base64
import re
from datetime import timedelta
from django.utils import timezone

from django.conf import settings
from django.contrib.auth.decorators import login_required
from django.http import JsonResponse, StreamingHttpResponse
from django.shortcuts import render, get_object_or_404
from django.views.decorators.http import require_http_methods
from django.db.models import Count

from .models import DiseaseLog, DiseaseAlert

logger = logging.getLogger(__name__)

# ── Gemini model fallback list ────────────────────────────────────────────────
# প্রথমটা quota শেষ হলে পরেরটা try করবে
GEMINI_MODELS = [
    "models/gemini-2.5-flash",
    "models/gemini-2.5-flash-lite-preview",
    "models/gemma-3-27b-it",
]

# ── Disease response format per language ──────────────────────────────────────
DISEASE_FORMAT = {
    "Bengali (Bangla)": """\
🔍 **রোগ সনাক্তকরণ**
[রোগের নাম — নিশ্চিততার মাত্রা: উচ্চ/মাঝারি/কম]

🦠 **কারণ**
[কেন এই রোগ হয়েছে — বিস্তারিত]

⚠️ **লক্ষণ**
[ছবিতে বা বর্ণনায় যা দেখা যাচ্ছে]

💊 **চিকিৎসা**
[ধাপে ধাপে — কী ওষুধ, কতটুকু, কতদিন]

🛡️ **প্রতিরোধ**
[ভবিষ্যতে কীভাবে রক্ষা করবে]

⚡ **এখনই করণীয়**
[জরুরি পদক্ষেপ — সময় গুরুত্বপূর্ণ]""",

    "English": """\
🔍 **Disease Identification**
[Disease name — confidence: High/Medium/Low]

🦠 **Cause**
[Why this disease occurred — detailed]

⚠️ **Symptoms**
[What is visible in the image or description]

💊 **Treatment**
[Step-by-step — medicine, dosage, duration]

🛡️ **Prevention**
[How to protect in the future]

⚡ **Immediate Action**
[Emergency steps — time is important]""",
}


# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
# PROMPT BUILDER
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

def build_system_prompt(language: str, species: str = "General") -> str:
    """Build a language-specific system prompt for Fish Doctor."""
    species_context = ""
    if species != "General":
        species_context = (
            f"\nThe farmer is asking about {species} fish specifically. "
            f"Focus your diagnosis and advice on this species.\n"
        )
    fmt = DISEASE_FORMAT.get(language, DISEASE_FORMAT["English"])

    return f"""You are "Fish Doctor" — a highly experienced, warm, and friendly fish disease expert AI.
You are part of the AquaSmart Fish Farm Management System.

Your expertise:
- Fish disease identification from images with high accuracy
- Water quality problem analysis
- General fish farming advice (feeding, water management, pond care)
- Disease prevention and treatment
- Natural conversation — answering any fish farming related questions

CRITICAL LANGUAGE RULE:
You MUST respond ONLY in {language}.
Do not use any other language. Even if the user writes in a different language, always reply in {language}.

CONVERSATION RULES:
- Be warm, friendly, and conversational — like a trusted friend who is also an expert.
- When the user greets you or makes small talk, respond naturally. Do NOT jump into disease format.
- When analyzing a fish image, be thorough. Look carefully at color changes, lesions, fin condition,
  eye appearance, body posture, and skin texture.

When you receive a fish image or disease description, use this format:
{species_context}
{fmt}

For general questions and conversation, respond naturally and warmly — no need to use the format above.
You genuinely care about the farmer's fish and livelihood."""


# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
# GEMINI CLIENT
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

def get_gemini_client():
    """Create and return a Google Gemini client."""
    try:
        from google import genai
        return genai.Client(api_key=settings.GOOGLE_API_KEY)
    except ImportError:
        raise RuntimeError("google-genai not found. Run: pip install google-genai")


def _is_quota_error(error_str: str) -> bool:
    """Check if an error string indicates a rate limit / quota issue."""
    s = error_str.lower()
    return "429" in error_str or "quota" in s or "rate" in s or "resource_exhausted" in s


# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
# DISEASE ANALYSIS HELPERS
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

def detect_severity(text: str) -> str:
    """Detect severity level from AI reply text."""
    t = text.lower()
    critical_words = [
        'critical', 'জরুরি', 'মারা যাচ্ছে', 'dying', 'dead', 'মরে',
        'সংকট', 'emergency', 'তীব্র', 'severe', 'immediate',
    ]
    medium_words = [
        'সতর্ক', 'warning', 'চিকিৎসা', 'treatment', 'মাঝারি',
        'moderate', 'সমস্যা', 'problem',
    ]
    if any(w in t for w in critical_words):
        return 'critical'
    if any(w in t for w in medium_words):
        return 'medium'
    return 'low'


def extract_disease_name(text: str) -> str:
    """Try to extract disease name from the AI response."""
    patterns = [
        r'\*\*([^*]+?)\s*[—\-–]\s*(?:নিশ্চিততা|confidence)',
        r'রোগের নাম[:\s]*\*{0,2}([^\*\n]+)',
        r'Disease (?:name|Identification)[:\s]*\*{0,2}([^\*\n]+)',
        r'🔍\s*\*{0,2}([^\*\n]+?)\*{0,2}\s*[—\-–]',
    ]
    for pat in patterns:
        m = re.search(pat, text, re.IGNORECASE)
        if m:
            name = m.group(1).strip()
            if 3 < len(name) < 100:
                return name
    m = re.search(r'🔍[^\n]*\n\s*[*]*([^\n*]+)', text)
    if m:
        name = m.group(1).strip()
        if 3 < len(name) < 100:
            return name
    return "Unknown"


def is_disease_reply(text: str) -> bool:
    """Return True if the AI reply looks like a disease diagnosis."""
    return bool(
        '🔍' in text or '💊' in text or '🦠' in text
        or 'চিকিৎসা' in text.lower()
        or 'treatment' in text.lower()
    )


def save_disease_log_and_check_recurring(request, reply_text, species, severity):
    """
    Save DiseaseLog. Update or create DiseaseAlert.
    Returns (occurrence_count, is_recurring).
    """
    if not is_disease_reply(reply_text):
        return 0, False

    disease_name = extract_disease_name(reply_text)
    user = request.user

    # Save the log
    DiseaseLog.objects.create(
        user=user,
        disease_name=disease_name,
        species=species,
        severity=severity,
        ai_response=reply_text[:3000],
    )

    # Count occurrences in last 30 days
    thirty_days_ago = timezone.now() - timedelta(days=30)
    recent_count = DiseaseLog.objects.filter(
        user=user,
        disease_name=disease_name,
        detected_at__gte=thirty_days_ago,
    ).count()

    is_recurring = recent_count >= 3

    # Update or create DiseaseAlert
    DiseaseAlert.objects.update_or_create(
        user=user,
        disease_name=disease_name,
        defaults={
            "occurrence_count": recent_count,
            "resolved": False,
        },
    )

    return recent_count, is_recurring


# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
# SHARED: build Gemini message history + current parts
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

def _build_gemini_messages(types, history, images, image_data_url, image_type, user_message):
    """Build gemini_history list and current_parts list from request data."""
    gemini_history = []
    for turn in history[-20:]:
        role = turn.get("role")
        text = turn.get("content", "")
        if role == "user":
            gemini_history.append(
                types.Content(role="user", parts=[types.Part(text=text)])
            )
        elif role == "assistant":
            gemini_history.append(
                types.Content(role="model", parts=[types.Part(text=text)])
            )

    current_parts = []

    if images:
        for img_obj in images[:4]:
            raw = img_obj.get("data", "")
            if "," in raw:
                raw = raw.split(",", 1)[1]
            current_parts.append(types.Part(
                inline_data=types.Blob(
                    mime_type=img_obj.get("type", "image/jpeg"),
                    data=base64.b64decode(raw),
                )
            ))
    elif image_data_url:
        raw_b64 = image_data_url
        if "," in raw_b64:
            raw_b64 = raw_b64.split(",", 1)[1]
        current_parts.append(types.Part(
            inline_data=types.Blob(
                mime_type=image_type,
                data=base64.b64decode(raw_b64),
            )
        ))

    text_part = user_message if user_message else (
        "Please analyze this fish image carefully. Identify any disease, "
        "explain the cause in detail, and provide step-by-step treatment "
        "and prevention advice."
    )
    current_parts.append(types.Part(text=text_part))
    gemini_history.append(types.Content(role="user", parts=current_parts))

    return gemini_history


# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
# VIEWS
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

@login_required
def fish_disease_agent(request):
    """Render the Fish Doctor chat page."""
    return render(request, 'farm/ai_agent.html')


@login_required
@require_http_methods(["POST"])
def fish_disease_chat(request):
    """
    Non-streaming chat endpoint with model fallback.
    Returns JSON with: reply, success, severity, is_disease,
                       disease_name, occurrence_count, recurring_alert
    """
    try:
        from google import genai
        from google.genai import types

        body           = json.loads(request.body)
        user_message   = body.get("message", "").strip()
        language       = body.get("language", "Bengali (Bangla)")
        image_data_url = body.get("image", "")
        image_type     = body.get("image_type", "image/jpeg")
        history        = body.get("history", [])
        images         = body.get("images", [])
        species        = body.get("species", "General")
        has_image      = bool(image_data_url) or bool(images)

        if not user_message and not has_image:
            return JsonResponse(
                {"error": "Please provide a message or an image."}, status=400
            )

        client        = get_gemini_client()
        system_prompt = build_system_prompt(language, species)
        gemini_history = _build_gemini_messages(
            types, history, images, image_data_url, image_type, user_message
        )

        # ── Model fallback loop ────────────────────────────────────────────
        response   = None
        last_error = ""

        for model_name in GEMINI_MODELS:
            try:
                response = client.models.generate_content(
                    model=model_name,
                    contents=gemini_history,
                    config=types.GenerateContentConfig(
                        system_instruction=system_prompt,
                        max_output_tokens=1500,
                        temperature=0.7,
                    ),
                )
                break  # success — stop trying
            except Exception as model_err:
                last_error = str(model_err)
                if _is_quota_error(last_error):
                    logger.warning(f"Quota exceeded on {model_name}, trying next model.")
                    continue
                raise  # non-quota error — re-raise immediately

        if response is None:
            return JsonResponse(
                {"error": "⏳ AI এখন ব্যস্ত। কিছুক্ষণ পরে আবার চেষ্টা করুন।"},
                status=429,
            )

        reply = response.text

        # ── Disease analysis & logging ─────────────────────────────────────
        disease  = is_disease_reply(reply)
        severity = detect_severity(reply) if disease else None
        occurrence_count = 0
        recurring_alert  = False

        if disease:
            occurrence_count, recurring_alert = save_disease_log_and_check_recurring(
                request, reply, species, severity or "low"
            )

        return JsonResponse({
            "reply":            reply,
            "success":          True,
            "is_disease":       disease,
            "severity":         severity,
            "disease_name":     extract_disease_name(reply) if disease else None,
            "occurrence_count": occurrence_count,
            "recurring_alert":  recurring_alert,
        })

    except Exception as e:
        logger.exception(f"fish_disease_chat error: {e}")
        error_msg = str(e)
        if "API_KEY" in error_msg.upper() or "authentication" in error_msg.lower():
            return JsonResponse(
                {"error": "Google API Key is invalid. Please check your .env file."},
                status=500,
            )
        return JsonResponse({"error": f"Server error: {error_msg}"}, status=500)


@login_required
@require_http_methods(["POST"])
def fish_disease_chat_stream(request):
    """
    Streaming chat endpoint (SSE) with model fallback.
    Words appear one by one (ChatGPT style).
    """
    try:
        from google import genai
        from google.genai import types

        body           = json.loads(request.body)
        user_message   = body.get("message", "").strip()
        language       = body.get("language", "Bengali (Bangla)")
        species        = body.get("species", "General")
        images         = body.get("images", [])
        image_data_url = body.get("image", "")
        image_type     = body.get("image_type", "image/jpeg")
        history        = body.get("history", [])
        has_image      = bool(images) or bool(image_data_url)

        if not user_message and not has_image:
            def _err():
                yield "data: " + json.dumps({"error": "Please provide a message or an image."}) + "\n\n"
            return StreamingHttpResponse(_err(), content_type="text/event-stream")

        client         = get_gemini_client()
        system_prompt  = build_system_prompt(language, species)
        gemini_history = _build_gemini_messages(
            types, history, images, image_data_url, image_type, user_message
        )

        def stream_generator():
            full_reply     = ""
            response_stream = None
            last_error     = ""

            # ── Model fallback loop ────────────────────────────────────────
            for model_name in GEMINI_MODELS:
                try:
                    response_stream = client.models.generate_content_stream(
                        model=model_name,
                        contents=gemini_history,
                        config=types.GenerateContentConfig(
                            system_instruction=system_prompt,
                            max_output_tokens=1800,
                            temperature=0.7,
                        ),
                    )
                    logger.info(f"Using model: {model_name}")
                    break  # success
                except Exception as model_err:
                    last_error = str(model_err)
                    if _is_quota_error(last_error):
                        logger.warning(f"Quota exceeded on {model_name}, trying next.")
                        continue
                    # non-quota error — send error event and stop
                    yield "data: " + json.dumps({"error": last_error}) + "\n\n"
                    return

            if response_stream is None:
                # All models exhausted
                yield "data: " + json.dumps({"rate_limit": True}) + "\n\n"
                return

            # ── Stream chunks to client ────────────────────────────────────
            try:
                for chunk in response_stream:
                    if chunk.text:
                        full_reply += chunk.text
                        yield "data: " + json.dumps({"chunk": chunk.text}) + "\n\n"

            except Exception as stream_err:
                err_str = str(stream_err)
                if _is_quota_error(err_str):
                    yield "data: " + json.dumps({"rate_limit": True}) + "\n\n"
                else:
                    yield "data: " + json.dumps({"error": err_str}) + "\n\n"
                return

            # ── Stream ended — disease analysis & DB logging ───────────────
            disease  = is_disease_reply(full_reply)
            severity = detect_severity(full_reply) if disease else None
            occurrence_count = 0
            recurring_alert  = False

            if disease:
                try:
                    occurrence_count, recurring_alert = save_disease_log_and_check_recurring(
                        request, full_reply, species, severity or "low"
                    )
                except Exception as db_err:
                    logger.error(f"DB logging error: {db_err}")

            yield "data: " + json.dumps({
                "done":             True,
                "is_disease":       disease,
                "severity":         severity,
                "disease_name":     extract_disease_name(full_reply) if disease else "",
                "occurrence_count": occurrence_count,
                "recurring_alert":  recurring_alert,
            }) + "\n\n"

        resp = StreamingHttpResponse(stream_generator(), content_type="text/event-stream")
        resp["Cache-Control"]     = "no-cache"
        resp["X-Accel-Buffering"] = "no"
        return resp

    except Exception as e:
        logger.exception(f"fish_disease_chat_stream error: {e}")
        def _err():
            yield "data: " + json.dumps({"error": str(e)}) + "\n\n"
        return StreamingHttpResponse(_err(), content_type="text/event-stream")


# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
# DISEASE LOG & STATS API ENDPOINTS
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

@login_required
def disease_log_api(request):
    """Return recent disease logs for the current user."""
    logs = DiseaseLog.objects.filter(user=request.user)[:50]
    data = [
        {
            "id":           log.id,
            "disease_name": log.disease_name,
            "species":      log.species,
            "severity":     log.severity,
            "detected_at":  log.detected_at.strftime("%Y-%m-%d %H:%M"),
        }
        for log in logs
    ]
    return JsonResponse({"logs": data, "success": True})


@login_required
def disease_stats_api(request):
    """Return disease statistics and recurring alerts for the current user."""
    thirty_days_ago = timezone.now() - timedelta(days=30)

    stats = list(
        DiseaseLog.objects
        .filter(user=request.user, detected_at__gte=thirty_days_ago)
        .values("disease_name", "severity")
        .annotate(count=Count("id"))
        .order_by("-count")[:15]
    )

    alerts = list(
        DiseaseAlert.objects
        .filter(user=request.user, resolved=False, occurrence_count__gte=3)
        .values("disease_name", "occurrence_count")
    )

    return JsonResponse({
        "stats":   stats,
        "alerts":  alerts,
        "success": True,
    })


@login_required
@require_http_methods(["POST"])
def resolve_disease_alert(request, pk):
    """Mark a DiseaseAlert as resolved."""
    alert = get_object_or_404(DiseaseAlert, pk=pk, user=request.user)
    alert.resolved = True
    alert.save(update_fields=["resolved"])
    return JsonResponse({"success": True, "message": "Alert resolved."})