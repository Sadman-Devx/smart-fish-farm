# ML Growth Prediction Model — Comparison Report

**Run date:** 2026-07-18 04:50

## Data source disclosure

- Real `FishBatch` records in database: 1
- Real `GrowthRecord` entries in database: 0

⚠️ **Real data volume is below the >=10-sample threshold** used by `ml_prediction.py`, so training fell back to **100% synthetic data** (domain-informed random ranges, not measured observations). State this explicitly in the paper's methodology/limitations section — do not present these numbers as validated against real farm data. As real usage accumulates, re-run this command for a stronger result.

## Model Comparison Results

```
models: [{'name': 'Random Forest', 'r2': 0.9966, 'mae': 6.32, 'rmse': 8.75}, {'name': 'Gradient Boosting', 'r2': 0.9981, 'mae': 5.27, 'rmse': 6.6}, {'name': 'Linear Regression', 'r2': 0.9993, 'mae': 3.39, 'rmse': 4.06}]
best_model: Linear Regression
dataset_info: {'real_samples': 0, 'synthetic_samples': 300, 'total_samples': 300, 'features': 10, 'feature_names': ['age_days', 'biomass_kg', 'current_avg_weight_g', 'water_temp_c', 'dissolved_oxygen', 'ph', 'feed_kg_7days', 'species_encoded', 'pond_area_m2', 'survival_rate']}
```

## Feature Set (from ml_prediction.py)

| Feature | Description |
|---|---|
| age_days | Days since stocking |
| biomass_kg | Current total pond biomass |
| current_avg_weight_g | Latest average fish weight |
| water_temp_c | Water temperature |
| dissolved_oxygen | Dissolved oxygen level |
| ph | Water pH |
| feed_kg_7days | Feed given over trailing 7 days |
| species_encoded | Fish species (encoded) |
| pond_area_m2 | Pond surface area |
| survival_rate | Current survival rate |

**Target variable:** `next_weight_g` (predicted average fish weight)

## Notes for the paper

- Report both R², MAE, and RMSE per model (see raw result dict above) — a single metric alone invites reviewer pushback.
- If synthetic-data-only (see disclosure above), frame this explicitly as a proof-of-concept validation, with real-world validation identified as future work once sufficient production data accumulates.
