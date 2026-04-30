"""
Fish Doctor AI Agent — Google Gemini Version (FREE)
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
INTEGRATION STEPS:
  1. Get a free API key from Google AI Studio: https://aistudio.google.com/apikey
  2. pip install google-genai
  3. Add to .env: GOOGLE_API_KEY=your_key_here
  4. Add to settings.py: GOOGLE_API_KEY = env('GOOGLE_API_KEY', default='')
  5. Place this file next to manage.py and rename it to ai_agent_views.py
  6. Add routes to farm/urls.py (see below)
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
"""

import json
import logging
import base64

from django.conf import settings
from django.contrib.auth.decorators import login_required
from django.http import JsonResponse
from django.shortcuts import render
from django.views.decorators.http import require_http_methods

logger = logging.getLogger(__name__)

FISH_DOCTOR_SYSTEM_PROMPT = """You are "Fish Doctor" — a highly experienced and friendly fish disease expert AI.
You are part of the AquaSmart Fish Farm Management System.

Your expertise:
- Fish disease identification (from both images and text descriptions)
- Water quality problem analysis
- General fish farming advice (feeding, water management, pond care)
- Disease prevention and treatment
- General conversation — answering any fish farming related questions

You always respond in Bengali (Bangla).

If you receive a fish image or disease description, respond in this format:

🔍 **Disease Identification**
[Disease name — how likely it is]

🦠 **Cause**
[Why this disease occurred]

⚠️ **Symptoms**
[What is visible]

💊 **Treatment**
[Step-by-step actions to take]

🛡️ **Prevention**
[How to protect in the future]

⚡ **Immediate Action**
[Emergency steps to take right now]

For general questions, respond naturally — no need to follow the format.
Always be warm and helpful. You are the farmer's trusted friend."""


def get_gemini_client():
    """Create and return a Google Gemini client."""
    try:
        from google import genai
        client = genai.Client(api_key=settings.GOOGLE_API_KEY)
        return client
    except ImportError:
        raise RuntimeError("google-genai package not found. Run: pip install google-genai")


@login_required
def fish_disease_agent(request):
    return render(request, 'farm/ai_agent.html')


@login_required
@require_http_methods(["POST"])
def fish_disease_chat(request):
    """
    Chat API endpoint.
    JSON body:
    {
        "message": "user text",
        "image": "data:image/jpeg;base64,...",   (optional)
        "image_type": "image/jpeg",
        "history": [{"role": "user", "content": "..."}, ...]
    }
    """
    try:
        from google import genai
        from google.genai import types

        body = json.loads(request.body)
        user_message = body.get("message", "").strip()
        image_data_url = body.get("image", "")
        image_type = body.get("image_type", "image/jpeg")
        history = body.get("history", [])

        has_image = bool(image_data_url)

        if not user_message and not has_image:
            return JsonResponse({"error": "Please provide a message or an image."}, status=400)

        client = get_gemini_client()

        # ── Build conversation history for Gemini ──────────────────────────
        gemini_history = []
        for turn in history[-20:]:
            role = turn.get("role")
            text = turn.get("content", "")
            if role == "user":
                gemini_history.append(types.Content(role="user", parts=[types.Part(text=text)]))
            elif role == "assistant":
                gemini_history.append(types.Content(role="model", parts=[types.Part(text=text)]))

        # ── Build current user message parts ──────────────────────────────
        current_parts = []

        if has_image:
            raw_b64 = image_data_url
            if "," in raw_b64:
                raw_b64 = raw_b64.split(",", 1)[1]
            image_bytes = base64.b64decode(raw_b64)
            current_parts.append(types.Part(
                inline_data=types.Blob(mime_type=image_type, data=image_bytes)
            ))

        text_part = user_message if user_message else (
            "Please analyze this fish image — identify any disease, explain the cause, and suggest the steps to take."
        )
        current_parts.append(types.Part(text=text_part))

        gemini_history.append(types.Content(role="user", parts=current_parts))

        # ── Call Gemini API ────────────────────────────────────────────────
        response = client.models.generate_content(
            model="models/gemini-2.5-flash",     # free tier compatible
            contents=gemini_history,
            config=types.GenerateContentConfig(
                system_instruction=FISH_DOCTOR_SYSTEM_PROMPT,
                max_output_tokens=1500,
                temperature=0.7,
            ),
        )

        reply = response.text
        return JsonResponse({"reply": reply, "success": True})

    except Exception as e:
        logger.exception(f"fish_disease_chat error: {e}")
        error_msg = str(e)
        if "API_KEY" in error_msg.upper() or "authentication" in error_msg.lower():
            return JsonResponse({"error": "Google API Key is invalid. Please check your .env file."}, status=500)
        return JsonResponse({"error": f"Server error: {error_msg}"}, status=500)