from .security import deactivate_session


class SessionActivityMiddleware:
    """
    Update UserSession.last_active on every authenticated request.
    Marks sessions inactive when Django session expires.
    """
    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        response = self.get_response(request)

        if request.user.is_authenticated and request.session.session_key:
            try:
                from .models import UserSession
                UserSession.objects.filter(
                    session_key=request.session.session_key,
                    user=request.user,
                ).update_or_create(
                    session_key=request.session.session_key,
                    defaults={"is_active": True, "user": request.user},
                )
            except Exception:
                pass

        return response
