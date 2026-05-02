"""
─────────────────────────────────────────────────────────────────────────────
Performance Benchmarking Service for AquaSmart
================================================

Measures and records system performance metrics for research paper evaluation.

Metrics collected:
  1. Response Time     — view execution time (ms)
  2. Database Queries  — count + total query time per request
  3. Memory Usage      — RSS memory before/after operations (MB)
  4. CPU Usage         — process CPU % during operations
  5. ML Prediction Time — time taken for ML inference (ms)
  6. Feed Calculation Time — time for smart feed calculation (ms)
  7. Alert Generation Time — time for water alert checks (ms)
  8. API Throughput    — requests per second (simulated)

Usage:
    # As decorator on views
    from farm.services.benchmarking import benchmark_view

    @benchmark_view
    def my_view(request):
        ...

    # Manual timing
    from farm.services.benchmarking import BenchmarkTimer
    with BenchmarkTimer("ml_prediction") as t:
        result = ml_predict_batch_growth(batch)
    print(t.elapsed_ms)

    # Full system benchmark (for paper)
    from farm.services.benchmarking import run_full_benchmark
    results = run_full_benchmark()
"""

from __future__ import annotations

import functools
import gc
import logging
import statistics
import time
from contextlib import contextmanager
from dataclasses import dataclass, field, asdict
from datetime import datetime
from typing import Any, Callable, Optional

import psutil

logger = logging.getLogger(__name__)


# ── Data classes ──────────────────────────────────────────────────────────────

@dataclass
class BenchmarkResult:
    """Single benchmark measurement result."""
    operation:      str
    elapsed_ms:     float
    memory_before_mb: float
    memory_after_mb:  float
    memory_delta_mb:  float
    cpu_percent:    float
    db_query_count: int
    db_query_time_ms: float
    timestamp:      str
    success:        bool
    error:          Optional[str] = None
    extra:          dict = field(default_factory=dict)

    def to_dict(self) -> dict:
        return asdict(self)


@dataclass
class BenchmarkSuite:
    """Collection of benchmark results for a full test run."""
    suite_name:   str
    started_at:   str
    finished_at:  str
    results:      list[BenchmarkResult]
    system_info:  dict

    @property
    def summary(self) -> dict:
        if not self.results:
            return {}
        times = [r.elapsed_ms for r in self.results if r.success]
        return {
            "total_operations":   len(self.results),
            "successful":         sum(1 for r in self.results if r.success),
            "failed":             sum(1 for r in self.results if not r.success),
            "avg_response_ms":    round(statistics.mean(times), 2) if times else 0,
            "min_response_ms":    round(min(times), 2) if times else 0,
            "max_response_ms":    round(max(times), 2) if times else 0,
            "median_response_ms": round(statistics.median(times), 2) if times else 0,
            "p95_response_ms":    round(_percentile(times, 95), 2) if times else 0,
            "p99_response_ms":    round(_percentile(times, 99), 2) if times else 0,
        }


# ── Helpers ───────────────────────────────────────────────────────────────────

def _percentile(data: list[float], pct: float) -> float:
    if not data:
        return 0.0
    sorted_data = sorted(data)
    idx = int(len(sorted_data) * pct / 100)
    idx = min(idx, len(sorted_data) - 1)
    return sorted_data[idx]


def _get_memory_mb() -> float:
    """Current process RSS memory in MB."""
    try:
        proc = psutil.Process()
        return proc.memory_info().rss / (1024 * 1024)
    except Exception:
        return 0.0


def _get_cpu_percent() -> float:
    """Current process CPU percent."""
    try:
        proc = psutil.Process()
        return proc.cpu_percent(interval=0.05)
    except Exception:
        return 0.0


