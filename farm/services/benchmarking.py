"""
─────────────────────────────────────────────────────────────────────────────
Performance Benchmarking Service for AquaSmart (Ultimate Merged Version)
================================================

Metrics collected:
  1. Response Time     — view execution time (ms)
  2. Database Queries  — count + total query time per request
  3. Memory Usage      — RSS memory before/after operations (MB)
  4. CPU Usage         — process CPU % during operations (via background thread)
  5. ML Prediction Time — time taken for ML inference (ms)
  6. Feed Calculation Time — time for smart feed calculation (ms)
  7. Alert Generation Time — time for water alert checks (ms)
  8. API Throughput    — requests per second (simulated)
"""

from __future__ import annotations

import functools
import gc
import logging
import platform
import statistics
import threading
import time
from dataclasses import dataclass, field, asdict
from datetime import datetime
from typing import Any, Callable, Optional

import psutil

logger = logging.getLogger(__name__)


# ── Data Classes ──────────────────────────────────────────────────────────────

@dataclass
class BenchmarkResult:
    """Single benchmark measurement result."""
    operation:        str
    elapsed_ms:       float
    memory_before_mb: float
    memory_after_mb:  float
    memory_delta_mb:  float
    cpu_percent:      float
    db_query_count:   int
    db_query_time_ms: float
    timestamp:        str
    success:          bool
    error:            Optional[str] = None
    extra:            dict = field(default_factory=dict)

    def to_dict(self) -> dict:
        return asdict(self)


@dataclass
class BenchmarkSuite:
    """Collection of benchmark results for a full test run."""
    suite_name:  str
    started_at:  str
    finished_at: str
    results:     list[BenchmarkResult]
    system_info: dict

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
    """Calculate percentile using standard linear interpolation."""
    if not data:
        return 0.0
    if len(data) == 1:
        return data[0]
    sorted_data = sorted(data)
    n = len(sorted_data)
    k = (pct / 100.0) * (n - 1)
    f = int(k)
    c = f + 1
    if c >= n:
        return sorted_data[-1]
    d = k - f
    return sorted_data[f] + d * (sorted_data[c] - sorted_data[f])


def _remove_outliers_iqr(data: list[float]) -> list[float]:
    """Remove statistical outliers using IQR method for paper accuracy."""
    if len(data) < 4:
        return data
    q1, _q2, q3 = statistics.quantiles(data, n=4)
    iqr = q3 - q1
    lower = q1 - 1.5 * iqr
    upper = q3 + 1.5 * iqr
    return [x for x in data if lower <= x <= upper]


def _get_memory_mb() -> float:
    """Current process RSS memory in MB."""
    try:
        return psutil.Process().memory_info().rss / (1024 * 1024)
    except Exception:
        return 0.0


def _get_system_info() -> dict:
    """Collect dynamic system info for paper's experimental setup section."""
    try:
        proc = psutil.Process()
        vm   = psutil.virtual_memory()
        return {
            "cpu_cores_logical":  psutil.cpu_count(logical=True),
            "cpu_cores_physical": psutil.cpu_count(logical=False),
            "cpu_freq_mhz":       round(psutil.cpu_freq().current, 0) if psutil.cpu_freq() else None,
            "total_ram_gb":       round(vm.total / (1024 ** 3), 2),
            "available_ram_gb":   round(vm.available / (1024 ** 3), 2),
            "ram_usage_pct":      vm.percent,
            "python_process_mb":  round(proc.memory_info().rss / (1024 * 1024), 2),
            "platform":           f"{platform.system()} ({platform.release()})",
            "python_version":     platform.python_version(),
            "benchmark_at":       datetime.now().isoformat(),
        }
    except Exception:
        return {}


def _capture_db_stats() -> tuple[int, float]:
    """Safely capture actual DB query count and total time from Django connection."""
    try:
        from django.db import connection
        queries = connection.queries
        db_count = len(queries)
        # Safely handle missing or None time values
        db_time_ms = round(sum(float(q.get("time") or 0) for q in queries) * 1000, 3)
        return db_count, db_time_ms
    except Exception:
        return 0, 0.0


# ── CPU Monitor (Background Thread) ──────────────────────────────────────────

