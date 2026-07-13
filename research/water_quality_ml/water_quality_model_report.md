# Water Quality Risk Classification — Model Report

**Dataset:** Kaggle `pondsdata` (apgopi) — IoT sensor data from 3 real aquaculture ponds, Guntur, Andhra Pradesh, India (Feb 2022 – Jan 2023).

- Raw records: 74,796
- After cleaning (missing/duplicate/invalid removal): 74,708
- Class balance: 61,308 normal / 13,400 risky (17.9% positive class)

## Features

| Feature | Description |
|---|---|
| NITRATE(PPM) | Nitrate concentration (parts per million) |
| PH | Water pH level |
| AMMONIA(mg/l) | Ammonia concentration (mg/L) |
| TEMP | Water temperature (°C) |
| DO | Dissolved oxygen (mg/L) |
| TURBIDITY | Water turbidity (clarity) |
| MANGANESE(mg/l) | Manganese concentration (mg/L) |

## Model Comparison (5-fold Stratified Cross-Validation, F1 score)

| Model | Mean F1 | Std Dev |
|---|---|---|
| RandomForest | 0.7849 | ±0.0035 |
| GradientBoosting | 0.7684 | ±0.0066 |
| LogisticRegression | 0.7581 | ±0.0047 |

**Best model:** RandomForest

## Held-out Test Set Performance (20% split, stratified)

| Metric | Score |
|---|---|
| Accuracy | 0.9032 |
| Precision | 0.6531 |
| Recall | 0.9813 |
| F1 | 0.7843 |
| Roc Auc | 0.9518 |

### Classification Report

```
              precision    recall  f1-score   support

      normal       1.00      0.89      0.94     12262
       risky       0.65      0.98      0.78      2680

    accuracy                           0.90     14942
   macro avg       0.82      0.93      0.86     14942
weighted avg       0.93      0.90      0.91     14942
```

### Confusion Matrix

|  | Predicted Normal | Predicted Risky |
|---|---|---|
| **Actual Normal** | 10865 | 1397 |
| **Actual Risky** | 50 | 2630 |

## Feature Importance (Random Forest Gini importance)

| Feature | Importance |
|---|---|
| NITRATE(PPM) | 0.3694 |
| MANGANESE(mg/l) | 0.3176 |
| AMMONIA(mg/l) | 0.1391 |
| DO | 0.0924 |
| TEMP | 0.0436 |
| TURBIDITY | 0.0244 |
| PH | 0.0135 |

## Notes for the paper

- Class imbalance (~4.5:1) handled via `class_weight='balanced'` rather than oversampling, to avoid synthetic-sample artifacts in a real-sensor dataset.
- Model selection used stratified 5-fold CV on the training split only; the held-out 20% test set was never seen during model selection.
- This classifier is trained and evaluated as a standalone research artifact; it is not currently wired into the production application, since the app's live sensor schema captures a subset of these 7 features.
