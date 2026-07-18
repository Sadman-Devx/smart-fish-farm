"""
farm/management/commands/evaluate_farm_analytics.py
─────────────────────────────────────────────────────────────────────────────
Aggregates FCR, Growth Rate, Mortality Rate, and Profitability results across
all real FishBatch records for the paper — supervisor feedback point #10.

Reuses existing production logic (farm/services/fcr_analytics.py) rather
than re-implementing FCR math, and adds Growth Rate (Specific Growth Rate,
SGR %/day), Mortality Rate, and Profitability, which don't yet have a
dedicated service function.

Literature benchmarks cited in the report for comparison (see Sources).

USAGE
-----
    python manage.py evaluate_farm_analytics
"""
from __future__ import annotations

import math
from pathlib import Path

from django.conf import settings
from django.core.management.base import BaseCommand
from django.db.models import Sum
from django.utils import timezone

from farm.models import FishBatch, MortalityLog, HarvestRecord, Expense
from farm.services.fcr_analytics import calculate_batch_fcr

# Literature benchmarks (see report "Sources")
SGR_ACCEPTABLE_RANGE = (1.5, 3.5)   # %/day, typical tilapia grow-out
MORTALITY_ACCEPTABLE_MAX = 20.0     # %, typical acceptable cumulative mortality per cycle


