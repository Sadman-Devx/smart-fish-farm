from allauth.socialaccount.adapter import DefaultSocialAccountAdapter
from django.contrib.auth import get_user_model
import uuid

User = get_user_model()

class MySocialAccountAdapter(DefaultSocialAccountAdapter):
    def populate_user(self, request, sociallogin, data):
        user = super().populate_user(request, sociallogin, data)
        if not user.username:
            # Email থেকে username বানাও, না হলে UUID দাও
            email = data.get('email', '')
            base = email.split('@')[0] if email else 'user'
            username = base
            counter = 1
            while User.objects.filter(username=username).exists():
                username = f"{base}_{counter}"
                counter += 1
            user.username = username
        return user