"""
farm/services/ml_prediction.py 
=========================================================
"""
from __future__ import annotations

import logging
import math
import threading
import time
from collections import defaultdict
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

DEFAULT_MARKET_WEIGHT_G = 500.0


# ── Safe converters ───────────────────────────────────────────────────────────

def _safe_float(value, default: float = 0.0) -> float:
    if value is None: return default
    try: return float(value)
    except (ValueError, TypeError): return default

def _safe_int(value, default: int = 0) -> int:
    if value is None: return default
    try: return int(value)
    except (ValueError, TypeError): return default


# ── Feature extraction (For single batch prediction) ─────────────────────────

def _extract_features(batch) -> dict[str, float]:
    """Extract numeric features from a FishBatch instance safely."""
    from django.utils import timezone
    from django.db.models import Sum
    from ..models import WeatherRecord, FeedLog

    # Age
    age_days = max((timezone.now().date() - batch.stocking_date).days, 1) if batch.stocking_date else 1

    # Biomass & Growth
    biomass_kg = _safe_float(batch.latest_biomass_kg, 0.0)
    latest_growth = batch.growth_records.order_by("-date").first()

    surviving_count = (
        latest_growth.surviving_count 
        if latest_growth and latest_growth.surviving_count is not None 
        else _safe_int(batch.initial_count, 1)
    )
    current_avg_weight_g = (
        _safe_float(latest_growth.avg_weight_g) 
        if latest_growth and latest_growth.avg_weight_g is not None 
        else _safe_float(batch.initial_avg_weight_g)
    )

    # Survival rate
    initial_count = _safe_int(batch.initial_count, 1)
    survival_rate = min(max((surviving_count / initial_count * 100) if initial_count > 0 else 100.0, 0.0), 100.0)

    # Water quality
    water_temp_c, dissolved_oxygen, ph = 26.0, 6.5, 7.0
    if batch.pond is not None:
        latest_weather = WeatherRecord.objects.filter(pond=batch.pond).order_by("-timestamp").first()
        if latest_weather:
            water_temp_c     = _safe_float(latest_weather.water_temp_c, 26.0)
            dissolved_oxygen = _safe_float(latest_weather.dissolved_oxygen_mg_l, 6.5)
            ph               = _safe_float(latest_weather.ph, 7.0)

    # Feed last 7 days
    seven_days_ago = timezone.now().date() - timedelta(days=7)
    feed_kg_7days = _safe_float(
        FeedLog.objects.filter(batch=batch, date__gte=seven_days_ago).aggregate(total=Sum("feed_amount_kg"))["total"]
    )

    # Species & Pond
    species_encoded = SPECIES_ENCODING.get(batch.species or "other", 3)
    pond_area_m2 = _safe_float(batch.pond.area_m2, 500.0) if batch.pond else 500.0

    return {
        "age_days": age_days, "biomass_kg": biomass_kg, "current_avg_weight_g": current_avg_weight_g,
        "water_temp_c": water_temp_c, "dissolved_oxygen": dissolved_oxygen, "ph": ph,
        "feed_kg_7days": feed_kg_7days, "species_encoded": species_encoded,
        "pond_area_m2": pond_area_m2, "survival_rate": survival_rate,
    }


def _features_to_array(features: dict[str, float]) -> np.ndarray:
    feature_order = [
        "age_days", "biomass_kg", "current_avg_weight_g", "water_temp_c",
        "dissolved_oxygen", "ph", "feed_kg_7days", "species_encoded",
        "pond_area_m2", "survival_rate",
    ]
    return np.array([[features[k] for k in feature_order]], dtype=np.float64)


# ── Training data generator (Optimized: O(1) DB Queries) ─────────────────────