def _get_system_info() -> dict:
    """Collect system info for paper's experimental setup section."""
    try:
        proc    = psutil.Process()
        vm      = psutil.virtual_memory()
        cpu_cnt = psutil.cpu_count(logical=True)
        return {
            "cpu_cores_logical":   cpu_cnt,
            "cpu_cores_physical":  psutil.cpu_count(logical=False),
            "total_ram_gb":        round(vm.total / (1024 ** 3), 2),
            "available_ram_gb":    round(vm.available / (1024 ** 3), 2),
            "ram_usage_pct":       vm.percent,
            "python_process_mb":   round(proc.memory_info().rss / (1024 * 1024), 2),
            "platform":            "Linux (Ubuntu)",
            "benchmark_at":        datetime.now().isoformat(),
        }
    except Exception:
        return {}


# ── Core timer context manager ────────────────────────────────────────────────

class BenchmarkTimer:
    """
    Context manager for timing any code block.

    Usage:
        with BenchmarkTimer("my_operation") as t:
            do_something()
        print(f"Took {t.elapsed_ms:.2f} ms")
    """

    def __init__(self, operation: str):
        self.operation    = operation
        self.elapsed_ms   = 0.0
        self.memory_before = 0.0
        self.memory_after  = 0.0
        self._start       = 0.0

    def __enter__(self):
        gc.collect()
        self.memory_before = _get_memory_mb()
        self._start        = time.perf_counter()
        return self

    def __exit__(self, *args):
        elapsed       = time.perf_counter() - self._start
        self.elapsed_ms    = round(elapsed * 1000, 3)
        self.memory_after  = _get_memory_mb()
        self.memory_delta  = round(self.memory_after - self.memory_before, 3)


# ── View decorator ────────────────────────────────────────────────────────────

def benchmark_view(view_func: Callable) -> Callable:
    """
    Decorator that measures view performance and saves to PerformanceLog.

    Usage:
        @benchmark_view
        def dashboard(request):
            ...
    """
    @functools.wraps(view_func)
    def wrapper(request, *args, **kwargs):
        from django.db import connection, reset_queries
        from django.conf import settings as django_settings

        # Enable query logging temporarily
        _debug_was = django_settings.DEBUG
        django_settings.DEBUG = True
        reset_queries()

        mem_before  = _get_memory_mb()
        start_time  = time.perf_counter()

        try:
            response = view_func(request, *args, **kwargs)
            success  = True
            error    = None
        except Exception as exc:
            success  = False
            error    = str(exc)
            raise
        finally:
            elapsed_ms = round((time.perf_counter() - start_time) * 1000, 3)
            mem_after  = _get_memory_mb()

            # Collect DB stats
            queries        = connection.queries
            db_count       = len(queries)
            db_time_ms     = round(
                sum(float(q.get("time", 0)) for q in queries) * 1000, 3
            )

            # Restore debug setting
            django_settings.DEBUG = _debug_was

            # Save to DB (non-blocking)
            try:
                _save_performance_log(
                    endpoint=view_func.__name__,
                    method=request.method,
                    elapsed_ms=elapsed_ms,
                    memory_before_mb=mem_before,
                    memory_after_mb=mem_after,
                    db_query_count=db_count,
                    db_query_time_ms=db_time_ms,
                    success=success,
                    error=error or "",
                )
            except Exception as e:
                logger.warning(f"[Benchmark] Failed to save log: {e}")

        return response
    return wrapper


def _save_performance_log(**kwargs):
    """Save performance data to database."""
    try:
        from ..models import PerformanceLog
        PerformanceLog.objects.create(**kwargs)
    except Exception as e:
        logger.debug(f"[Benchmark] DB save skipped: {e}")


# ── Operation benchmarkers ────────────────────────────────────────────────────

