from django.urls import path
from . import views

app_name = "accounts"

urlpatterns = [
    path("login/",                            views.login_view,          name="login"),
    path("login/otp/",                        views.verify_otp_view,     name="verify_otp"),
    path("login/otp/resend/",                 views.resend_otp_view,     name="resend_otp"),
    path("logout/",                           views.logout_view,         name="logout"),
    path("register/",                         views.register_view,       name="register"),  # ← add
    path("profile/",                          views.profile_view,        name="profile"),
    path("password/",                         views.change_password_view,name="change_password"),
    path("sessions/",                         views.sessions_view,       name="sessions"),
    path("sessions/<int:session_id>/revoke/", views.revoke_session_view, name="revoke_session"),
]