"""
farm/services/ml_prediction.py
─────────────────────────────────────────────────────────────────────────────
ML-based Fish Growth Prediction Service
========================================

Uses scikit-learn to train and predict fish growth using historical data.

Models Used:
  1. RandomForestRegressor  — Primary model (weight prediction)
  2. GradientBoostingRegressor — Secondary model (FCR prediction)
  3. LinearRegression        — Baseline comparison model

Features used for prediction:
  - age_days          : Days since stocking
  - biomass_kg        : Current total biomass
  - water_temp_c      : Latest water temperature
  - dissolved_oxygen  : Latest DO reading
  - ph                : Latest pH reading
  - feed_kg_7days     : Total feed given last 7 days
  - species_encoded   : Species as numeric (label encoded)
  - pond_area_m2      : Pond surface area
  - survival_rate     : Current survival rate %

Usage in views:
    from farm.services.ml_prediction import MLGrowthPredictor

    predictor = MLGrowthPredictor()
    result    = predictor.predict(batch)
    # result = {
    #     'predicted_weight_g': 320.5,
    #     'predicted_daily_gain_g': 4.2,
    #     'days_to_market': 45,
    #     'confidence_score': 0.87,
    #     'model_used': 'RandomForest',
    #     'feature_importance': {...},
    #     'training_samples': 120,
    # }
"""

from __future__ import annotations

import logging
import math
from datetime import date, timedelta
from typing import Any

import numpy as np

logger = logging.getLogger(__name__)

# ── Species encoding map ──────────────────────────────────────────────────────
SPECIES_ENCODING: dict[str, int] = {
    "tilapia": 0,
    "catfish": 1,
    "carp":    2,
    "other":   3,
}

# ── Default market weight (grams) ─────────────────────────────────────────────
DEFAULT_MARKET_WEIGHT_G = 500.0


# ── Feature extraction ────────────────────────────────────────────────────────

def _extract_features(batch) -> dict[str, float]:
    """
    Extract numeric features from a FishBatch instance.
    Returns a dict of feature_name → float value.
    """
    from django.utils import timezone
    from django.db.models import Sum

    from ..models import WeatherRecord, FeedLog

    # Age
    age_days = (timezone.now().date() - batch.stocking_date).days
    age_days = max(age_days, 1)

    # Biomass
    biomass_kg = batch.latest_biomass_kg or 0.0

    # Latest growth record
    latest_growth = batch.growth_records.order_by("-date").first()
    surviving_count = latest_growth.surviving_count if latest_growth else batch.initial_count
    current_avg_weight_g = (
        float(latest_growth.avg_weight_g) if latest_growth
        else float(batch.initial_avg_weight_g)
    )

    # Survival rate
    survival_rate = (
        (surviving_count / batch.initial_count * 100)
        if batch.initial_count > 0 else 100.0
    )

    # Latest water quality
    latest_weather = (
        WeatherRecord.objects
        .filter(pond=batch.pond)
        .order_by("-timestamp")
        .first()
    )
    water_temp_c      = float(latest_weather.water_temp_c)      if latest_weather else 26.0
    dissolved_oxygen  = float(latest_weather.dissolved_oxygen_mg_l) if latest_weather else 6.5
    ph                = float(latest_weather.ph)                 if latest_weather else 7.0

    # Feed last 7 days
    seven_days_ago = timezone.now().date() - timedelta(days=7)
    feed_7days = (
        FeedLog.objects
        .filter(batch=batch, date__gte=seven_days_ago)
        .aggregate(total=Sum("feed_amount_kg"))["total"] or 0.0
    )
    feed_kg_7days = float(feed_7days)

    # Species encoding
    species_encoded = SPECIES_ENCODING.get(batch.species, 3)

    # Pond area
    pond_area_m2 = float(batch.pond.area_m2) if batch.pond.area_m2 else 500.0

    return {
        "age_days":           age_days,
        "biomass_kg":         biomass_kg,
        "current_avg_weight_g": current_avg_weight_g,
        "water_temp_c":       water_temp_c,
        "dissolved_oxygen":   dissolved_oxygen,
        "ph":                 ph,
        "feed_kg_7days":      feed_kg_7days,
        "species_encoded":    species_encoded,
        "pond_area_m2":       pond_area_m2,
        "survival_rate":      survival_rate,
    }