def benchmark_ml_prediction(batch) -> BenchmarkResult:
    """Benchmark ML prediction for a single batch."""
    from .ml_prediction import ml_predict_batch_growth

    mem_before = _get_memory_mb()
    cpu_before = _get_cpu_percent()
    start      = time.perf_counter()

    try:
        result  = ml_predict_batch_growth(batch)
        success = True
        error   = None
        extra   = {
            "model_used":      result.get("model_used", ""),
            "r2_score":        result.get("r2_score", 0),
            "training_samples": result.get("training_samples_real", 0),
        }
    except Exception as exc:
        success = False
        error   = str(exc)
        extra   = {}

    elapsed_ms = round((time.perf_counter() - start) * 1000, 3)
    mem_after  = _get_memory_mb()

    return BenchmarkResult(
        operation="ml_prediction",
        elapsed_ms=elapsed_ms,
        memory_before_mb=round(mem_before, 2),
        memory_after_mb=round(mem_after, 2),
        memory_delta_mb=round(mem_after - mem_before, 2),
        cpu_percent=round(_get_cpu_percent(), 2),
        db_query_count=0,
        db_query_time_ms=0.0,
        timestamp=datetime.now().isoformat(),
        success=success,
        error=error,
        extra=extra,
    )


def benchmark_feed_calculation(batch) -> BenchmarkResult:
    """Benchmark smart feed calculation."""
    from .feed_calculator import smart_feed_kg_for_batch

    mem_before = _get_memory_mb()
    start      = time.perf_counter()

    try:
        result  = smart_feed_kg_for_batch(batch)
        success = True
        error   = None
        extra   = {"feed_kg": result}
    except Exception as exc:
        success = False
        error   = str(exc)
        extra   = {}

    elapsed_ms = round((time.perf_counter() - start) * 1000, 3)
    mem_after  = _get_memory_mb()

    return BenchmarkResult(
        operation="feed_calculation",
        elapsed_ms=elapsed_ms,
        memory_before_mb=round(mem_before, 2),
        memory_after_mb=round(mem_after, 2),
        memory_delta_mb=round(mem_after - mem_before, 2),
        cpu_percent=round(_get_cpu_percent(), 2),
        db_query_count=0,
        db_query_time_ms=0.0,
        timestamp=datetime.now().isoformat(),
        success=success,
        error=error,
        extra=extra,
    )


def benchmark_alert_generation(weather_record) -> BenchmarkResult:
    """Benchmark water quality alert generation."""
    from ..views import _generate_water_alerts

    mem_before = _get_memory_mb()
    start      = time.perf_counter()

    try:
        _generate_water_alerts(weather_record)
        success = True
        error   = None
    except Exception as exc:
        success = False
        error   = str(exc)

    elapsed_ms = round((time.perf_counter() - start) * 1000, 3)
    mem_after  = _get_memory_mb()

    return BenchmarkResult(
        operation="alert_generation",
        elapsed_ms=elapsed_ms,
        memory_before_mb=round(mem_before, 2),
        memory_after_mb=round(mem_after, 2),
        memory_delta_mb=round(mem_after - mem_before, 2),
        cpu_percent=round(_get_cpu_percent(), 2),
        db_query_count=0,
        db_query_time_ms=0.0,
        timestamp=datetime.now().isoformat(),
        success=success,
        error=error,
        extra={},
    )


# ── Full benchmark suite (for paper) ─────────────────────────────────────────

