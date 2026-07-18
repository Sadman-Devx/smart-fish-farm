"""
farm/management/commands/evaluate_benchmarking.py
─────────────────────────────────────────────────────────────────────────────
Runs the existing benchmarking service (farm/services/benchmarking.py) and
saves a paper-ready report — supervisor feedback points #11 (Benchmarking
module evaluation results) and #16 (Performance testing: response time,
API latency, resource utilization).

Two data sources, both already built into the app:
  1. run_full_benchmark() — a CONTROLLED synthetic benchmark: runs ML
     prediction, feed calculation, alert generation, DB queries, and API
     serialization n_iterations times each (with warmup) and reports
     response-time percentiles. Needs at least one real FishBatch and one
     WeatherRecord in the DB to exercise those code paths meaningfully.
  2. get_benchmark_stats_for_paper() — REAL production usage stats, but
     only populated if farm/services/benchmarking.py's `benchmark_view`
     decorator has actually been applied to live views and has received
     real traffic. If unused, this returns {"no_data": True} and the
     report notes that clearly rather than fabricating numbers.

USAGE
-----
    python manage.py evaluate_benchmarking
    python manage.py evaluate_benchmarking --iterations 20 --warmup 3
"""
from __future__ import annotations

from pathlib import Path

from django.conf import settings
from django.core.management.base import BaseCommand
from django.utils import timezone

from farm.models import FishBatch, WeatherRecord
from farm.services.benchmarking import run_full_benchmark, get_benchmark_stats_for_paper


