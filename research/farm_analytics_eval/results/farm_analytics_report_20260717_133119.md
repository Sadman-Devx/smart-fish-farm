# Farm Analytics — FCR, Growth Rate, Mortality Rate, Profitability

**Run date:** 2026-07-17 13:31

**Batches analyzed:** 1

## Per-Batch Summary

| Batch | Pond | SGR (%/day) | Mortality Rate | FCR | FCR Status | Profit (BDT) |
|---|---|---|---|---|---|---|
| Tilapia batch in Tilapia Pond A | Tilapia Pond A | N/A | 0.0% | N/A | N/A | N/A (not harvested) |

## Aggregate Statistics

- Growth Rate: insufficient growth-record history to compute.
- **Average Mortality Rate:** 0.00% (within the typical acceptable range of <20.0% per cycle)
- FCR: insufficient feed/growth history to compute.
- Profitability: no harvested batches yet — cannot compute realized profit.

## Notes on methodology

- **Growth Rate** uses Specific Growth Rate: `SGR = (ln(W_final) - ln(W_initial)) / days × 100`.
- **Mortality Rate** = total logged deaths / initial stocked count × 100.
- **FCR** reuses the production `calculate_batch_fcr()` logic (farm/services/fcr_analytics.py) — same calculation shown to farmers in-app.
- **Profitability** = harvest revenue (from `HarvestRecord`) minus pond expenses (`Expense`) logged between stocking and harvest date. This is an approximation where a pond had exactly one active batch during that window; with overlapping batches on the same pond, expenses should ideally be batch-tagged directly for full accuracy — worth noting as a data-model limitation if that applies to your farm data.

## Sources

- Typical tilapia grow-out SGR and acceptable mortality ranges: general aquaculture production guidance (FAO aquaculture production manuals; Bangladesh pond-culture studies).
- FCR benchmarks: see `FCR_BENCHMARKS` in `farm/services/fcr_analytics.py` (species-specific optimal/poor thresholds already cited there).