def run_full_benchmark(n_iterations: int = 10) -> BenchmarkSuite:
    """
    Run complete benchmark suite across all major operations.
    Call this from the benchmark dashboard view.

    Args:
        n_iterations: How many times to repeat each operation (default 10)

    Returns:
        BenchmarkSuite with all results and summary statistics.
    """
    from ..models import FishBatch, WeatherRecord, Pond
    from decimal import Decimal

    started_at  = datetime.now().isoformat()
    all_results: list[BenchmarkResult] = []
    system_info = _get_system_info()

    # ── Get test data ──────────────────────────────────────────────────────────
    batch         = FishBatch.objects.select_related("pond").first()
    weather_record = WeatherRecord.objects.first()

    if not batch:
        logger.warning("[Benchmark] No FishBatch found — using minimal test data")

    # ── 1. ML Prediction benchmark ────────────────────────────────────────────
    if batch:
        logger.info(f"[Benchmark] Running ML prediction × {n_iterations}")
        for i in range(n_iterations):
            result = benchmark_ml_prediction(batch)
            result.extra["iteration"] = i + 1
            all_results.append(result)

    # ── 2. Feed Calculation benchmark ─────────────────────────────────────────
    if batch:
        logger.info(f"[Benchmark] Running feed calculation × {n_iterations}")
        for i in range(n_iterations):
            result = benchmark_feed_calculation(batch)
            result.extra["iteration"] = i + 1
            all_results.append(result)

    # ── 3. Alert Generation benchmark ────────────────────────────────────────
    if weather_record:
        logger.info(f"[Benchmark] Running alert generation × {n_iterations}")
        for i in range(n_iterations):
            result = benchmark_alert_generation(weather_record)
            result.extra["iteration"] = i + 1
            all_results.append(result)

    # ── 4. Database query benchmark ───────────────────────────────────────────
    logger.info(f"[Benchmark] Running DB query benchmark × {n_iterations}")
    for i in range(n_iterations):
        result = _benchmark_db_queries()
        result.extra["iteration"] = i + 1
        all_results.append(result)

    # ── 5. API response benchmark ─────────────────────────────────────────────
    logger.info(f"[Benchmark] Running API benchmark × {n_iterations}")
    for i in range(n_iterations):
        result = _benchmark_api_serialization(batch)
        result.extra["iteration"] = i + 1
        all_results.append(result)

    finished_at = datetime.now().isoformat()

    suite = BenchmarkSuite(
        suite_name="AquaSmart Full Performance Benchmark",
        started_at=started_at,
        finished_at=finished_at,
        results=all_results,
        system_info=system_info,
    )

    # Save aggregated results to DB
    _save_benchmark_suite(suite)

    return suite


def _benchmark_db_queries() -> BenchmarkResult:
    """Benchmark typical DB query patterns."""
    from ..models import FishBatch, GrowthRecord, FeedLog, WeatherRecord

    mem_before = _get_memory_mb()
    start      = time.perf_counter()
    db_count   = 0

    try:
        # Simulate typical dashboard queries
        batches = list(
            FishBatch.objects
            .select_related("pond")
            .prefetch_related("growth_records", "feed_logs")
            .all()[:20]
        )
        db_count += 1

        for b in batches:
            _ = b.latest_biomass_kg
            db_count += 1

        WeatherRecord.objects.order_by("-timestamp")[:14]
        db_count += 1

        GrowthRecord.objects.order_by("-date")[:50]
        db_count += 1

        FeedLog.objects.order_by("-date")[:14]
        db_count += 1

        success = True
        error   = None
    except Exception as exc:
        success = False
        error   = str(exc)

    elapsed_ms = round((time.perf_counter() - start) * 1000, 3)
    mem_after  = _get_memory_mb()

    return BenchmarkResult(
        operation="db_queries",
        elapsed_ms=elapsed_ms,
        memory_before_mb=round(mem_before, 2),
        memory_after_mb=round(mem_after, 2),
        memory_delta_mb=round(mem_after - mem_before, 2),
        cpu_percent=round(_get_cpu_percent(), 2),
        db_query_count=db_count,
        db_query_time_ms=elapsed_ms,
        timestamp=datetime.now().isoformat(),
        success=success,
        error=error,
        extra={"query_count": db_count},
    )


