"""
farm/urls.py
─────────────────────────────────────────────────────────────────────────────
Full URL config for the farm app — includes onboarding, core, AI, analytics,
benchmarking, and PWA routes.
"""
from django.conf import settings
from django.urls import path
from django.views.static import serve

from . import views, onboarding_views, ai_agent_views
from .views import offline_view, manifest_view

app_name = "farm"

urlpatterns = [
    # ── Onboarding Wizard ──────────────────────────────────────────────────────
    path("onboarding/step1/",   onboarding_views.onboarding_step1, name="onboarding_step1"),
    path("onboarding/step2/",   onboarding_views.onboarding_step2, name="onboarding_step2"),
    path("onboarding/step3/",   onboarding_views.onboarding_step3, name="onboarding_step3"),
    path("onboarding/step4/",   onboarding_views.onboarding_step4, name="onboarding_step4"),
    path("onboarding/skip/",    onboarding_views.onboarding_skip,  name="onboarding_skip"),
    path("onboarding/upazilas/",onboarding_views.upazila_options,  name="upazila_options"),

    # ── Core Dashboard ─────────────────────────────────────────────────────────
    path("",                           views.dashboard,        name="dashboard"),
    path("alerts/test/",               views.send_test_alert,  name="send_test_alert"),

    # ── Ponds & Batches ────────────────────────────────────────────────────────
    path("ponds/",                    views.pond_list,         name="pond_list"),
    path("ponds/add/",                views.pond_create,       name="pond_create"),
    path("ponds/<int:pk>/delete/",    views.pond_delete,       name="pond_delete"),
    path("ponds/<int:pk>/",           views.pond_detail,       name="pond_detail"),
    
    path("batches/add/",              views.batch_create,      name="batch_create"),
    path("batches/<int:pk>/",         views.batch_detail,      name="batch_detail"),
    path("batches/<int:pk>/edit/",    views.batch_update,      name="batch_update"),
    path("batches/<int:pk>/delete/",  views.batch_delete,      name="batch_delete"),

    # ── Logging (Data Entry) ────────────────────────────────────────────────────
    path("weather/add/",              views.weather_create,    name="weather_create"),
    path("growth/add/",               views.growth_create,     name="growth_create"),
    path("feed/add/",                 views.feed_log_create,   name="feed_log_create"),
    path("mortality/add/",            views.mortality_create,  name="mortality_create"),

    # ── Harvest & Expenses ─────────────────────────────────────────────────────
    path("harvests/",                 views.harvest_list,      name="harvest_list"),
    path("harvests/add/",             views.harvest_create,    name="harvest_create"),
    
    path("expenses/",                 views.expense_list,      name="expense_list"),
    path("expenses/add/",             views.expense_create,    name="expense_create"),

    # ── Alerts & Reminders ─────────────────────────────────────────────────────
    path("alerts/",                   views.alert_list,        name="alert_list"),
    path("alerts/<int:pk>/resolve/",  views.alert_resolve,     name="alert_resolve"),
    path("reminders/",                views.reminder_list,     name="reminder_list"),

    # ── Reports & Dashboard Actions ────────────────────────────────────────────
    path("reports/daily-feed/",       views.daily_feed_report, name="daily_feed_report"),
    path("reports/profit-loss/",      views.profit_loss_report, name="profit_loss_report"),
    path("reports/mortality/",        views.mortality_report,  name="mortality_report"),
    
    path("weather/refresh/",          views.refresh_weather_view, name="refresh_weather"),
    path("feeding/done/",             views.mark_feeding_done_view, name="mark_feeding_done"),

    # ── AI Fish Doctor ─────────────────────────────────────────────────────────
    path("fish-doctor/",                          ai_agent_views.fish_disease_agent,     name="fish_doctor"),
    path("fish-doctor/chat/",                     ai_agent_views.fish_disease_chat,      name="fish_doctor_chat"),
    path("fish-doctor/chat/stream/",              ai_agent_views.fish_disease_chat_stream, name="fish_doctor_chat_stream"),
    path("fish-doctor/stats/",                    ai_agent_views.disease_stats_api,      name="disease_stats"),
    path("fish-doctor/logs/",                     ai_agent_views.disease_log_api,        name="disease_logs"),
    path("fish-doctor/alerts/<int:pk>/resolve/",  ai_agent_views.resolve_disease_alert,  name="resolve_disease_alert"),

    # ── Benchmarking (Staff Only) ─────────────────────────────────────────────
    path("benchmark/",         views.benchmark_dashboard,   name="benchmark_dashboard"),
    path("benchmark/run/",     views.run_benchmark_view,    name="run_benchmark"),
    path("benchmark/export/",  views.benchmark_export_json, name="benchmark_export"),

    # ── Analytics Dashboard ────────────────────────────────────────────────────
    path("analytics/",              views.analytics_dashboard, name="analytics_dashboard"),
    path("analytics/fcr/<int:pk>/", views.fcr_batch_detail,    name="fcr_batch_detail"),

    # ── PWA (Progressive Web App) ────────────────────────────────────────────
    path("offline/",      offline_view,   name="pwa_offline"),
    path("manifest.json", manifest_view,  name="pwa_manifest"),
    
    # Note: In production, serve sw.js via your web server (Nginx/Apache) or collectstatic.
    path('sw.js', serve, {
        'path': 'sw.js',
        'document_root': settings.BASE_DIR,
    }, name='service_worker'),
]