class Command(BaseCommand):
    help = "Run the performance benchmarking suite and save a paper-ready report."

    def add_arguments(self, parser):
        parser.add_argument("--iterations", type=int, default=15)
        parser.add_argument("--warmup", type=int, default=3)
        parser.add_argument("--out-dir", type=str, default=None)

    def handle(self, *args, **opts):
        out_dir = Path(opts["out_dir"]) if opts["out_dir"] else (
            Path(settings.BASE_DIR) / "research" / "benchmarking_eval" / "results"
        )
        out_dir.mkdir(parents=True, exist_ok=True)
        ts = timezone.now().strftime("%Y%m%d_%H%M%S")

        has_batch = FishBatch.objects.exists()
        has_weather = WeatherRecord.objects.exists()
        if not has_batch:
            self.stdout.write(self.style.WARNING(
                "No FishBatch in DB — ML prediction and feed calculation benchmarks will be skipped."
            ))
        if not has_weather:
            self.stdout.write(self.style.WARNING(
                "No WeatherRecord in DB — alert generation benchmark will be skipped."
            ))

        self.stdout.write(f"[running] Controlled benchmark suite "
                           f"({opts['iterations']} iterations, {opts['warmup']} warmup)...")
        suite = run_full_benchmark(n_iterations=opts["iterations"], warmup=opts["warmup"])

        self.stdout.write("[checking] Real production usage stats (get_benchmark_stats_for_paper)...")
        prod_stats = get_benchmark_stats_for_paper()

        report_path = out_dir / f"benchmarking_report_{ts}.md"
        self._write_report(report_path, suite, prod_stats, opts)
        self.stdout.write(self.style.SUCCESS(f"[saved] {report_path}"))
        self.stdout.write(f"Summary: {suite.summary}")

        failures = [r for r in suite.results if not r.success]
        if failures:
            self.stdout.write(self.style.ERROR(f"\n[{len(failures)} failures found] Sample errors:"))
            seen_ops = set()
            for r in failures:
                if r.operation not in seen_ops:
                    seen_ops.add(r.operation)
                    self.stdout.write(self.style.ERROR(f"  [{r.operation}] {r.error}"))

    def _write_report(self, path, suite, prod_stats, opts):
        with open(path, "w", encoding="utf-8") as f:
            f.write("# Performance Benchmarking Report\n\n")
            f.write(f"**Run date:** {timezone.now().strftime('%Y-%m-%d %H:%M')}\n\n")
            f.write(f"**System:** {suite.system_info}\n\n")

            f.write("## A. Controlled Benchmark (response time, resource utilization)\n\n")
            f.write(f"Ran {opts['iterations']} measured iterations per operation "
                    f"(plus {opts['warmup']} warmup iterations to eliminate cold-start bias).\n\n")

            s = suite.summary
            if not s:
                f.write("No results collected — likely no FishBatch/WeatherRecord in the "
                        "database to exercise the benchmarked code paths. Add at least one "
                        "batch and one weather record, then re-run.\n\n")
            else:
                f.write("| Metric | Value |\n|---|---|\n")
                f.write(f"| Total operations measured | {s['total_operations']} |\n")
                f.write(f"| Successful | {s['successful']} |\n")
                f.write(f"| Failed | {s['failed']} |\n")
                f.write(f"| Average response time | {s['avg_response_ms']} ms |\n")
                f.write(f"| Median response time | {s['median_response_ms']} ms |\n")
                f.write(f"| Min / Max | {s['min_response_ms']} / {s['max_response_ms']} ms |\n")
                f.write(f"| P95 | {s['p95_response_ms']} ms |\n")
                f.write(f"| P99 | {s['p99_response_ms']} ms |\n\n")

                # Per-operation breakdown
                by_op = {}
                for r in suite.results:
                    by_op.setdefault(r.operation, []).append(r)
                f.write("### Per-operation breakdown\n\n")
                f.write("| Operation | Runs | Successes | Avg (ms) | Avg Memory Δ (MB) | Avg DB Queries |\n|---|---|---|---|---|---|\n")
                for op, results in by_op.items():
                    times = [r.elapsed_ms for r in results if r.success]
                    mem = [r.memory_delta_mb for r in results if hasattr(r, "memory_delta_mb") and r.success]
                    queries = [r.db_query_count for r in results if hasattr(r, "db_query_count") and r.success]
                    n_success = sum(1 for r in results if r.success)
                    avg_t = round(sum(times) / len(times), 2) if times else 0
                    avg_m = round(sum(mem) / len(mem), 3) if mem else "N/A"
                    avg_q = round(sum(queries) / len(queries), 1) if queries else "N/A"
                    f.write(f"| {op} | {len(results)} | {n_success}/{len(results)} | {avg_t} | {avg_m} | {avg_q} |\n")

                failed_ops = {op: results for op, results in by_op.items() if any(not r.success for r in results)}
                if failed_ops:
                    f.write("\n### Sample errors from failed operations\n\n")
                    for op, results in failed_ops.items():
                        failures = [r for r in results if not r.success]
                        sample_error = failures[0].error if failures[0].error else "(no error message captured)"
                        f.write(f"**{op}** ({len(failures)}/{len(results)} failed):\n```\n{sample_error}\n```\n\n")

            f.write("\n## B. Real Production Usage Stats\n\n")
            if prod_stats.get("no_data"):
                f.write("No `PerformanceLog` entries found — this means the `benchmark_view` "
                        "decorator (in `farm/services/benchmarking.py`) hasn't been applied to "
                        "live views yet, or the app hasn't received real traffic. Section A "
                        "above (controlled benchmark) is the primary evidence for the paper in "
                        "the meantime. To populate this section: apply `@benchmark_view` to key "
                        "view functions and let the app run under normal/real usage for a "
                        "while, then re-run this command.\n\n")
            else:
                f.write("```\n")
                for k, v in prod_stats.items():
                    f.write(f"{k}: {v}\n")
                f.write("```\n\n")

            f.write("## Notes for the paper\n\n")
            f.write("- Section A gives controlled, reproducible latency figures suitable for a "
                    "'Performance Testing' subsection (point #16) — response time, P95/P99 "
                    "tail latency, and per-operation memory/DB-query cost.\n")
            f.write("- Section B (if populated) gives real-world evidence of production "
                    "behavior, strengthening the benchmarking module claim (point #11).\n")