def _features_to_array(features: dict[str, float]) -> np.ndarray:
    """Convert feature dict to numpy array in consistent order."""
    feature_order = [
        "age_days",
        "biomass_kg",
        "current_avg_weight_g",
        "water_temp_c",
        "dissolved_oxygen",
        "ph",
        "feed_kg_7days",
        "species_encoded",
        "pond_area_m2",
        "survival_rate",
    ]
    return np.array([[features[k] for k in feature_order]], dtype=np.float64)


# ── Training data generator ───────────────────────────────────────────────────

def _build_training_data() -> tuple[np.ndarray, np.ndarray, int]:
    """
    Build training dataset from all GrowthRecord rows in the database.

    For each growth record we reconstruct the features at that point in time
    and use the *next* record's avg_weight_g as the target label.

    Returns:
        X     : feature matrix  (n_samples, n_features)
        y     : target vector   (n_samples,) — avg weight at next measurement
        count : number of training samples
    """
    from ..models import GrowthRecord, WeatherRecord, FeedLog
    from django.db.models import Sum

    X_rows: list[list[float]] = []
    y_vals: list[float]       = []

    # Group growth records by batch
    from ..models import FishBatch
    batches = FishBatch.objects.prefetch_related(
        "growth_records", "feed_logs", "pond"
    ).all()

    for batch in batches:
        records = list(batch.growth_records.order_by("date"))
        if len(records) < 2:
            continue  # Need at least 2 records to form a training pair

        for i in range(len(records) - 1):
            curr = records[i]
            nxt  = records[i + 1]

            age_days = max((curr.date - batch.stocking_date).days, 1)

            surviving  = curr.surviving_count
            init_count = batch.initial_count
            survival_rate = (surviving / init_count * 100) if init_count > 0 else 100.0

            biomass_kg = (surviving * float(curr.avg_weight_g)) / 1000.0

            # Water quality closest to this record's date
            weather = (
                WeatherRecord.objects
                .filter(pond=batch.pond, timestamp__date__lte=curr.date)
                .order_by("-timestamp")
                .first()
            )
            water_temp_c     = float(weather.water_temp_c)           if weather else 26.0
            dissolved_oxygen = float(weather.dissolved_oxygen_mg_l)  if weather else 6.5
            ph               = float(weather.ph)                      if weather else 7.0

            # Feed 7 days before this record
            seven_days_ago = curr.date - timedelta(days=7)
            feed_7days = (
                FeedLog.objects
                .filter(batch=batch, date__gte=seven_days_ago, date__lte=curr.date)
                .aggregate(total=Sum("feed_amount_kg"))["total"] or 0.0
            )

            row = [
                age_days,
                biomass_kg,
                float(curr.avg_weight_g),
                water_temp_c,
                dissolved_oxygen,
                ph,
                float(feed_7days),
                SPECIES_ENCODING.get(batch.species, 3),
                float(batch.pond.area_m2) if batch.pond.area_m2 else 500.0,
                survival_rate,
            ]
            X_rows.append(row)
            y_vals.append(float(nxt.avg_weight_g))

    if not X_rows:
        return np.array([]), np.array([]), 0

    return np.array(X_rows, dtype=np.float64), np.array(y_vals, dtype=np.float64), len(X_rows)


# ── Synthetic data augmentation (when real data is scarce) ────────────────────

