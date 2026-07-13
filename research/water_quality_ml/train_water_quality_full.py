"""
train_water_quality_full.py
=========================================================
Research model — Water Quality Risk Classifier (FULL feature set).

Data source: Kaggle "pondsdata" (apgopi) — IoT sensor readings from
3 real fishponds (Guntur, Andhra Pradesh, India), Feb 2022 - Jan 2023,
~74.7k cleaned records.

Features (all 7 sensors used to derive the original label, per the
dataset's associated Aqua-Enviro Index methodology):
    Nitrate (PPM), PH, Ammonia (mg/l), Temperature (C),
    Dissolved Oxygen (mg/l), Turbidity, Manganese (mg/l)
Target: label (0 = normal, 1 = risky water quality)

This is a standalone RESEARCH artifact for a paper — not wired into
the live Django app (the app's WeatherRecord model only tracks 3 of
these 7 sensors, so live integration would need a schema change,
which is out of scope for now).
"""
import warnings
warnings.filterwarnings("ignore")

import numpy as np
import pandas as pd
import joblib

from sklearn.ensemble import RandomForestClassifier, GradientBoostingClassifier
from sklearn.linear_model import LogisticRegression
from sklearn.preprocessing import StandardScaler
from sklearn.pipeline import Pipeline
from sklearn.model_selection import cross_val_score, StratifiedKFold, train_test_split
from sklearn.metrics import (
    classification_report, f1_score, confusion_matrix,
    roc_auc_score, accuracy_score, precision_score, recall_score,
)

RAW_PATH = "data/Ponds data.csv"
OUT_MODEL_PATH = "water_quality_risk_model_full.pkl"
OUT_REPORT_PATH = "water_quality_model_report.md"

FEATURES = ["NITRATE(PPM)", "PH", "AMMONIA(mg/l)", "TEMP", "DO", "TURBIDITY", "MANGANESE(mg/l)"]
TARGET = "label"

# ── 1. Load & clean ─────────────────────────────────────────────────────────
df = pd.read_csv(RAW_PATH, low_memory=False)
df = df[FEATURES + [TARGET]].copy()
for c in FEATURES + [TARGET]:
    df[c] = pd.to_numeric(df[c], errors="coerce")

n_raw = len(df)
df = df.dropna().drop_duplicates()
n_after_na = len(df)

# Sensor sanity filter (remove impossible dropout readings)
df = df[(df["TEMP"] > 5) & (df["DO"] >= 0) & (df["PH"] > 0) &
        (df["NITRATE(PPM)"] >= 0) & (df["TURBIDITY"] >= 0)]
n_final = len(df)

print(f"[data] raw={n_raw}  after_clean={n_after_na}  after_sanity_filter={n_final}")
print(df[TARGET].value_counts())

X = df[FEATURES].values
y = df[TARGET].values.astype(int)

X_train, X_test, y_train, y_test = train_test_split(
    X, y, test_size=0.2, random_state=42, stratify=y
)

# ── 2. Candidate models ──────────────────────────────────────────────────────
candidates = {
    "RandomForest": Pipeline([
        ("scaler", StandardScaler()),
        ("model", RandomForestClassifier(
            n_estimators=250, max_depth=14, min_samples_split=4,
            min_samples_leaf=2, class_weight="balanced",
            random_state=42, n_jobs=-1)),
    ]),
    "GradientBoosting": Pipeline([
        ("scaler", StandardScaler()),
        ("model", GradientBoostingClassifier(
            n_estimators=200, learning_rate=0.08, max_depth=5,
            subsample=0.85, random_state=42)),
    ]),
    "LogisticRegression": Pipeline([
        ("scaler", StandardScaler()),
        ("model", LogisticRegression(class_weight="balanced", max_iter=2000)),
    ]),
}

best_model, best_name, best_f1 = None, "", -1.0
cv = StratifiedKFold(n_splits=5, shuffle=True, random_state=42)
cv_results = []

print("\n[cross-validation: F1 score, 5-fold, on training split]")
for name, pipe in candidates.items():
    scores = cross_val_score(pipe, X_train, y_train, cv=cv, scoring="f1", n_jobs=-1)
    mean_f1, std_f1 = float(np.mean(scores)), float(np.std(scores))
    cv_results.append((name, mean_f1, std_f1))
    print(f"  {name:20s} F1={mean_f1:.4f}  (+/- {std_f1:.4f})")
    if mean_f1 > best_f1:
        best_f1, best_name, best_model = mean_f1, name, pipe

# ── 3. Fit best model, evaluate on held-out test set ────────────────────────
best_model.fit(X_train, y_train)
y_pred = best_model.predict(X_test)
y_proba = best_model.predict_proba(X_test)[:, 1]

