from rest_framework import serializers

from .models import FishBatch, GrowthRecord, Pond, WeatherRecord, FeedLog


class PondSerializer(serializers.ModelSerializer):
    class Meta:
        model = Pond
        fields = ["id", "name", "area_m2", "max_depth_m", "created_at"]


class FishBatchSerializer(serializers.ModelSerializer):
    pond_name = serializers.CharField(source="pond.name", read_only=True)
    latest_biomass_kg = serializers.FloatField(read_only=True)

    class Meta:
        model = FishBatch
        fields = [
            "id",
            "pond",
            "pond_name",
            "species",
            "stocking_date",
            "initial_count",
            "initial_avg_weight_g",
            "target_harvest_date",
            "latest_biomass_kg",
            "notes",
        ]


class GrowthRecordSerializer(serializers.ModelSerializer):
    class Meta:
        model = GrowthRecord
        fields = ["id", "batch", "date", "surviving_count", "avg_weight_g"]


class WeatherRecordSerializer(serializers.ModelSerializer):
    class Meta:
        model = WeatherRecord
        fields = [
            "id",
            "pond",
            "timestamp",
            "water_temp_c",
            "dissolved_oxygen_mg_l",
            "ph",
            "rainfall_mm",
        ]


class FeedLogSerializer(serializers.ModelSerializer):
    class Meta:
        model = FeedLog
        fields = ["id", "batch", "date", "feed_amount_kg", "auto_calculated"]