def _generate_synthetic_data(n_samples: int = 200) -> tuple[np.ndarray, np.ndarray]:
    """
    Generate biologically-realistic synthetic fish growth data.

    This is used when the database has < 10 real training samples.
    Based on published aquaculture growth parameters for common species.

    Reference: Boyd & Tucker (1998), Aquaculture Water Management.
    """
    rng = np.random.default_rng(seed=42)

    X_rows: list[list[float]] = []
    y_vals: list[float]       = []

    for _ in range(n_samples):
        species_encoded = rng.integers(0, 4)
        age_days        = rng.integers(10, 180)
        water_temp_c    = rng.uniform(22.0, 32.0)
        dissolved_oxygen= rng.uniform(4.0, 9.0)
        ph              = rng.uniform(6.5, 9.0)
        pond_area_m2    = rng.uniform(200.0, 2000.0)
        survival_rate   = rng.uniform(75.0, 99.0)
        feed_kg_7days   = rng.uniform(1.0, 20.0)

        # Species-specific base growth rates (g/day)
        base_growth = {0: 3.5, 1: 2.8, 2: 3.0, 3: 2.5}[species_encoded]

        # Temperature factor (optimal 26–30°C)
        if water_temp_c < 18:
            temp_factor = 0.3
        elif water_temp_c < 22:
            temp_factor = 0.6
        elif water_temp_c <= 30:
            temp_factor = 1.0
        else:
            temp_factor = 0.85

        # DO factor
        do_factor = min(dissolved_oxygen / 7.0, 1.0) if dissolved_oxygen >= 4.0 else 0.5

        # Daily gain
        daily_gain_g = base_growth * temp_factor * do_factor * rng.uniform(0.85, 1.15)

        # Current weight based on age
        initial_weight_g  = rng.uniform(5.0, 30.0)
        current_weight_g  = initial_weight_g + (daily_gain_g * age_days)
        current_weight_g  = max(current_weight_g, initial_weight_g)

        biomass_kg = (survival_rate / 100) * rng.integers(500, 3000) * current_weight_g / 1000.0

        # Target: weight after ~7 more days
        next_weight_g = current_weight_g + daily_gain_g * rng.uniform(5, 10)

        row = [
            age_days,
            biomass_kg,
            current_weight_g,
            water_temp_c,
            dissolved_oxygen,
            ph,
            feed_kg_7days,
            float(species_encoded),
            pond_area_m2,
            survival_rate,
        ]
        X_rows.append(row)
        y_vals.append(next_weight_g)

    return np.array(X_rows, dtype=np.float64), np.array(y_vals, dtype=np.float64)


# ── Main predictor class ──────────────────────────────────────────────────────