def _build_training_data() -> tuple[np.ndarray, np.ndarray, int]:
    """
    Build training dataset. 
    ✅ FIX: Fetches ALL weather/feeds in 2 queries, then groups in memory.
    Prevents thousands of DB queries inside nested loops.
    """
    from ..models import GrowthRecord, WeatherRecord, FeedLog, FishBatch

    X_rows: list[list[float]] = []
    y_vals: list[float]       = []

    # ✅ FIX 1: Single bulk query for Weather, grouped by pond_id in memory
    all_weather = WeatherRecord.objects.select_related("pond").all()
    weather_by_pond = defaultdict(list)
    for w in all_weather:
        if w.pond_id:
            weather_by_pond[w.pond_id].append(w)

    # ✅ FIX 2: Single bulk query for FeedLogs, grouped by batch_id in memory
    all_feeds = FeedLog.objects.all()
    feed_by_batch = defaultdict(list)
    for f in all_feeds:
        if f.batch_id:
            feed_by_batch[f.batch_id].append(f)

    # Batch query with prefetched growth records
    batches = FishBatch.objects.select_related("pond").prefetch_related("growth_records").all()

    for batch in batches:
        if batch.pond is None or batch.stocking_date is None:
            continue

        records = list(batch.growth_records.order_by("date"))
        if len(records) < 2:
            continue

        init_count = _safe_int(batch.initial_count, 1)
        
        # Pre-sort weather for this pond descending (for fast lookup)
        pond_weather = sorted(
            weather_by_pond.get(batch.pond_id, []), 
            key=lambda w: w.timestamp, 
            reverse=True
        )
        batch_feeds = feed_by_batch.get(batch.id, [])

        for i in range(len(records) - 1):
            curr = records[i]
            nxt  = records[i + 1]

            surviving = _safe_int(curr.surviving_count, init_count)
            avg_weight_g = _safe_float(curr.avg_weight_g)
            nxt_weight_g = _safe_float(nxt.avg_weight_g)

            if avg_weight_g <= 0 or nxt_weight_g <= 0:
                continue

            age_days = max((curr.date - batch.stocking_date).days, 1)
            survival_rate = min(max((surviving / init_count * 100) if init_count > 0 else 100.0, 0.0), 100.0)
            biomass_kg = (surviving * avg_weight_g) / 1000.0

            # ✅ FIX 3: Find weather from memory instead of DB hit
            weather = next((w for w in pond_weather if w.timestamp.date() <= curr.date), None)
            water_temp_c     = _safe_float(weather.water_temp_c, 26.0) if weather else 26.0
            dissolved_oxygen = _safe_float(weather.dissolved_oxygen_mg_l, 6.5) if weather else 6.5
            ph               = _safe_float(weather.ph, 7.0) if weather else 7.0

            # ✅ FIX 4: Calculate feed from memory instead of DB hit
            seven_days_ago = curr.date - timedelta(days=7)
            feed_7days = sum(
                _safe_float(f.feed_amount_kg) 
                for f in batch_feeds 
                if seven_days_ago <= f.date <= curr.date
            )

            pond_area = _safe_float(batch.pond.area_m2, 500.0)
            species_enc = SPECIES_ENCODING.get(batch.species or "other", 3)

            row = [
                age_days, biomass_kg, avg_weight_g, water_temp_c,
                dissolved_oxygen, ph, feed_7days, species_enc, pond_area, survival_rate,
            ]
            X_rows.append(row)
            y_vals.append(nxt_weight_g)

    if not X_rows:
        return np.array([]), np.array([]), 0

    return np.array(X_rows, dtype=np.float64), np.array(y_vals, dtype=np.float64), len(X_rows)


# ── Synthetic data augmentation ───────────────────────────────────────────────

