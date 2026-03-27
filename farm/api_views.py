from rest_framework import generics
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
    queryset = Pond.objects.all().order_by("name")
    serializer_class = PondSerializer


class FishBatchListAPI(generics.ListCreateAPIView):
    queryset = FishBatch.objects.all().select_related("pond").order_by("pond__name", "stocking_date")
    serializer_class = FishBatchSerializer


class FishBatchDetailAPI(generics.RetrieveAPIView):
    queryset = FishBatch.objects.all().select_related("pond")
    serializer_class = FishBatchSerializer


class GrowthRecordListAPI(generics.ListCreateAPIView):
    queryset = GrowthRecord.objects.all().order_by("-date")
    serializer_class = GrowthRecordSerializer


class WeatherRecordListAPI(generics.ListCreateAPIView):
    queryset = WeatherRecord.objects.all().order_by("-timestamp")
    serializer_class = WeatherRecordSerializer


class FeedLogListAPI(generics.ListCreateAPIView):
    queryset = FeedLog.objects.all().order_by("-date")
    serializer_class = FeedLogSerializer


class BatchPredictionAPI(APIView):
    def get(self, request, pk: int):
        batch = get_object_or_404(FishBatch.objects.select_related("pond"), pk=pk)
        smart_feed_kg = smart_feed_kg_for_batch(batch)
        prediction = predict_batch_growth(batch, feed_kg=smart_feed_kg)
        return Response(
            {
                "batch_id": batch.id,
                "species": batch.get_species_display(),
                "pond": batch.pond.name,
                "smart_feed_kg": smart_feed_kg,
                "prediction": prediction,
            }
        )

