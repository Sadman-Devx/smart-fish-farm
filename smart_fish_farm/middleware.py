"""
smart_fish_farm/middleware.py
─────────────────────────────
Guests can browse the site (read-only).
Write actions are protected by @login_required in views.py directly.

This middleware does nothing special — it just exists so the import
in settings.py doesn't break if someone added it previously.
Remove the entry from MIDDLEWARE if you prefer.
"""


class LoginRequiredMiddleware:
    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        return self.get_response(request)