class _CPUMonitor:
    """
    Background thread that samples CPU usage during operation.
    Avoids the 100ms blocking delay of psutil.cpu_percent(interval=x).
    """
    def __init__(self, interval: float = 0.01):
        self.interval = interval
        self._cpu_values: list[float] = []
        self._running = False
        self._thread: Optional[threading.Thread] = None

    def _sample_loop(self):
        proc = psutil.Process()
        proc.cpu_percent(interval=None)  # Initialize counter
        while self._running:
            try:
                self._cpu_values.append(proc.cpu_percent(interval=self.interval))
            except Exception:
                break

    def start(self):
        self._running = True
        self._cpu_values = []
        self._thread = threading.Thread(target=self._sample_loop, daemon=True)
        self._thread.start()
        time.sleep(self.interval * 2)  # Let first sample complete

    def stop(self) -> float:
        self._running = False
        if self._thread:
            self._thread.join(timeout=0.2)
        return round(max(self._cpu_values), 2) if self._cpu_values else 0.0


# ── Core Timer Context Manager ────────────────────────────────────────────────

class BenchmarkTimer:
    """Context manager for timing any code block with GC-aware memory delta."""
    def __init__(self, operation: str, monitor_cpu: bool = False):
        self.operation     = operation
        self.elapsed_ms    = 0.0
        self.memory_before = 0.0
        self.memory_after  = 0.0
        self.memory_delta  = 0.0
        self.cpu_percent   = 0.0
        self._start        = 0.0
        self._monitor_cpu  = monitor_cpu
        self._cpu_monitor: Optional[_CPUMonitor] = None

    def __enter__(self):
        gc.collect()  # Clean before measurement
        self.memory_before = _get_memory_mb()
        if self._monitor_cpu:
            self._cpu_monitor = _CPUMonitor(interval=0.01)
            self._cpu_monitor.start()
        self._start = time.perf_counter()
        return self

    def __exit__(self, *args):
        self.elapsed_ms = round((time.perf_counter() - self._start) * 1000, 3)
        if self._cpu_monitor:
            self.cpu_percent = self._cpu_monitor.stop()
        gc.collect()  # Force GC after to measure true deallocation
        self.memory_after = _get_memory_mb()
        self.memory_delta = round(self.memory_after - self.memory_before, 3)


# ── View Decorator ────────────────────────────────────────────────────────────

