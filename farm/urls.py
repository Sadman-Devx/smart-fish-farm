from django.urls import path
from . import views

app_name = "farm"

urlpatterns = [
    # ── Core ──────────────────────────────────────────────────────────────────
    path("",                           views.dashboard,        name="dashboard"),
    path("alerts/test/",              views.send_test_alert,  name="send_test_alert"),

    # ── Ponds & Batches ────────────────────────────────────────────────────────
    path("ponds/",                    views.pond_list,         name="pond_list"),
    path("ponds/<int:pk>/",           views.pond_detail,       name="pond_detail"),
    path("batches/<int:pk>/",         views.batch_detail,      name="batch_detail"),

    # ── Logging ────────────────────────────────────────────────────────────────
    path("weather/add/",              views.weather_create,    name="weather_create"),
    path("growth/add/",               views.growth_create,     name="growth_create"),
    path("feed/add/",                 views.feed_log_create,   name="feed_log_create"),
    path("mortality/add/",            views.mortality_create,  name="mortality_create"),

    # ── Harvest ────────────────────────────────────────────────────────────────
    path("harvests/",                 views.harvest_list,      name="harvest_list"),
    path("harvests/add/",             views.harvest_create,    name="harvest_create"),

    # ── Expenses ───────────────────────────────────────────────────────────────
    path("expenses/",                 views.expense_list,      name="expense_list"),
    path("expenses/add/",             views.expense_create,    name="expense_create"),

    # ── Alerts ─────────────────────────────────────────────────────────────────
    path("alerts/",                   views.alert_list,        name="alert_list"),
    path("alerts/<int:pk>/resolve/",  views.alert_resolve,     name="alert_resolve"),

    # ── Reports ────────────────────────────────────────────────────────────────
    path("reminders/",                views.reminder_list,     name="reminder_list"),
    path("reports/daily-feed/",       views.daily_feed_report, name="daily_feed_report"),
    path("reports/profit-loss/",      views.profit_loss_report,name="profit_loss_report"),
]