def _generate_synthetic_data(n_samples: int = 300) -> tuple[np.ndarray, np.ndarray]:
    """Generate biologically-realistic synthetic fish growth data."""
    rng = np.random.default_rng(seed=42)
    X_rows, y_vals = [], []

    for _ in range(n_samples):
        species_encoded = rng.integers(0, 4)
        age_days        = rng.integers(10, 180)
        water_temp_c    = rng.uniform(22.0, 32.0)
        dissolved_oxygen= rng.uniform(4.0, 9.0)
        ph              = rng.uniform(6.5, 9.0)
        pond_area_m2    = rng.uniform(200.0, 2000.0)
        survival_rate   = rng.uniform(75.0, 99.0)
        feed_kg_7days   = rng.uniform(1.0, 20.0)

        base_growth = {0: 3.5, 1: 2.8, 2: 3.0, 3: 2.5}[species_encoded]
        temp_factor = 0.3 if water_temp_c < 18 else (0.6 if water_temp_c < 22 else (1.0 if water_temp_c <= 30 else 0.85))
        do_factor = min(dissolved_oxygen / 7.0, 1.0) if dissolved_oxygen >= 4.0 else 0.5
        daily_gain_g = base_growth * temp_factor * do_factor * rng.uniform(0.85, 1.15)

        initial_weight_g = rng.uniform(5.0, 30.0)
        current_weight_g = max(initial_weight_g + (daily_gain_g * age_days), initial_weight_g)
        biomass_kg = (survival_rate / 100) * rng.integers(500, 3000) * current_weight_g / 1000.0
        next_weight_g = current_weight_g + daily_gain_g * rng.uniform(5, 10)

        X_rows.append([age_days, biomass_kg, current_weight_g, water_temp_c, dissolved_oxygen, ph, feed_kg_7days, float(species_encoded), pond_area_m2, survival_rate])
        y_vals.append(next_weight_g)

    return np.array(X_rows, dtype=np.float64), np.array(y_vals, dtype=np.float64)


# ── Main predictor class ──────────────────────────────────────────────────────

