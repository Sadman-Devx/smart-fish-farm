import logging

logger = logging.getLogger(__name__)


class SessionActivityMiddleware:
    """
    Update UserSession.last_active on every authenticated request.

    FIX: the original bare `except Exception: pass` hid real bugs
    (e.g. DB errors, import errors). Now we log at WARNING level so
    problems appear in the server log without crashing the request.
    """

    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        response = self.get_response(request)

        if request.user.is_authenticated and request.session.session_key:
            try:
                from .models import UserSession
                UserSession.objects.update_or_create(
                    session_key=request.session.session_key,
                    defaults={
                        "is_active": True,
                        "user": request.user,
                    },
                )
            except Exception as exc:           # still non-fatal …
                logger.warning(                # … but now visible in logs
                    "SessionActivityMiddleware: failed to update UserSession "
                    "for user %s — %s: %s",
                    request.user.pk,
                    type(exc).__name__,
                    exc,
                )

        return response