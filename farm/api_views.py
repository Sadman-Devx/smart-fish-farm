"""
farm/api_views.py
─────────────────
REST API permission policy:
  • GET  (list / retrieve / prediction) → open to anonymous (IsAuthenticatedOrReadOnly)
  • POST (create)                       → authenticated users only
"""
from rest_framework import generics
from rest_framework.permissions import IsAuthenticatedOrReadOnly
from django.shortcuts import get_object_or_404
from rest_framework.response import Response
from rest_framework.views import APIView

from .models import FishBatch, FeedLog, GrowthRecord, Pond, WeatherRecord
from .serializers import (
    FeedLogSerializer,
    FishBatchSerializer,
    GrowthRecordSerializer,
    PondSerializer,
    WeatherRecordSerializer,
)
from .services import predict_batch_growth, smart_feed_kg_for_batch


class PondListAPI(generics.ListCreateAPIView):
    """
    GET  /api/ponds/  — public (guests can list ponds)
    POST /api/ponds/  — authenticated users only
    """
    queryset           = Pond.objects.all().order_by("name")
    serializer_class   = PondSerializer
    permission_classes = [IsAuthenticatedOrReadOnly]


class FishBatchListAPI(generics.ListCreateAPIView):
    """
    GET  /api/batches/  — public
    POST /api/batches/  — authenticated only
    """
    queryset = (
        FishBatch.objects.all()
        .select_related("pond")
        .order_by("pond__name", "stocking_date")
    )
    serializer_class   = FishBatchSerializer
    permission_classes = [IsAuthenticatedOrReadOnly]


class FishBatchDetailAPI(generics.RetrieveAPIView):
    """GET /api/batches/<pk>/ — public."""
    queryset           = FishBatch.objects.all().select_related("pond")
    serializer_class   = FishBatchSerializer
    permission_classes = [IsAuthenticatedOrReadOnly]


class GrowthRecordListAPI(generics.ListCreateAPIView):
    """
    GET  /api/growth-records/  — public
    POST /api/growth-records/  — authenticated only
    """
    queryset           = GrowthRecord.objects.all().order_by("-date")
    serializer_class   = GrowthRecordSerializer
    permission_classes = [IsAuthenticatedOrReadOnly]


class WeatherRecordListAPI(generics.ListCreateAPIView):
    """
    GET  /api/weather-records/  — public
    POST /api/weather-records/  — authenticated only
    """
    queryset           = WeatherRecord.objects.all().order_by("-timestamp")
    serializer_class   = WeatherRecordSerializer
    permission_classes = [IsAuthenticatedOrReadOnly]


class FeedLogListAPI(generics.ListCreateAPIView):
    """
    GET  /api/feed-logs/  — public
    POST /api/feed-logs/  — authenticated only
    """
    queryset           = FeedLog.objects.all().order_by("-date")
    serializer_class   = FeedLogSerializer
    permission_classes = [IsAuthenticatedOrReadOnly]


class BatchPredictionAPI(APIView):
    """
    GET /api/batches/<pk>/prediction/
    Returns AI growth prediction for a batch. Public (read-only data).
    """
    permission_classes = [IsAuthenticatedOrReadOnly]

    def get(self, request, pk: int):
        batch         = get_object_or_404(FishBatch.objects.select_related("pond"), pk=pk)
        smart_feed_kg = smart_feed_kg_for_batch(batch)
        prediction    = predict_batch_growth(batch, feed_kg=smart_feed_kg)
        return Response(
            {
                "batch_id":      batch.id,
                "species":       batch.get_species_display(),
                "pond":          batch.pond.name,
                "smart_feed_kg": smart_feed_kg,
                "prediction":    prediction,
            }
        )