class Command(BaseCommand):
    help = "Aggregate FCR / Growth Rate / Mortality Rate / Profitability across all batches for the paper."

    def add_arguments(self, parser):
        parser.add_argument("--out-dir", type=str, default=None)

    def handle(self, *args, **opts):
        out_dir = Path(opts["out_dir"]) if opts["out_dir"] else (
            Path(settings.BASE_DIR) / "research" / "farm_analytics_eval" / "results"
        )
        out_dir.mkdir(parents=True, exist_ok=True)
        ts = timezone.now().strftime("%Y%m%d_%H%M%S")

        batches = list(FishBatch.objects.all())
        if not batches:
            self.stdout.write(self.style.WARNING(
                "No FishBatch records found — nothing to analyze. This report needs at "
                "least one real batch with growth/feed/harvest history."
            ))

        results = [self._analyze_batch(b) for b in batches]
        report_path = out_dir / f"farm_analytics_report_{ts}.md"
        self._write_report(report_path, results)
        self.stdout.write(self.style.SUCCESS(f"[saved] {report_path}"))
        self.stdout.write(f"Analyzed {len(results)} batch(es).")

    def _analyze_batch(self, batch: FishBatch) -> dict:
        out = {"batch": str(batch), "batch_id": batch.id, "pond": batch.pond.name if batch.pond else "N/A"}

        # ── Growth Rate (Specific Growth Rate, %/day) ───────────────────────
        latest_growth = batch.growth_records.order_by("-date").first()
        if latest_growth and latest_growth.avg_weight_g:
            days = (latest_growth.date - batch.stocking_date).days
            w0 = float(batch.initial_avg_weight_g)
            w1 = float(latest_growth.avg_weight_g)
            if days > 0 and w0 > 0 and w1 > 0:
                sgr = (math.log(w1) - math.log(w0)) / days * 100
                out["sgr_pct_per_day"] = round(sgr, 3)
                out["days_tracked"] = days
                out["weight_start_g"] = w0
                out["weight_latest_g"] = w1
            else:
                out["sgr_pct_per_day"] = None
        else:
            out["sgr_pct_per_day"] = None

        # ── Mortality Rate ───────────────────────────────────────────────────
        total_mortality = MortalityLog.objects.filter(batch=batch).aggregate(t=Sum("count"))["t"] or 0
        out["total_mortality"] = total_mortality
        out["mortality_rate_pct"] = round(total_mortality / batch.initial_count * 100, 2) if batch.initial_count else None

        # ── FCR (reuses production logic) ───────────────────────────────────
        fcr_result = calculate_batch_fcr(batch)
        out["fcr"] = fcr_result

        # ── Profitability ────────────────────────────────────────────────────
        harvests = HarvestRecord.objects.filter(batch=batch)
        revenue = sum(float(h.gross_revenue) for h in harvests)
        last_harvest_date = max((h.harvest_date for h in harvests), default=None)
        expense_end = last_harvest_date or timezone.now().date()
        expenses = Expense.objects.filter(
            pond=batch.pond, date__gte=batch.stocking_date, date__lte=expense_end,
        ) if batch.pond else Expense.objects.none()
        cost = float(expenses.aggregate(t=Sum("amount"))["t"] or 0)

        out["revenue_bdt"] = round(revenue, 2)
        out["cost_bdt"] = round(cost, 2)
        out["profit_bdt"] = round(revenue - cost, 2)
        out["profit_margin_pct"] = round((revenue - cost) / revenue * 100, 1) if revenue > 0 else None
        out["has_harvest"] = harvests.exists()

        return out

    def _write_report(self, path, results):
        with open(path, "w", encoding="utf-8") as f:
            f.write("# Farm Analytics — FCR, Growth Rate, Mortality Rate, Profitability\n\n")
            f.write(f"**Run date:** {timezone.now().strftime('%Y-%m-%d %H:%M')}\n\n")
            f.write(f"**Batches analyzed:** {len(results)}\n\n")

            if not results:
                f.write("No batch data available yet.\n")
                return

            f.write("## Per-Batch Summary\n\n")
            f.write("| Batch | Pond | SGR (%/day) | Mortality Rate | FCR | FCR Status | Profit (BDT) |\n")
            f.write("|---|---|---|---|---|---|---|\n")
            for r in results:
                sgr = f"{r['sgr_pct_per_day']}" if r["sgr_pct_per_day"] is not None else "N/A"
                mort = f"{r['mortality_rate_pct']}%" if r["mortality_rate_pct"] is not None else "N/A"
                fcr_val = r["fcr"]["fcr"] if r["fcr"] else "N/A"
                fcr_status = r["fcr"]["status"] if r["fcr"] else "N/A"
                profit = f"{r['profit_bdt']:,.0f}" if r["has_harvest"] else "N/A (not harvested)"
                f.write(f"| {r['batch']} | {r['pond']} | {sgr} | {mort} | {fcr_val} | {fcr_status} | {profit} |\n")

            # ── Aggregate stats ──────────────────────────────────────────────
            sgrs = [r["sgr_pct_per_day"] for r in results if r["sgr_pct_per_day"] is not None]
            morts = [r["mortality_rate_pct"] for r in results if r["mortality_rate_pct"] is not None]
            fcrs = [r["fcr"]["fcr"] for r in results if r["fcr"] and r["fcr"].get("fcr")]
            profits = [r["profit_bdt"] for r in results if r["has_harvest"]]

            f.write("\n## Aggregate Statistics\n\n")
            if sgrs:
                avg_sgr = sum(sgrs) / len(sgrs)
                in_range = SGR_ACCEPTABLE_RANGE[0] <= avg_sgr <= SGR_ACCEPTABLE_RANGE[1]
                f.write(f"- **Average Growth Rate (SGR):** {avg_sgr:.2f} %/day "
                        f"({'within' if in_range else 'outside'} typical tilapia grow-out range "
                        f"{SGR_ACCEPTABLE_RANGE[0]}-{SGR_ACCEPTABLE_RANGE[1]} %/day)\n")
            else:
                f.write("- Growth Rate: insufficient growth-record history to compute.\n")

            if morts:
                avg_mort = sum(morts) / len(morts)
                f.write(f"- **Average Mortality Rate:** {avg_mort:.2f}% "
                        f"({'within' if avg_mort <= MORTALITY_ACCEPTABLE_MAX else 'above'} the "
                        f"typical acceptable range of <{MORTALITY_ACCEPTABLE_MAX}% per cycle)\n")
            else:
                f.write("- Mortality Rate: no mortality log history yet.\n")

            if fcrs:
                avg_fcr = sum(fcrs) / len(fcrs)
                f.write(f"- **Average FCR:** {avg_fcr:.2f}\n")
            else:
                f.write("- FCR: insufficient feed/growth history to compute.\n")

            if profits:
                total_profit = sum(profits)
                f.write(f"- **Total Profit (harvested batches):** {total_profit:,.0f} BDT across "
                        f"{len(profits)} harvested batch(es)\n")
            else:
                f.write("- Profitability: no harvested batches yet — cannot compute realized profit.\n")

            f.write("\n## Notes on methodology\n\n")
            f.write("- **Growth Rate** uses Specific Growth Rate: "
                    "`SGR = (ln(W_final) - ln(W_initial)) / days × 100`.\n")
            f.write("- **Mortality Rate** = total logged deaths / initial stocked count × 100.\n")
            f.write("- **FCR** reuses the production `calculate_batch_fcr()` logic "
                    "(farm/services/fcr_analytics.py) — same calculation shown to farmers in-app.\n")
            f.write("- **Profitability** = harvest revenue (from `HarvestRecord`) minus pond "
                    "expenses (`Expense`) logged between stocking and harvest date. This is an "
                    "approximation where a pond had exactly one active batch during that window; "
                    "with overlapping batches on the same pond, expenses should ideally be "
                    "batch-tagged directly for full accuracy — worth noting as a data-model "
                    "limitation if that applies to your farm data.\n")

            f.write("\n## Sources\n\n")
            f.write("- Typical tilapia grow-out SGR and acceptable mortality ranges: general "
                    "aquaculture production guidance (FAO aquaculture production manuals; "
                    "Bangladesh pond-culture studies).\n")
            f.write("- FCR benchmarks: see `FCR_BENCHMARKS` in `farm/services/fcr_analytics.py` "
                    "(species-specific optimal/poor thresholds already cited there).\n")