
"""
metrics.py
----------

Thread-safe in-memory metrics collector for Agent 6.
"""

from __future__ import annotations

from threading import RLock
from typing import List

from models import ExecutionMetrics, ExecutionResult


class MetricsService:

    def __init__(self):
        self._metrics = ExecutionMetrics()
        self._latencies: List[float] = []
        self._lock = RLock()

    def record(self, result: ExecutionResult) -> None:
        with self._lock:
            self._metrics.executed += 1

            if result.success:
                self._metrics.successful += 1
            else:
                self._metrics.failures += 1

            if result.cached:
                self._metrics.cache_hits += 1

            retries = sum(a.retries for a in result.action_results)
            self._metrics.retries += retries

            self._latencies.append(result.latency_ms)
            self._latencies.sort()

            self._metrics.average_latency_ms = (
                sum(self._latencies) / len(self._latencies)
            )

            self._metrics.p95_latency_ms = self._percentile(95)
            self._metrics.p99_latency_ms = self._percentile(99)

    def increment_locked_cards(self, count: int = 1):
        with self._lock:
            self._metrics.locked_cards += count

    def snapshot(self) -> ExecutionMetrics:
        with self._lock:
            return ExecutionMetrics(
                executed=self._metrics.executed,
                successful=self._metrics.successful,
                failures=self._metrics.failures,
                cache_hits=self._metrics.cache_hits,
                retries=self._metrics.retries,
                locked_cards=self._metrics.locked_cards,
                average_latency_ms=round(
                    self._metrics.average_latency_ms, 2
                ),
                p95_latency_ms=round(
                    self._metrics.p95_latency_ms, 2
                ),
                p99_latency_ms=round(
                    self._metrics.p99_latency_ms, 2
                ),
            )

    def reset(self):
        with self._lock:
            self._metrics = ExecutionMetrics()
            self._latencies.clear()

    def _percentile(self, percentile: int) -> float:
        if not self._latencies:
            return 0.0

        index = int(
            (percentile / 100) * (len(self._latencies) - 1)
        )
        return self._latencies[index]


metrics_service = MetricsService()