class MLGrowthPredictor:
    _cache_lock = threading.Lock()
    _cached_model      = None
    _cached_model_name = ""
    _cached_score      = 0.0
    _cached_n_samples  = 0
    _cache_expiry      = 0.0

    CACHE_TTL_SECONDS = 300  # 5 minutes

    FEATURE_NAMES = [
        "age_days", "biomass_kg", "current_avg_weight_g", "water_temp_c",
        "dissolved_oxygen", "ph", "feed_kg_7days", "species_encoded",
        "pond_area_m2", "survival_rate",
    ]

    def _train(self) -> tuple[Any, str, float, int]:
        """Train models and return the best one."""
        from sklearn.ensemble import RandomForestRegressor, GradientBoostingRegressor
        from sklearn.linear_model  import LinearRegression
        from sklearn.preprocessing import StandardScaler
        from sklearn.pipeline      import Pipeline
        from sklearn.model_selection import cross_validate
        import warnings
        warnings.filterwarnings("ignore")

        X_real, y_real, n_real = _build_training_data()
        X_synth, y_synth = _generate_synthetic_data(300)

        if n_real >= 10:
            X = np.vstack([np.tile(X_real, (3, 1)), X_synth])
            y = np.concatenate([np.tile(y_real, 3), y_synth])
        else:
            X, y = X_synth, y_synth

        candidates = {
            "RandomForest": Pipeline([("scaler", StandardScaler()), ("model", RandomForestRegressor(n_estimators=150, max_depth=12, min_samples_split=4, min_samples_leaf=2, random_state=42, n_jobs=-1))]),
            "GradientBoosting": Pipeline([("scaler", StandardScaler()), ("model", GradientBoostingRegressor(n_estimators=120, learning_rate=0.08, max_depth=5, subsample=0.85, random_state=42))]),
            "LinearRegression": Pipeline([("scaler", StandardScaler()), ("model", LinearRegression())]),
        }

        best_model, best_name, best_score, best_mae = None, "", -999.0, float("inf")
        cv_folds = min(5, max(2, len(y) // 20))

        for name, pipeline in candidates.items():
            try:
                scores = cross_validate(
                    pipeline, X, y, cv=cv_folds,
                    scoring=("r2", "neg_mean_absolute_error"), n_jobs=-1,
                )
                mean_r2 = float(np.mean(scores["test_r2"]))
                mean_mae = float(-np.mean(scores["test_neg_mean_absolute_error"]))
                # Select by lowest MAE (real-world prediction error in grams —
                # more decision-relevant than R2 alone, which can favor a model
                # with worse absolute error if its variance-explained happens
                # to be higher). R2 is still tracked and returned for reporting.
                if mean_mae < best_mae:
                    best_mae, best_score, best_name, best_model = mean_mae, mean_r2, name, pipeline
            except Exception as e:
                logger.warning(f"[ML] {name} CV failed: {e}")

        if best_model is not None:
            best_model.fit(X, y)

        return best_model, best_name, max(best_score, 0.0), n_real

    def _get_feature_importance(self, model) -> dict[str, float]:
        try:
            inner = model.named_steps["model"]
            if hasattr(inner, "feature_importances_"):
                return {name: round(float(imp), 4) for name, imp in zip(self.FEATURE_NAMES, inner.feature_importances_)}
        except Exception: pass
        return {}

    def _is_cache_valid(self) -> bool:
        return self.__class__._cached_model is not None and time.time() < self.__class__._cache_expiry

    def predict(self, batch) -> dict[str, Any]:
        """Main prediction method with thread-safe caching."""
        from django.conf import settings

        features = _extract_features(batch)
        X_input  = _features_to_array(features)

        model, model_name, score, n_real = None, "", 0.0, 0

        if self._is_cache_valid():
            model, model_name, score, n_real = (
                self.__class__._cached_model, self.__class__._cached_model_name,
                self.__class__._cached_score, self.__class__._cached_n_samples
            )
        else:
            with self.__class__._cache_lock:
                if self._is_cache_valid():
                    model, model_name, score, n_real = (
                        self.__class__._cached_model, self.__class__._cached_model_name,
                        self.__class__._cached_score, self.__class__._cached_n_samples
                    )
                else:
                    try:
                        model, model_name, score, n_real = self._train()
                        self.__class__._cached_model      = model
                        self.__class__._cached_model_name = model_name
                        self.__class__._cached_score      = score
                        self.__class__._cached_n_samples  = n_real
                        self.__class__._cache_expiry      = time.time() + self.CACHE_TTL_SECONDS
                    except Exception as e:
                        logger.error(f"[ML] Training failed: {e}")
                        return self._fallback_prediction(batch, features)

        if model is None:
            return self._fallback_prediction(batch, features)

        try:
            predicted_weight_g = max(float(model.predict(X_input)[0]), features["current_avg_weight_g"])
        except Exception as e:
            logger.error(f"[ML] Prediction failed: {e}")
            return self._fallback_prediction(batch, features)

        current_weight_g = features["current_avg_weight_g"]
        weight_gain_g = max(predicted_weight_g - current_weight_g, 0.1)
        
        # Note: Assuming 7-day window between records for daily gain calculation
        predicted_daily_gain_g = round(weight_gain_g / 7.0, 2)

        market_weight_g = float(getattr(settings, "DEFAULT_MARKET_WEIGHT_G", 500.0))
        remaining_g = max(market_weight_g - current_weight_g, 0.0)
        days_to_market = 0 if remaining_g == 0 else int(math.ceil(remaining_g / max(predicted_daily_gain_g, 0.1)))
        
        data_confidence = min(n_real / 50.0, 1.0)
        confidence_score = max(0.0, min(1.0, round(score * 0.7 + data_confidence * 0.3, 3)))

        return {
            "predicted_weight_g": round(predicted_weight_g, 2),
            "current_avg_weight_g": round(current_weight_g, 2),
            "predicted_daily_gain_g": predicted_daily_gain_g,
            "days_to_market": days_to_market,
            "estimated_harvest_date": date.today() + timedelta(days=days_to_market),
            "target_market_weight_g": market_weight_g,
            "model_used": model_name,
            "r2_score": round(score, 4),
            "confidence_score": confidence_score,
            "training_samples_real": n_real,
            "training_samples_synthetic": 300,
            "feature_importance": self._get_feature_importance(model),
            "features_used": {k: round(v, 2) for k, v in features.items()},
            "fallback": False,
        }

    def _fallback_prediction(self, batch, features: dict) -> dict[str, Any]:
        """Formula-based fallback when ML fails."""
        from django.conf import settings
        try:
            from .growth_prediction import predict_batch_growth
            result = predict_batch_growth(batch)
        except Exception as e:
            logger.error(f"[ML] Fallback failed: {e}")
            current_weight = features.get("current_avg_weight_g", 0.0)
            market_weight = float(getattr(settings, "DEFAULT_MARKET_WEIGHT_G", 500.0))
            remaining = max(market_weight - current_weight, 0.0)
            return {
                "predicted_weight_g": round(current_weight + 21.0, 2), "current_avg_weight_g": round(current_weight, 2),
                "predicted_daily_gain_g": 3.0, "days_to_market": int(math.ceil(remaining / 3.0)) if remaining > 0 else 0,
                "estimated_harvest_date": date.today() + timedelta(days=int(math.ceil(remaining / 3.0)) if remaining > 0 else 0),
                "target_market_weight_g": market_weight, "model_used": "Formula (emergency)", "r2_score": 0.0,
                "confidence_score": 0.3, "training_samples_real": 0, "training_samples_synthetic": 0,
                "feature_importance": {}, "features_used": features, "fallback": True,
            }

        result.update({
            "model_used": "Formula (fallback)", "r2_score": 0.0, "confidence_score": 0.5,
            "training_samples_real": 0, "training_samples_synthetic": 0,
            "feature_importance": {}, "features_used": features, "fallback": True,
        })
        return result


# ── Convenience & Utilities ───────────────────────────────────────────────────

def ml_predict_batch_growth(batch) -> dict[str, Any]:
    return MLGrowthPredictor().predict(batch)


def compare_models_for_paper() -> dict[str, Any]:
    """Train all models and return comparison metrics for the research paper."""
    from sklearn.ensemble import RandomForestRegressor, GradientBoostingRegressor
    from sklearn.linear_model  import LinearRegression
    from sklearn.preprocessing import StandardScaler
    from sklearn.pipeline      import Pipeline
    from sklearn.model_selection import cross_validate, KFold
    import warnings
    warnings.filterwarnings("ignore")

    X_real, y_real, n_real = _build_training_data()
    X_synth, y_synth = _generate_synthetic_data(300)

    X = np.vstack([np.tile(X_real, (3, 1)), X_synth]) if n_real >= 10 else X_synth
    y = np.concatenate([np.tile(y_real, 3), y_synth]) if n_real >= 10 else y_synth

    candidates = {
        "Random Forest": Pipeline([("scaler", StandardScaler()), ("model", RandomForestRegressor(n_estimators=150, random_state=42, n_jobs=-1))]),
        "Gradient Boosting": Pipeline([("scaler", StandardScaler()), ("model", GradientBoostingRegressor(n_estimators=120, learning_rate=0.08, random_state=42))]),
        "Linear Regression": Pipeline([("scaler", StandardScaler()), ("model", LinearRegression())]),
    }

    # NOTE: all three metrics (R2, MAE, RMSE) are computed via the SAME 5-fold
    # cross-validation, i.e. all out-of-sample. Comparing an out-of-sample R2
    # against an in-sample MAE/RMSE (fit-then-predict-on-training-data) would
    # be an apples-to-oranges comparison — tree-based models can look
    # artificially strong in-sample from memorizing training data, which
    # previously distorted this comparison.
    results, best_name, best_mae = [], "", float("inf")
    kf = KFold(n_splits=5, shuffle=True, random_state=42)

    for name, pipeline in candidates.items():
        scores = cross_validate(
            pipeline, X, y, cv=kf,
            scoring=("r2", "neg_mean_absolute_error", "neg_root_mean_squared_error"),
        )
        r2   = float(np.mean(scores["test_r2"]))
        mae  = float(-np.mean(scores["test_neg_mean_absolute_error"]))
        rmse = float(-np.mean(scores["test_neg_root_mean_squared_error"]))
        results.append({"name": name, "r2": round(r2, 4), "mae": round(mae, 2), "rmse": round(rmse, 2)})
        # Select by lowest (cross-validated) MAE — see note above on why not R2 alone.
        if mae < best_mae:
            best_mae, best_name = mae, name

    return {
        "models": results, "best_model": best_name,
        "dataset_info": {
            "real_samples": n_real, "synthetic_samples": 300,
            "total_samples": len(y), "features": len(MLGrowthPredictor.FEATURE_NAMES),
            "feature_names": MLGrowthPredictor.FEATURE_NAMES,
        },
    }