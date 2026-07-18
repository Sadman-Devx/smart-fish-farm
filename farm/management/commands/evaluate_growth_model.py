"""
farm/management/commands/evaluate_growth_model.py
─────────────────────────────────────────────────────────────────────────────
Runs the existing compare_models_for_paper() function (already built into
farm/services/ml_prediction.py) and saves a paper-ready report —
supervisor feedback point #4 (ML Growth Prediction: algorithm, training
data, feature selection, performance metrics).

IMPORTANT: whether this uses REAL farm data or falls back to synthetic
data depends entirely on how many real GrowthRecord/FishBatch rows exist
in your database (see ml_prediction.py — real data is used once there are
>= 10 real samples, weighted 3x against synthetic; otherwise it's 100%
synthetic). The report explicitly states which situation applies, so you
know exactly what to claim (or not claim) about real-data validation in
the paper.

USAGE
-----
    python manage.py evaluate_growth_model
"""
from __future__ import annotations

from pathlib import Path

from django.conf import settings
from django.core.management.base import BaseCommand
from django.utils import timezone

from farm.models import FishBatch, GrowthRecord
from farm.services.ml_prediction import compare_models_for_paper


class Command(BaseCommand):
    help = "Run compare_models_for_paper() and save a paper-ready ML growth model report."

    def add_arguments(self, parser):
        parser.add_argument("--out-dir", type=str, default=None)

    def handle(self, *args, **opts):
        out_dir = Path(opts["out_dir"]) if opts["out_dir"] else (
            Path(settings.BASE_DIR) / "research" / "growth_model_eval" / "results"
        )
        out_dir.mkdir(parents=True, exist_ok=True)
        ts = timezone.now().strftime("%Y%m%d_%H%M%S")

        n_real_batches = FishBatch.objects.count()
        n_real_growth_records = GrowthRecord.objects.count()

        self.stdout.write("[running] compare_models_for_paper() — this trains multiple "
                           "models with cross-validation, may take a moment...")
        result = compare_models_for_paper()

        report_path = out_dir / f"growth_model_report_{ts}.md"
        self._write_report(report_path, result, n_real_batches, n_real_growth_records)
        self.stdout.write(self.style.SUCCESS(f"[saved] {report_path}"))
        self.stdout.write(f"Result: {result}")

    def _write_report(self, path, result, n_real_batches, n_real_growth_records):
        with open(path, "w", encoding="utf-8") as f:
            f.write("# ML Growth Prediction Model — Comparison Report\n\n")
            f.write(f"**Run date:** {timezone.now().strftime('%Y-%m-%d %H:%M')}\n\n")

            f.write("## Data source disclosure\n\n")
            f.write(f"- Real `FishBatch` records in database: {n_real_batches}\n")
            f.write(f"- Real `GrowthRecord` entries in database: {n_real_growth_records}\n\n")
            if n_real_growth_records >= 10:
                f.write("Real data volume meets the >=10-sample threshold used by "
                        "`ml_prediction.py` to blend real data (weighted 3x) with synthetic "
                        "data. Results below reflect a mix of real and synthetic training data.\n\n")
            else:
                f.write("⚠️ **Real data volume is below the >=10-sample threshold** used by "
                        "`ml_prediction.py`, so training fell back to **100% synthetic data** "
                        "(domain-informed random ranges, not measured observations). State this "
                        "explicitly in the paper's methodology/limitations section — do not "
                        "present these numbers as validated against real farm data. As real "
                        "usage accumulates, re-run this command for a stronger result.\n\n")

            f.write("## Model Comparison Results\n\n")
            f.write("```\n")
            for k, v in result.items():
                f.write(f"{k}: {v}\n")
            f.write("```\n\n")

            f.write("## Feature Set (from ml_prediction.py)\n\n")
            f.write("| Feature | Description |\n|---|---|\n")
            f.write("| age_days | Days since stocking |\n")
            f.write("| biomass_kg | Current total pond biomass |\n")
            f.write("| current_avg_weight_g | Latest average fish weight |\n")
            f.write("| water_temp_c | Water temperature |\n")
            f.write("| dissolved_oxygen | Dissolved oxygen level |\n")
            f.write("| ph | Water pH |\n")
            f.write("| feed_kg_7days | Feed given over trailing 7 days |\n")
            f.write("| species_encoded | Fish species (encoded) |\n")
            f.write("| pond_area_m2 | Pond surface area |\n")
            f.write("| survival_rate | Current survival rate |\n\n")
            f.write("**Target variable:** `next_weight_g` (predicted average fish weight)\n\n")

            f.write("## Notes for the paper\n\n")
            f.write("- Report both R², MAE, and RMSE per model (see raw result dict above) — "
                    "a single metric alone invites reviewer pushback.\n")
            f.write("- If synthetic-data-only (see disclosure above), frame this explicitly as "
                    "a proof-of-concept validation, with real-world validation identified as "
                    "future work once sufficient production data accumulates.\n")