from django.contrib.auth.backends import ModelBackend
from django.contrib.auth import get_user_model
from django.contrib.auth.hashers import make_password

User = get_user_model()


class EmailBackend(ModelBackend):
    """
    Custom authentication backend that allows users to log in with their
    email address and password instead of the default username + password.
    """
    def authenticate(self, request, username=None, password=None, **kwargs):
        # Normalize password to a string (even if None is passed)
        if password is None:
            password = ''

        # Email can be supplied as the 'email' kwarg or fall back to 'username'
        email = kwargs.get('email', username)
        if email is None:
            email = ''
        email = email.strip()

        # If no email is provided, perform a dummy hash to mitigate timing attacks
        if not email:
            make_password(password)
            return None

        try:
            user = User.objects.get(email__iexact=email)
        except User.DoesNotExist:
            make_password(password)
            return None
        except User.MultipleObjectsReturned:
            # Treat duplicate emails as non‑existent to avoid information leakage
            make_password(password)
            return None

        # Use the parent class method to check is_active etc.
        if user.check_password(password) and self.user_can_authenticate(user):
            return user
        return None