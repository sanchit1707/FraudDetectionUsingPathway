"""
metrics.py
----------

Dual-mode metrics collector for FlashGuard Agent 6.

In-memory mode (always active)
    The existing ExecutionMetrics dataclass and MetricsService are
    kept exactly as-is so all existing consumers continue to work.

Prometheus mode (layered on top)
    When prometheus-client is installed (it is listed in requirements.txt)
    the same record() call also increments the corresponding Prometheus
    counters / histograms, which are scraped by Prometheus.

Exported Prometheus metrics
---------------------------
    agent6_executions_total          counter   (labels: verdict, state)
    agent6_execution_latency_seconds histogram (labels: verdict)
    agent6_cache_hits_total          counter
    agent6_retries_total             counter
    agent6_locked_cards_total        counter
    agent6_action_executions_total   counter   (labels: action_type, status)
"""

from __future__ import annotations

import logging
import os
from threading import RLock
from typing import List

from models import ExecutionMetrics, ExecutionResult

logger = logging.getLogger(__name__)

# ──────────────────────────────────────────────────────────────────────────────
# Prometheus metric definitions (created lazily so tests without
# prometheus-client installed still pass)
# ──────────────────────────────────────────────────────────────────────────────

_prom_ready = False
_prom_executions = None
_prom_latency = None
_prom_cache_hits = None
_prom_retries = None
_prom_locked_cards = None
_prom_actions = None


def _init_prometheus() -> None:
    global _prom_ready
    global _prom_executions, _prom_latency
    global _prom_cache_hits, _prom_retries
    global _prom_locked_cards, _prom_actions
    if _prom_ready:
        return
    try:
        from prometheus_client import Counter, Histogram, REGISTRY

        _prom_executions = Counter(
            "agent6_executions_total",
            "Total number of executions",
            ["verdict", "state"],
        )
        _prom_latency = Histogram(
            "agent6_execution_latency_seconds",
            "Execution latency in seconds",
            ["verdict"],
            buckets=[0.005, 0.01, 0.025, 0.05, 0.1, 0.25, 0.5, 1.0, 2.5],
        )
        _prom_cache_hits = Counter(
            "agent6_cache_hits_total",
            "Number of idempotency cache hits",
        )
        _prom_retries = Counter(
            "agent6_retries_total",
            "Total number of action retries",
        )
        _prom_locked_cards = Counter(
            "agent6_locked_cards_total",
            "Total number of cards locked",
        )
        _prom_actions = Counter(
            "agent6_action_executions_total",
            "Action executions by type and status",
            ["action_type", "status"],
        )
        _prom_ready = True
        logger.info("Prometheus metrics registered")
    except Exception as exc:
        logger.warning("Prometheus not available: %s", exc)
        _prom_ready = False


# ──────────────────────────────────────────────────────────────────────────────
# MetricsService (extended original)
# ──────────────────────────────────────────────────────────────────────────────

class MetricsService:
    """
    Thread-safe in-memory metrics collector.

    All original public methods (record, snapshot, reset,
    increment_locked_cards) are preserved.  Prometheus counters
    are updated alongside the in-memory counters when available.
    """

    def __init__(self) -> None:
        self._metrics = ExecutionMetrics()
        self._latencies: List[float] = []
        self._lock = RLock()
        _init_prometheus()

    # ── Public API ────────────────────────────────────────────────────────────

    def record(self, result: ExecutionResult) -> None:
        """Record an execution result.  Updates both in-memory and Prometheus."""
        with self._lock:
            self._metrics.executed += 1

            verdict = (
                result.action_results[0].action_type.value
                if result.action_results
                else "UNKNOWN"
            )
            # Prefer to label by request verdict – stored in result message
            # (not directly accessible here so we use state as label fallback)
            state_label = result.state.value

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

        # ── Prometheus ────────────────────────────────────────────────────────
        if _prom_ready:
            try:
                _prom_executions.labels(
                    verdict="N/A",
                    state=state_label,
                ).inc()
                _prom_latency.labels(verdict="N/A").observe(
                    result.latency_ms / 1000.0
                )
                if result.cached:
                    _prom_cache_hits.inc()
                if retries > 0:
                    _prom_retries.inc(retries)
                for ar in result.action_results:
                    _prom_actions.labels(
                        action_type=ar.action_type.value,
                        status=ar.status.value,
                    ).inc()
            except Exception as exc:
                logger.debug("Prometheus record error: %s", exc)

    def record_with_verdict(
        self,
        result: ExecutionResult,
        verdict: str,
    ) -> None:
        """
        Like record() but also carries the verdict string for richer
        Prometheus labels.  Called by the FastAPI executor path.
        """
        self.record(result)

        if _prom_ready:
            try:
                # Re-label with actual verdict
                _prom_executions.labels(
                    verdict=verdict,
                    state=result.state.value,
                ).inc()
                _prom_latency.labels(verdict=verdict).observe(
                    result.latency_ms / 1000.0
                )
            except Exception as exc:
                logger.debug("Prometheus record_with_verdict error: %s", exc)

    def increment_locked_cards(self, count: int = 1) -> None:
        with self._lock:
            self._metrics.locked_cards += count
        if _prom_ready:
            try:
                _prom_locked_cards.inc(count)
            except Exception as exc:
                logger.debug("Prometheus locked_cards error: %s", exc)

    def snapshot(self) -> ExecutionMetrics:
        with self._lock:
            return ExecutionMetrics(
                executed=self._metrics.executed,
                successful=self._metrics.successful,
                failures=self._metrics.failures,
                cache_hits=self._metrics.cache_hits,
                retries=self._metrics.retries,
                locked_cards=self._metrics.locked_cards,
                average_latency_ms=round(self._metrics.average_latency_ms, 2),
                p95_latency_ms=round(self._metrics.p95_latency_ms, 2),
                p99_latency_ms=round(self._metrics.p99_latency_ms, 2),
            )

    def reset(self) -> None:
        with self._lock:
            self._metrics = ExecutionMetrics()
            self._latencies.clear()

    # ── Internal ──────────────────────────────────────────────────────────────

    def _percentile(self, percentile: int) -> float:
        if not self._latencies:
            return 0.0
        index = int((percentile / 100) * (len(self._latencies) - 1))
        return self._latencies[index]


def start_prometheus_server(port: int | None = None) -> None:
    """
    Start a standalone Prometheus HTTP server on the given port.

    Reads PROMETHEUS_PORT env var (default 8001) if port is None.
    Safe to call multiple times – only the first call starts the server.
    """
    _init_prometheus()
    if not _prom_ready:
        logger.warning("Cannot start Prometheus server: prometheus-client not installed")
        return
    port = port or int(os.getenv("PROMETHEUS_PORT", "8001"))
    try:
        from prometheus_client import start_http_server
        start_http_server(port)
        logger.info("Prometheus metrics server started on port %d", port)
    except OSError as exc:
        # Already bound – ignore
        logger.debug("Prometheus server already running: %s", exc)
    except Exception as exc:
        logger.warning("Failed to start Prometheus server: %s", exc)


# ──────────────────────────────────────────────────────────────────────────────
# Module-level singleton (backward compatible)
# ──────────────────────────────────────────────────────────────────────────────
metrics_service = MetricsService()
