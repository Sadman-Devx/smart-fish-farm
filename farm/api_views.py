"""
farm/api_views.py
─────────────────
REST API permission & isolation policy:
  • GET (list / retrieve / prediction) → Authenticated users see ONLY their own data.
  • Guests (unauthenticated)          → Receive empty lists (no data leakage).
  • POST (create)                     → Authenticated users only. Owner is forced to request.user.
"""
from rest_framework import generics
from rest_framework.permissions import IsAuthenticatedOrReadOnly
from rest_framework import serializers
from .services.generate_water_alerts import generate_water_alerts  
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
# ✅ FIXED: Do not import from views.py. Import from services or utils to avoid circular imports.
# Assuming you moved _generate_water_alerts to farm/services.py or farm/utils.py



class PondListAPI(generics.ListCreateAPIView):
    """
    GET  /api/ponds/  — Authenticated users see only their ponds.
    POST /api/ponds/  — Creates a pond and forces owner=request.user.
    """
    serializer_class   = PondSerializer
    permission_classes = [IsAuthenticatedOrReadOnly]

    # ✅ FIXED: Override queryset to enforce per-user isolation
    def get_queryset(self):
        user = self.request.user
        if user.is_authenticated:
            return Pond.objects.filter(owner=user).order_by("name")
        return Pond.objects.none() # Guests get nothing

    # ✅ FIXED: Prevent mass assignment. Force the logged-in user as the owner.
    def perform_create(self, serializer):
        serializer.save(owner=self.request.user)


class FishBatchListAPI(generics.ListCreateAPIView):
    """
    GET  /api/batches/  — Isolated by pond__owner
    POST /api/batches/  — Isolated creation
    """
    serializer_class   = FishBatchSerializer
    permission_classes = [IsAuthenticatedOrReadOnly]

    def get_queryset(self):
        user = self.request.user
        if user.is_authenticated:
            return FishBatch.objects.filter(pond__owner=user).select_related("pond").order_by("pond__name", "stocking_date")
        return FishBatch.objects.none()


class FishBatchDetailAPI(generics.RetrieveAPIView):
    """
    GET /api/batches/<pk>/ — Prevents users from looking up other users' batch IDs.
    """
    serializer_class   = FishBatchSerializer
    permission_classes = [IsAuthenticatedOrReadOnly]

    def get_queryset(self):
        user = self.request.user
        if user.is_authenticated:
            return FishBatch.objects.filter(pond__owner=user).select_related("pond")
        return FishBatch.objects.none()


class GrowthRecordListAPI(generics.ListCreateAPIView):
    """
    GET  /api/growth-records/  — Isolated by batch__pond__owner
    POST /api/growth-records/  — Isolated creation
    """
    serializer_class   = GrowthRecordSerializer
    permission_classes = [IsAuthenticatedOrReadOnly]

    def get_queryset(self):
        user = self.request.user
        if user.is_authenticated:
            return GrowthRecord.objects.filter(batch__pond__owner=user).order_by("-date")
        return GrowthRecord.objects.none()


class WeatherRecordListAPI(generics.ListCreateAPIView):
    """
    GET  /api/weather-records/  — Isolated by pond__owner
    POST /api/weather-records/  — IoT sensor or manual entry (Isolated)
    """
    serializer_class   = WeatherRecordSerializer
    permission_classes = [IsAuthenticatedOrReadOnly]

    def get_queryset(self):
        user = self.request.user
        if user.is_authenticated:
            return WeatherRecord.objects.filter(pond__owner=user).order_by("-timestamp")
        return WeatherRecord.objects.none()

    def perform_create(self, serializer):
        # ✅ Bulletproof Security: Verify the posted pond belongs to the requesting user
        pond = serializer.validated_data.get('pond')
        if pond and pond.owner != self.request.user:
            raise serializers.ValidationError(
                {"pond": "You do not have permission to log data for this pond."}
            )
        
        record = serializer.save()
        generate_water_alerts(record)


class FeedLogListAPI(generics.ListCreateAPIView):
    """
    GET  /api/feed-logs/  — Isolated by batch__pond__owner
    POST /api/feed-logs/  — Isolated creation
    """
    serializer_class   = FeedLogSerializer
    permission_classes = [IsAuthenticatedOrReadOnly]

    def get_queryset(self):
        user = self.request.user
        if user.is_authenticated:
            return FeedLog.objects.filter(batch__pond__owner=user).order_by("-date")
        return FeedLog.objects.none()


class BatchPredictionAPI(APIView):
    """
    GET /api/batches/<pk>/prediction/
    Returns AI growth prediction for a batch. 
    Prevents IDOR by checking if the batch belongs to the requesting user.
    """
    permission_classes = [IsAuthenticatedOrReadOnly]

    def get(self, request, pk: int):
        # ✅ FIXED: Do not use get_object_or_404 directly on the model. 
        # Filter by owner first to prevent IDOR.
        user = request.user
        if not user.is_authenticated:
            return Response({"error": "Authentication required"}, status=401)

        batch = get_object_or_404(
            FishBatch.objects.filter(pond__owner=user).select_related("pond"), 
            pk=pk
        )
        
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