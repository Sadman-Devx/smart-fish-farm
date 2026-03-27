from django.urls import path

from . import views

app_name = "farm"

urlpatterns = [
    path("", views.dashboard, name="dashboard"),
    path("alerts/test/", views.send_test_alert, name="send_test_alert"),
    path("ponds/", views.pond_list, name="pond_list"),
    path("ponds/<int:pk>/", views.pond_detail, name="pond_detail"),
    path("batches/<int:pk>/", views.batch_detail, name="batch_detail"),
    path("weather/add/", views.weather_create, name="weather_create"),
    path("growth/add/", views.growth_create, name="growth_create"),
    path("feed/add/", views.feed_log_create, name="feed_log_create"),
    path("reminders/", views.reminder_list, name="reminder_list"),
    path("reports/daily-feed/", views.daily_feed_report, name="daily_feed_report"),
]