def _benchmark_api_serialization(batch) -> BenchmarkResult:
    """Benchmark DRF serializer performance."""
    mem_before = _get_memory_mb()
    start      = time.perf_counter()

    try:
        from ..serializers import FishBatchSerializer, GrowthRecordSerializer
        from ..models import FishBatch, GrowthRecord

        batches = FishBatch.objects.select_related("pond").all()[:10]
        data    = FishBatchSerializer(batches, many=True).data

        records = GrowthRecord.objects.order_by("-date")[:20]
        data2   = GrowthRecordSerializer(records, many=True).data

        success = True
        error   = None
        extra   = {
            "batches_serialized": len(data),
            "records_serialized": len(data2),
        }
    except Exception as exc:
        success = False
        error   = str(exc)
        extra   = {}

    elapsed_ms = round((time.perf_counter() - start) * 1000, 3)
    mem_after  = _get_memory_mb()

    return BenchmarkResult(
        operation="api_serialization",
        elapsed_ms=elapsed_ms,
        memory_before_mb=round(mem_before, 2),
        memory_after_mb=round(mem_after, 2),
        memory_delta_mb=round(mem_after - mem_before, 2),
        cpu_percent=round(_get_cpu_percent(), 2),
        db_query_count=2,
        db_query_time_ms=0.0,
        timestamp=datetime.now().isoformat(),
        success=success,
        error=error,
        extra=extra,
    )


def _save_benchmark_suite(suite: BenchmarkSuite):
    """Save full benchmark suite results to DB."""
    try:
        from ..models import BenchmarkRun
        import json

        by_operation: dict[str, list[float]] = {}
        for r in suite.results:
            by_operation.setdefault(r.operation, []).append(r.elapsed_ms)

        aggregated = {}
        for op, times in by_operation.items():
            aggregated[op] = {
                "count":      len(times),
                "avg_ms":     round(statistics.mean(times), 2),
                "min_ms":     round(min(times), 2),
                "max_ms":     round(max(times), 2),
                "median_ms":  round(statistics.median(times), 2),
                "p95_ms":     round(_percentile(times, 95), 2),
                "std_dev":    round(statistics.stdev(times) if len(times) > 1 else 0, 2),
            }

        BenchmarkRun.objects.create(
            suite_name=suite.suite_name,
            started_at=suite.started_at,
            finished_at=suite.finished_at,
            total_operations=len(suite.results),
            aggregated_results=aggregated,
            system_info=suite.system_info,
            summary=suite.summary,
        )
    except Exception as e:
        logger.warning(f"[Benchmark] Failed to save suite: {e}")


# ── Statistics helper for paper tables ───────────────────────────────────────

def get_benchmark_stats_for_paper() -> dict[str, Any]:
    """
    Compute statistics from all stored PerformanceLog records.
    Use this to generate Table data for the research paper.

    Returns a dict ready for the benchmark dashboard template.
    """
    try:
        from ..models import PerformanceLog, BenchmarkRun
        from django.db.models import Avg, Min, Max, Count, StdDev

        logs = PerformanceLog.objects.all()

        if not logs.exists():
            return {"no_data": True}

        # Per-endpoint stats
        endpoint_stats = (
            logs.values("endpoint")
            .annotate(
                count=Count("id"),
                avg_ms=Avg("elapsed_ms"),
                min_ms=Min("elapsed_ms"),
                max_ms=Max("elapsed_ms"),
                avg_db_queries=Avg("db_query_count"),
                avg_memory_delta=Avg("memory_after_mb"),
            )
            .order_by("-avg_ms")
        )

        # Latest benchmark runs
        recent_runs = BenchmarkRun.objects.order_by("-created_at")[:5]

        # Overall system stats
        all_times = list(logs.values_list("elapsed_ms", flat=True))
        overall = {
            "total_requests_logged": len(all_times),
            "overall_avg_ms":   round(statistics.mean(all_times), 2) if all_times else 0,
            "overall_p95_ms":   round(_percentile(all_times, 95), 2) if all_times else 0,
            "overall_p99_ms":   round(_percentile(all_times, 99), 2) if all_times else 0,
        }

        return {
            "no_data":       False,
            "endpoint_stats": list(endpoint_stats),
            "recent_runs":   recent_runs,
            "overall":       overall,
            "system_info":   _get_system_info(),
        }

    except Exception as e:
        logger.error(f"[Benchmark] Stats error: {e}")
        return {"no_data": True, "error": str(e)}