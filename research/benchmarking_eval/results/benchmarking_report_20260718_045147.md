# Performance Benchmarking Report

**Run date:** 2026-07-18 04:53

**System:** {'cpu_cores_logical': 8, 'cpu_cores_physical': 4, 'cpu_freq_mhz': 1496.0, 'total_ram_gb': 7.85, 'available_ram_gb': 1.49, 'ram_usage_pct': 81.0, 'python_process_mb': 139.22, 'platform': 'Windows (11)', 'python_version': '3.14.5', 'benchmark_at': '2026-07-18T10:51:47.943010'}

## A. Controlled Benchmark (response time, resource utilization)

Ran 15 measured iterations per operation (plus 3 warmup iterations to eliminate cold-start bias).

| Metric | Value |
|---|---|
| Total operations measured | 75 |
| Successful | 60 |
| Failed | 15 |
| Average response time | 9.92 ms |
| Median response time | 12.15 ms |
| Min / Max | 0.06 / 24.45 ms |
| P95 | 16.99 ms |
| P99 | 23.94 ms |

### Per-operation breakdown

| Operation | Runs | Avg (ms) | Avg Memory Δ (MB) | Avg DB Queries |
|---|---|---|---|---|
| ml_prediction | 15 | 13.86 | 0.0 | 0.0 |
| feed_calculation | 15 | 0 | N/A | N/A |
| alert_generation | 15 | 0.08 | 0.0 | 0.0 |
| db_queries | 15 | 15.66 | -0.001 | 7.0 |
| api_serialization | 15 | 10.07 | 0.0 | 3.0 |

## B. Real Production Usage Stats

No `PerformanceLog` entries found — this means the `benchmark_view` decorator (in `farm/services/benchmarking.py`) hasn't been applied to live views yet, or the app hasn't received real traffic. Section A above (controlled benchmark) is the primary evidence for the paper in the meantime. To populate this section: apply `@benchmark_view` to key view functions and let the app run under normal/real usage for a while, then re-run this command.

## Notes for the paper

- Section A gives controlled, reproducible latency figures suitable for a 'Performance Testing' subsection (point #16) — response time, P95/P99 tail latency, and per-operation memory/DB-query cost.
- Section B (if populated) gives real-world evidence of production behavior, strengthening the benchmarking module claim (point #11).
