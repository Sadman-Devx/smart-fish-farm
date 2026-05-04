import logging
from django.utils import timezone

logger = logging.getLogger(__name__)
SESSION_ACTIVITY_UPDATE_INTERVAL = 300  


class SessionActivityMiddleware:
    """
    Update UserSession.last_active periodically for authenticated users.

    FIX 1: Replaced bare `except Exception: pass` with logger.warning().
    FIX 2: Prevents hammering the database on every single request by
           checking a session timestamp and only updating every N seconds.
    FIX 3: Fixed docstring/code mismatch (was updating is_active, docstring said last_active).
    """

    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        response = self.get_response(request)

        if request.user.is_authenticated and request.session.session_key:
            try:
                last_check = request.session.get('_session_activity_last_checked')
                now = timezone.now().timestamp()

                if not last_check or (now - last_check) > SESSION_ACTIVITY_UPDATE_INTERVAL:
                    from .models import UserSession
                    
                    UserSession.objects.update_or_create(
                        session_key=request.session.session_key,
                        defaults={
                            "is_active": True,
                            "user": request.user,
                            "last_active": timezone.now(),  
                        },
                    )
                    
                    request.session['_session_activity_last_checked'] = now

            except Exception as exc:
                logger.warning(
                    "SessionActivityMiddleware: failed to update UserSession "
                    "for user %s — %s: %s",
                    request.user.pk,
                    type(exc).__name__,
                    exc,
                )

        return response