def benchmark_view(view_func: Callable) -> Callable:
    """
    Thread-safe decorator that measures view performance.
    Uses connection.force_debug_cursor instead of global DEBUG flag.
    """
    @functools.wraps(view_func)
    def wrapper(request, *args, **kwargs):
        from django.db import connection

        # Thread-safe query logging (no global state mutation)
        cursor_was_debug = getattr(connection, 'force_debug_cursor', False)
        connection.force_debug_cursor = True
        connection.queries_log.clear() if hasattr(connection, 'queries_log') else None

        mem_before = _get_memory_mb()
        start_time = time.perf_counter()

        try:
            response = view_func(request, *args, **kwargs)
            success  = True
            error    = None
        except Exception as exc:
            success  = False
            error    = str(exc)[:500]  # Truncate to prevent DB bloat
            raise
        finally:
            elapsed_ms = round((time.perf_counter() - start_time) * 1000, 3)
            
            # Restore state safely
            connection.force_debug_cursor = cursor_was_debug
            db_count, db_time_ms = _capture_db_stats()
            mem_after = _get_memory_mb()

            try:
                _save_performance_log(
                    endpoint=view_func.__name__,
                    method=request.method,
                    elapsed_ms=elapsed_ms,
                    memory_before_mb=round(mem_before, 2),
                    memory_after_mb=round(mem_after, 2),
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
    try:
        from ..models import PerformanceLog
        PerformanceLog.objects.create(**kwargs)
    except Exception as e:
        logger.debug(f"[Benchmark] DB save skipped: {e}")


# ── Operation Benchmarkers ────────────────────────────────────────────────────

def benchmark_ml_prediction(batch) -> BenchmarkResult:
    """Benchmark ML prediction for a single batch."""
    from .ml_prediction import ml_predict_batch_growth

    gc.collect()
    mem_before = _get_memory_mb()
    cpu_monitor = _CPUMonitor(interval=0.01)
    cpu_monitor.start()
    start = time.perf_counter()

    try:
        result = ml_predict_batch_growth(batch)
        success = True
        error = None
        extra = {
            "model_used": result.get("model_used", "") if isinstance(result, dict) else "",
            "r2_score": result.get("r2_score", 0) if isinstance(result, dict) else 0,
            "training_samples": result.get("training_samples_real", 0) if isinstance(result, dict) else 0,
        }
    except Exception as exc:
        success = False
        error = str(exc)[:500]
        extra = {}

    elapsed_ms = round((time.perf_counter() - start) * 1000, 3)
    cpu_percent = cpu_monitor.stop()
    gc.collect()
    mem_after = _get_memory_mb()

    return BenchmarkResult(
        operation="ml_prediction", elapsed_ms=elapsed_ms,
        memory_before_mb=round(mem_before, 2), memory_after_mb=round(mem_after, 2),
        memory_delta_mb=round(mem_after - mem_before, 2), cpu_percent=cpu_percent,
        db_query_count=0, db_query_time_ms=0.0,
        timestamp=datetime.now().isoformat(), success=success, error=error, extra=extra,
    )


def benchmark_feed_calculation(batch) -> BenchmarkResult:
    """Benchmark smart feed calculation."""
    from .feed_calculator import smart_feed_kg_for_batch

    gc.collect()
    mem_before = _get_memory_mb()
    cpu_monitor = _CPUMonitor(interval=0.01)
    cpu_monitor.start()
    start = time.perf_counter()

    try:
        result = smart_feed_kg_for_batch(batch)
        success = True
        error = None
        extra = {"feed_kg": float(result) if result is not None else 0}
    except Exception as exc:
        success = False
        error = str(exc)[:500]
        extra = {}

    elapsed_ms = round((time.perf_counter() - start) * 1000, 3)
    cpu_percent = cpu_monitor.stop()
    gc.collect()
    mem_after = _get_memory_mb()

    return BenchmarkResult(
        operation="feed_calculation", elapsed_ms=elapsed_ms,
        memory_before_mb=round(mem_before, 2), memory_after_mb=round(mem_after, 2),
        memory_delta_mb=round(mem_after - mem_before, 2), cpu_percent=cpu_percent,
        db_query_count=0, db_query_time_ms=0.0,
        timestamp=datetime.now().isoformat(), success=success, error=error, extra=extra,
    )


def benchmark_alert_generation(weather_record) -> BenchmarkResult:
    """Benchmark water quality alert generation."""
    from .generate_water_alerts import generate_water_alerts

    gc.collect()
    mem_before = _get_memory_mb()
    cpu_monitor = _CPUMonitor(interval=0.01)
    cpu_monitor.start()
    start = time.perf_counter()

    try:
        generate_water_alerts(weather_record)
        success = True
        error = None
    except Exception as exc:
        success = False
        error = str(exc)[:500]

    elapsed_ms = round((time.perf_counter() - start) * 1000, 3)
    cpu_percent = cpu_monitor.stop()
    gc.collect()
    mem_after = _get_memory_mb()

    return BenchmarkResult(
        operation="alert_generation", elapsed_ms=elapsed_ms,
        memory_before_mb=round(mem_before, 2), memory_after_mb=round(mem_after, 2),
        memory_delta_mb=round(mem_after - mem_before, 2), cpu_percent=cpu_percent,
        db_query_count=0, db_query_time_ms=0.0,
        timestamp=datetime.now().isoformat(), success=success, error=error, extra={},
    )


# ── Full Benchmark Suite ──────────────────────────────────────────────────────

def run_full_benchmark(n_iterations: int = 10, warmup: int = 2) -> BenchmarkSuite:
    """
    Run complete benchmark suite. Includes warm-up phase to eliminate cold-start.
    """
    from ..models import FishBatch, WeatherRecord

    started_at = datetime.now().isoformat()
    all_results: list[BenchmarkResult] = []
    system_info = _get_system_info()

    batch = FishBatch.objects.select_related("pond").first()
    weather_record = WeatherRecord.objects.first()

    if not batch:
        logger.warning("[Benchmark] No FishBatch found")

    # 1. ML Prediction
    if batch:
        logger.info(f"[Benchmark] ML prediction: {warmup} warmup + {n_iterations} measured")
        for _ in range(warmup): benchmark_ml_prediction(batch)
        for i in range(n_iterations):
            r = benchmark_ml_prediction(batch); r.extra["iteration"] = i + 1; all_results.append(r)

    # 2. Feed Calculation
    if batch:
        logger.info(f"[Benchmark] Feed calculation: {warmup} warmup + {n_iterations} measured")
        for _ in range(warmup): benchmark_feed_calculation(batch)
        for i in range(n_iterations):
            r = benchmark_feed_calculation(batch); r.extra["iteration"] = i + 1; all_results.append(r)

    # 3. Alert Generation
    if weather_record:
        logger.info(f"[Benchmark] Alert generation: {warmup} warmup + {n_iterations} measured")
        for _ in range(warmup): benchmark_alert_generation(weather_record)
        for i in range(n_iterations):
            r = benchmark_alert_generation(weather_record); r.extra["iteration"] = i + 1; all_results.append(r)

    # 4. DB Queries
    logger.info(f"[Benchmark] DB queries: {warmup} warmup + {n_iterations} measured")
    for _ in range(warmup): _benchmark_db_queries()
    for i in range(n_iterations):
        r = _benchmark_db_queries(); r.extra["iteration"] = i + 1; all_results.append(r)

    # 5. API Serialization
    logger.info(f"[Benchmark] API serialization: {warmup} warmup + {n_iterations} measured")
    for _ in range(warmup): _benchmark_api_serialization(batch)
    for i in range(n_iterations):
        r = _benchmark_api_serialization(batch); r.extra["iteration"] = i + 1; all_results.append(r)

    finished_at = datetime.now().isoformat()
    suite = BenchmarkSuite(
        suite_name="AquaSmart Full Performance Benchmark",
        started_at=started_at, finished_at=finished_at,
        results=all_results, system_info=system_info,
    )
    _save_benchmark_suite(suite)
    return suite


def _benchmark_db_queries() -> BenchmarkResult:
    """Benchmark typical DB query patterns with forced evaluation."""
    from ..models import FishBatch, GrowthRecord, FeedLog, WeatherRecord
    from django.db import connection

    # Enable query logging for this specific connection
    cursor_was = getattr(connection, 'force_debug_cursor', False)
    connection.force_debug_cursor = True
    connection.queries_log.clear() if hasattr(connection, 'queries_log') else None

    gc.collect()
    mem_before = _get_memory_mb()
    cpu_monitor = _CPUMonitor(interval=0.01)
    cpu_monitor.start()
    start = time.perf_counter()

    try:
        # Use list() to force query evaluation and prevent lazy loading bugs
        batches = list(FishBatch.objects.select_related("pond").prefetch_related("growth_records", "feed_logs").all()[:20])
        for b in batches:
            _ = b.latest_biomass_kg
            
        list(WeatherRecord.objects.order_by("-timestamp")[:14])
        list(GrowthRecord.objects.order_by("-date")[:50])
        list(FeedLog.objects.order_by("-date")[:14])
        success, error = True, None
    except Exception as exc:
        success, error = False, str(exc)[:500]

    elapsed_ms = round((time.perf_counter() - start) * 1000, 3)
    cpu_percent = cpu_monitor.stop()
    
    # Capture stats BEFORE restoring state
    db_count, db_time_ms = _capture_db_stats()
    
    connection.force_debug_cursor = cursor_was
    gc.collect()
    mem_after = _get_memory_mb()

    return BenchmarkResult(
        operation="db_queries", elapsed_ms=elapsed_ms,
        memory_before_mb=round(mem_before, 2), memory_after_mb=round(mem_after, 2),
        memory_delta_mb=round(mem_after - mem_before, 2), cpu_percent=cpu_percent,
        db_query_count=db_count, db_query_time_ms=db_time_ms,
        timestamp=datetime.now().isoformat(), success=success, error=error,
        extra={"query_count": db_count},
    )


def _benchmark_api_serialization(batch) -> BenchmarkResult:
    """Benchmark DRF serializer performance with forced evaluation."""
    from django.db import connection

    cursor_was = getattr(connection, 'force_debug_cursor', False)
    connection.force_debug_cursor = True
    connection.queries_log.clear() if hasattr(connection, 'queries_log') else None

    gc.collect()
    mem_before = _get_memory_mb()
    cpu_monitor = _CPUMonitor(interval=0.01)
    cpu_monitor.start()
    start = time.perf_counter()
    extra = {}

    try:
        from ..serializers import FishBatchSerializer, GrowthRecordSerializer
        from ..models import FishBatch, GrowthRecord

        batches = list(FishBatch.objects.select_related("pond").all()[:10])
        data1 = FishBatchSerializer(batches, many=True).data

        records = list(GrowthRecord.objects.order_by("-date")[:20])
        data2 = GrowthRecordSerializer(records, many=True).data

        success, error = True, None
        extra = {"batches_serialized": len(data1), "records_serialized": len(data2)}
    except Exception as exc:
        success, error = False, str(exc)[:500]

    elapsed_ms = round((time.perf_counter() - start) * 1000, 3)
    cpu_percent = cpu_monitor.stop()
    
    db_count, db_time_ms = _capture_db_stats()
    
    connection.force_debug_cursor = cursor_was
    gc.collect()
    mem_after = _get_memory_mb()

    return BenchmarkResult(
        operation="api_serialization", elapsed_ms=elapsed_ms,
        memory_before_mb=round(mem_before, 2), memory_after_mb=round(mem_after, 2),
        memory_delta_mb=round(mem_after - mem_before, 2), cpu_percent=cpu_percent,
        db_query_count=db_count, db_query_time_ms=db_time_ms,
        timestamp=datetime.now().isoformat(), success=success, error=error, extra=extra,
    )


def _save_benchmark_suite(suite: BenchmarkSuite):
    """Save full benchmark suite results with outlier-aware statistics."""
    try:
        from ..models import BenchmarkRun

        by_operation: dict[str, list[float]] = {}
        for r in suite.results:
            by_operation.setdefault(r.operation, []).append(r.elapsed_ms)

        aggregated = {}
        for op, times in by_operation.items():
            times_clean = _remove_outliers_iqr(times)
            aggregated[op] = {
                "count": len(times),
                "avg_ms": round(statistics.mean(times), 2),
                "min_ms": round(min(times), 2),
                "max_ms": round(max(times), 2),
                "median_ms": round(statistics.median(times), 2),
                "p95_ms": round(_percentile(times, 95), 2),
                "p99_ms": round(_percentile(times, 99), 2),
                "std_dev": round(statistics.stdev(times) if len(times) > 1 else 0, 2),
                # Clean stats (outliers removed)
                "avg_ms_clean": round(statistics.mean(times_clean), 2) if times_clean else 0,
                "std_dev_clean": round(statistics.stdev(times_clean) if len(times_clean) > 1 else 0, 2),
                "outliers_removed": len(times) - len(times_clean),
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


# ── Statistics Helper for Paper Tables ───────────────────────────────────────

def get_benchmark_stats_for_paper() -> dict[str, Any]:
    """Compute statistics for the research paper using DB-level accurate math."""
    try:
        from ..models import PerformanceLog, BenchmarkRun
        from django.db.models import Avg, Min, Max, Count, F

        logs = PerformanceLog.objects.all()
        if not logs.exists():
            return {"no_data": True}

        # Per-endpoint stats (using F() for true DB-level delta calculation)
        endpoint_stats = (
            logs.values("endpoint")
            .annotate(
                count=Count("id"),
                avg_ms=Avg("elapsed_ms"),
                min_ms=Min("elapsed_ms"),
                max_ms=Max("elapsed_ms"),
                avg_db_queries=Avg("db_query_count"),
                avg_memory_delta=Avg(F("memory_after_mb") - F("memory_before_mb")),
            )
            .order_by("-avg_ms")
        )

        recent_runs = BenchmarkRun.objects.order_by("-created_at")[:5]
        
        all_times = list(logs.values_list("elapsed_ms", flat=True))
        all_times_clean = _remove_outliers_iqr(all_times)
        
        overall = {
            "total_requests_logged": len(all_times),
            "overall_avg_ms": round(statistics.mean(all_times), 2) if all_times else 0,
            "overall_avg_ms_clean": round(statistics.mean(all_times_clean), 2) if all_times_clean else 0,
            "overall_p95_ms": round(_percentile(all_times, 95), 2) if all_times else 0,
            "overall_p99_ms": round(_percentile(all_times, 99), 2) if all_times else 0,
            "outliers_count": len(all_times) - len(all_times_clean),
        }

        return {
            "no_data": False,
            "endpoint_stats": list(endpoint_stats),
            "recent_runs": recent_runs,
            "overall": overall,
            "system_info": _get_system_info(),
        }

    except Exception as e:
        logger.error(f"[Benchmark] Stats error: {e}")
        return {"no_data": True, "error": str(e)}