test_metrics = {
    "accuracy": accuracy_score(y_test, y_pred),
    "precision": precision_score(y_test, y_pred),
    "recall": recall_score(y_test, y_pred),
    "f1": f1_score(y_test, y_pred),
    "roc_auc": roc_auc_score(y_test, y_proba),
}
cm = confusion_matrix(y_test, y_pred)
report_text = classification_report(y_test, y_pred, target_names=["normal", "risky"])

print(f"\n[best model] {best_name}  (CV F1={best_f1:.4f})")
print("\n[test set performance]")
print(report_text)
print("Confusion matrix:\n", cm)
print("ROC-AUC:", round(test_metrics["roc_auc"], 4))

# ── 4. Feature importance ────────────────────────────────────────────────────
importance = {}
inner = best_model.named_steps["model"]
if hasattr(inner, "feature_importances_"):
    importance = dict(sorted(
        zip(FEATURES, [round(float(v), 4) for v in inner.feature_importances_]),
        key=lambda kv: -kv[1]
    ))
    print("\n[feature importance, ranked]")
    for k, v in importance.items():
        print(f"  {k:18s} {v}")

# ── 5. Refit best model on ALL data for the shipped artifact ────────────────
best_model.fit(X, y)

joblib.dump({
    "model": best_model,
    "model_name": best_name,
    "features": FEATURES,
    "test_metrics": {k: round(v, 4) for k, v in test_metrics.items()},
    "cv_f1": round(best_f1, 4),
    "n_samples": n_final,
    "feature_importance": importance,
}, OUT_MODEL_PATH)
print(f"\n[saved model] {OUT_MODEL_PATH}")

# ── 6. Write a paper-ready markdown report ──────────────────────────────────
with open(OUT_REPORT_PATH, "w") as f:
    f.write("# Water Quality Risk Classification — Model Report\n\n")
    f.write("**Dataset:** Kaggle `pondsdata` (apgopi) — IoT sensor data from 3 real "
            "aquaculture ponds, Guntur, Andhra Pradesh, India (Feb 2022 – Jan 2023).\n\n")
    f.write(f"- Raw records: {n_raw:,}\n")
    f.write(f"- After cleaning (missing/duplicate/invalid removal): {n_final:,}\n")
    f.write(f"- Class balance: {int((y==0).sum()):,} normal / {int((y==1).sum()):,} risky "
            f"({(y==1).mean()*100:.1f}% positive class)\n\n")

    f.write("## Features\n\n")
    f.write("| Feature | Description |\n|---|---|\n")
    descs = {
        "NITRATE(PPM)": "Nitrate concentration (parts per million)",
        "PH": "Water pH level",
        "AMMONIA(mg/l)": "Ammonia concentration (mg/L)",
        "TEMP": "Water temperature (°C)",
        "DO": "Dissolved oxygen (mg/L)",
        "TURBIDITY": "Water turbidity (clarity)",
        "MANGANESE(mg/l)": "Manganese concentration (mg/L)",
    }
    for feat in FEATURES:
        f.write(f"| {feat} | {descs[feat]} |\n")

    f.write("\n## Model Comparison (5-fold Stratified Cross-Validation, F1 score)\n\n")
    f.write("| Model | Mean F1 | Std Dev |\n|---|---|---|\n")
    for name, mean_f1, std_f1 in sorted(cv_results, key=lambda r: -r[1]):
        f.write(f"| {name} | {mean_f1:.4f} | ±{std_f1:.4f} |\n")

    f.write(f"\n**Best model:** {best_name}\n\n")

    f.write("## Held-out Test Set Performance (20% split, stratified)\n\n")
    f.write("| Metric | Score |\n|---|---|\n")
    for k, v in test_metrics.items():
        f.write(f"| {k.replace('_', ' ').title()} | {v:.4f} |\n")

    f.write("\n### Classification Report\n\n```\n")
    f.write(report_text)
    f.write("```\n\n")

    f.write("### Confusion Matrix\n\n")
    f.write("|  | Predicted Normal | Predicted Risky |\n|---|---|---|\n")
    f.write(f"| **Actual Normal** | {cm[0][0]} | {cm[0][1]} |\n")
    f.write(f"| **Actual Risky** | {cm[1][0]} | {cm[1][1]} |\n\n")

    if importance:
        f.write("## Feature Importance (Random Forest Gini importance)\n\n")
        f.write("| Feature | Importance |\n|---|---|\n")
        for k, v in importance.items():
            f.write(f"| {k} | {v} |\n")

    f.write("\n## Notes for the paper\n\n")
    f.write("- Class imbalance (~4.5:1) handled via `class_weight='balanced'` "
            "rather than oversampling, to avoid synthetic-sample artifacts in a "
            "real-sensor dataset.\n")
    f.write("- Model selection used stratified 5-fold CV on the training split only; "
            "the held-out 20% test set was never seen during model selection.\n")
    f.write("- This classifier is trained and evaluated as a standalone research "
            "artifact; it is not currently wired into the production application, "
            "since the app's live sensor schema captures a subset of these 7 features.\n")

print(f"[saved report] {OUT_REPORT_PATH}")