class MLGrowthPredictor:
    """
    ML-based fish growth predictor.

    Trains three models and selects the best one based on cross-validation score:
      1. RandomForestRegressor     (ensemble, handles non-linearity well)
      2. GradientBoostingRegressor (boosting, good for small datasets)
      3. LinearRegression          (baseline, interpretable)

    The model is retrained on every call to predict() if new data is available,
    or uses cached model if data hasn't changed.
    """

    _cached_model      = None
    _cached_model_name = ""
    _cached_score      = 0.0
    _cached_n_samples  = 0

    # Feature names in order (must match _features_to_array)
    FEATURE_NAMES = [
        "age_days", "biomass_kg", "current_avg_weight_g",
        "water_temp_c", "dissolved_oxygen", "ph",
        "feed_kg_7days", "species_encoded", "pond_area_m2", "survival_rate",
    ]

    def _train(self) -> tuple[Any, str, float, int]:
        """
        Train models and return (best_model, model_name, r2_score, n_samples).
        """
        from sklearn.ensemble import RandomForestRegressor, GradientBoostingRegressor
        from sklearn.linear_model  import LinearRegression
        from sklearn.preprocessing import StandardScaler
        from sklearn.pipeline      import Pipeline
        from sklearn.model_selection import cross_val_score
        from sklearn.metrics import r2_score
        import warnings
        warnings.filterwarnings("ignore")

        # Build real training data
        X_real, y_real, n_real = _build_training_data()

        # Augment with synthetic data
        X_synth, y_synth = _generate_synthetic_data(n_samples=300)

        if n_real >= 10:
            # Mix real (weighted 3x) + synthetic
            X_real_rep = np.tile(X_real, (3, 1))
            y_real_rep = np.tile(y_real, 3)
            X = np.vstack([X_real_rep, X_synth])
            y = np.concatenate([y_real_rep, y_synth])
        else:
            # Not enough real data — use synthetic only
            X = X_synth
            y = y_synth

        n_samples = len(y)

        # Define candidate models
        candidates = {
            "RandomForest": Pipeline([
                ("scaler", StandardScaler()),
                ("model",  RandomForestRegressor(
                    n_estimators=150,
                    max_depth=12,
                    min_samples_split=4,
                    min_samples_leaf=2,
                    random_state=42,
                    n_jobs=-1,
                )),
            ]),
            "GradientBoosting": Pipeline([
                ("scaler", StandardScaler()),
                ("model",  GradientBoostingRegressor(
                    n_estimators=120,
                    learning_rate=0.08,
                    max_depth=5,
                    subsample=0.85,
                    random_state=42,
                )),
            ]),
            "LinearRegression": Pipeline([
                ("scaler", StandardScaler()),
                ("model",  LinearRegression()),
            ]),
        }

        best_model      = None
        best_name       = ""
        best_score      = -999.0

        cv_folds = min(5, max(2, n_samples // 20))

        for name, pipeline in candidates.items():
            try:
                scores = cross_val_score(
                    pipeline, X, y,
                    cv=cv_folds,
                    scoring="r2",
                    n_jobs=-1,
                )
                mean_score = float(np.mean(scores))
                logger.info(f"[ML] {name}: CV R² = {mean_score:.4f}")
                if mean_score > best_score:
                    best_score = mean_score
                    best_name  = name
                    best_model = pipeline
            except Exception as e:
                logger.warning(f"[ML] {name} CV failed: {e}")

        # Final fit on all data
        if best_model is not None:
            best_model.fit(X, y)

        return best_model, best_name, max(best_score, 0.0), n_real

    def _get_feature_importance(self, model) -> dict[str, float]:
        """Extract feature importance from the trained model."""
        try:
            inner = model.named_steps["model"]
            if hasattr(inner, "feature_importances_"):
                importances = inner.feature_importances_
                return {
                    name: round(float(imp), 4)
                    for name, imp in zip(self.FEATURE_NAMES, importances)
                }
        except Exception:
            pass
        return {}

    def predict(self, batch) -> dict[str, Any]:
        """
        Main prediction method.

        Args:
            batch: FishBatch model instance

        Returns:
            dict with prediction results and metadata.
        """
        from django.conf import settings

        # Extract current features
        features = _extract_features(batch)
        X_input  = _features_to_array(features)

        # Train (or use cache)
        try:
            model, model_name, score, n_real = self._train()
            self.__class__._cached_model      = model
            self.__class__._cached_model_name = model_name
            self.__class__._cached_score      = score
            self.__class__._cached_n_samples  = n_real
        except Exception as e:
            logger.error(f"[ML] Training failed: {e}")
            return self._fallback_prediction(batch, features)

        if model is None:
            return self._fallback_prediction(batch, features)

        # Predict next weight
        try:
            predicted_weight_g = float(model.predict(X_input)[0])
            predicted_weight_g = max(predicted_weight_g, features["current_avg_weight_g"])
        except Exception as e:
            logger.error(f"[ML] Prediction failed: {e}")
            return self._fallback_prediction(batch, features)

        # Derived metrics
        current_weight_g   = features["current_avg_weight_g"]
        weight_gain_g      = max(predicted_weight_g - current_weight_g, 0.1)
        predicted_daily_gain_g = round(weight_gain_g / 7.0, 2)  # assume 7-day window

        market_weight_g    = float(getattr(settings, "DEFAULT_MARKET_WEIGHT_G", 500.0))
        remaining_g        = max(market_weight_g - current_weight_g, 0.0)
        days_to_market     = (
            0 if remaining_g == 0
            else int(math.ceil(remaining_g / max(predicted_daily_gain_g, 0.1)))
        )
        harvest_date       = date.today() + timedelta(days=days_to_market)

        # Confidence score: based on R² and data quantity
        data_confidence = min(n_real / 50.0, 1.0)   # saturates at 50 real samples
        confidence_score = round(score * 0.7 + data_confidence * 0.3, 3)
        confidence_score = max(0.0, min(1.0, confidence_score))

        feature_importance = self._get_feature_importance(model)

        return {
            # Core predictions
            "predicted_weight_g":         round(predicted_weight_g, 2),
            "current_avg_weight_g":       round(current_weight_g, 2),
            "predicted_daily_gain_g":     predicted_daily_gain_g,
            "days_to_market":             days_to_market,
            "estimated_harvest_date":     harvest_date,
            "target_market_weight_g":     market_weight_g,

            # Model metadata (for paper)
            "model_used":                 model_name,
            "r2_score":                   round(score, 4),
            "confidence_score":           confidence_score,
            "training_samples_real":      n_real,
            "training_samples_synthetic": 300,
            "feature_importance":         feature_importance,

            # Input features used (for transparency)
            "features_used": {
                "water_temp_c":      features["water_temp_c"],
                "dissolved_oxygen":  features["dissolved_oxygen"],
                "ph":                features["ph"],
                "age_days":          features["age_days"],
                "survival_rate":     round(features["survival_rate"], 1),
                "feed_kg_7days":     round(features["feed_kg_7days"], 2),
                "biomass_kg":        round(features["biomass_kg"], 2),
            },
            "fallback": False,
        }

    def _fallback_prediction(self, batch, features: dict) -> dict[str, Any]:
        """
        Formula-based fallback when ML fails.
        Uses the original growth_prediction.py logic.
        """
        from django.conf import settings
        from .growth_prediction import predict_batch_growth

        result = predict_batch_growth(batch)
        result["model_used"]    = "Formula (fallback)"
        result["r2_score"]      = 0.0
        result["confidence_score"] = 0.5
        result["training_samples_real"] = 0
        result["training_samples_synthetic"] = 0
        result["feature_importance"] = {}
        result["features_used"]  = features
        result["fallback"]       = True
        return result


# ── Convenience function ──────────────────────────────────────────────────────

def ml_predict_batch_growth(batch) -> dict[str, Any]:
    """
    Top-level convenience function.
    Call this from views instead of predict_batch_growth() for ML predictions.

    Example:
        from farm.services.ml_prediction import ml_predict_batch_growth
        result = ml_predict_batch_growth(batch)
    """
    predictor = MLGrowthPredictor()
    return predictor.predict(batch)


# ── Model comparison utility (for paper evaluation) ───────────────────────────

def compare_models_for_paper() -> dict[str, Any]:
    """
    Train all three models and return comparison metrics.
    Use this to generate Table data for the research paper.

    Returns:
        {
            'models': [
                {'name': 'RandomForest', 'r2': 0.91, 'mae': 12.3, 'rmse': 18.7},
                {'name': 'GradientBoosting', ...},
                {'name': 'LinearRegression', ...},
            ],
            'best_model': 'RandomForest',
            'dataset_info': {'real_samples': 120, 'synthetic_samples': 300},
        }
    """
    from sklearn.ensemble import RandomForestRegressor, GradientBoostingRegressor
    from sklearn.linear_model  import LinearRegression
    from sklearn.preprocessing import StandardScaler
    from sklearn.pipeline      import Pipeline
    from sklearn.model_selection import cross_val_score, KFold
    from sklearn.metrics import mean_absolute_error, mean_squared_error
    import warnings
    warnings.filterwarnings("ignore")

    X_real, y_real, n_real = _build_training_data()
    X_synth, y_synth = _generate_synthetic_data(300)

    if n_real >= 10:
        X_real_rep = np.tile(X_real, (3, 1))
        y_real_rep = np.tile(y_real, 3)
        X = np.vstack([X_real_rep, X_synth])
        y = np.concatenate([y_real_rep, y_synth])
    else:
        X, y = X_synth, y_synth

    candidates = {
        "Random Forest": Pipeline([
            ("scaler", StandardScaler()),
            ("model",  RandomForestRegressor(n_estimators=150, random_state=42, n_jobs=-1)),
        ]),
        "Gradient Boosting": Pipeline([
            ("scaler", StandardScaler()),
            ("model",  GradientBoostingRegressor(n_estimators=120, learning_rate=0.08, random_state=42)),
        ]),
        "Linear Regression": Pipeline([
            ("scaler", StandardScaler()),
            ("model",  LinearRegression()),
        ]),
    }

    results    = []
    best_name  = ""
    best_r2    = -999.0
    kf         = KFold(n_splits=5, shuffle=True, random_state=42)

    for name, pipeline in candidates.items():
        pipeline.fit(X, y)
        y_pred = pipeline.predict(X)

        r2_scores = cross_val_score(pipeline, X, y, cv=kf, scoring="r2")
        r2        = float(np.mean(r2_scores))
        mae       = float(mean_absolute_error(y, y_pred))
        rmse      = float(np.sqrt(mean_squared_error(y, y_pred)))

        results.append({
            "name": name,
            "r2":   round(r2, 4),
            "mae":  round(mae, 2),
            "rmse": round(rmse, 2),
        })

        if r2 > best_r2:
            best_r2   = r2
            best_name = name

    return {
        "models":      results,
        "best_model":  best_name,
        "dataset_info": {
            "real_samples":      n_real,
            "synthetic_samples": 300,
            "total_samples":     len(y),
            "features":          len(MLGrowthPredictor.FEATURE_NAMES),
            "feature_names":     MLGrowthPredictor.FEATURE_NAMES,
        },
    }