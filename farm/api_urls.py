from django.urls import path

from . import api_views

app_name = "farm_api"

urlpatterns = [
    path("ponds/", api_views.PondListAPI.as_view(), name="pond-list"),
    path("batches/", api_views.FishBatchListAPI.as_view(), name="batch-list"),
    path("batches/<int:pk>/", api_views.FishBatchDetailAPI.as_view(), name="batch-detail"),
    path("batches/<int:pk>/prediction/", api_views.BatchPredictionAPI.as_view(), name="batch-prediction"),
    path("growth-records/", api_views.GrowthRecordListAPI.as_view(), name="growth-list"),
    path("weather-records/", api_views.WeatherRecordListAPI.as_view(), name="weather-list"),
    path("feed-logs/", api_views.FeedLogListAPI.as_view(), name="feed-log-list"),
]

