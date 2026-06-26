"""
container.py
------------

Dependency Injection Container for Agent 6.

Upgraded with:
- async init() / shutdown() methods for FastAPI lifespan
- Wires Redis idempotency, PostgreSQL audit, Kafka event bus
- All sync singletons preserved for CLI / test compatibility
"""

from __future__ import annotations

import logging
import os

from validator import RequestValidator
from idempotency import (
    IdempotencyStore,
    IdempotencyService,
    build_idempotency_service,
)
from distributed_lock import (
    InMemoryLockStore,
    DistributedLockService,
)
from policy_engine import (
    PolicyRegistry,
    PolicyEngine,
    BlockPolicy,
    FlagPolicy,
    ReviewPolicy,
    AllowPolicy,
)
from planner import ExecutionPlanner
from retry import RetryManager
from circuit_breaker import CircuitRegistry
from action_runner import ActionRunner
from audit import AuditService, build_audit_service
from event_bus import InMemoryEventBus, build_event_bus
from metrics import MetricsService, start_prometheus_server
from executor import Executor
from models import Verdict
from tracing import init_tracing, shutdown_tracing

logger = logging.getLogger(__name__)


class Container:
    """
    Central dependency registry.

    Synchronous services (validator, lock, planner, retry, circuit breaker,
    action runner, executor) are created eagerly in __init__ so the CLI and
    unit tests work without calling init().

    Async adapters (Redis idempotency, PostgreSQL audit, Kafka event bus)
    are created and connected in init() which is called by the FastAPI
    lifespan context manager.
    """

    def __init__(self) -> None:

        # ── Core (sync, always available) ─────────────────────────────────────
        self.validator = RequestValidator()

        self.idempotency_store = IdempotencyStore()
        self.idempotency = IdempotencyService(self.idempotency_store)

        self.lock_store = InMemoryLockStore()
        self.distributed_lock = DistributedLockService(self.lock_store)

        self.planner = ExecutionPlanner()
        self.retry = RetryManager()
        self.circuit_registry = CircuitRegistry()

        # ── In-memory fallback services ────────────────────────────────────────
        self.audit = AuditService()
        self.event_bus: InMemoryEventBus = InMemoryEventBus()
        self.metrics = MetricsService()

        # ── Async-capable adapters (set in init()) ────────────────────────────
        self.async_idempotency = None   # RedisIdempotencyService or None
        self.async_audit = None         # PostgresAuditService or None
        self.async_event_bus = None     # KafkaEventBus or None

        # ── Policies ──────────────────────────────────────────────────────────
        self.policy_registry = PolicyRegistry()
        self.policy_registry.register(Verdict.BLOCK, BlockPolicy())
        self.policy_registry.register(Verdict.FLAG, FlagPolicy())
        self.policy_registry.register(Verdict.REVIEW, ReviewPolicy())
        self.policy_registry.register(Verdict.ALLOW, AllowPolicy())
        self.policy_engine = PolicyEngine(self.policy_registry)

        # ── Action Runner ─────────────────────────────────────────────────────
        self.action_runner = ActionRunner()

        # ── Executor ──────────────────────────────────────────────────────────
        self.executor = Executor()

    # ──────────────────────────────────────────────────────────────────────────
    # Async lifecycle
    # ──────────────────────────────────────────────────────────────────────────

    async def init(self) -> None:
        """
        Connect all async adapters.

        Called once at FastAPI application startup via the lifespan
        context manager in api.py.
        """
        logger.info("Container.init(): connecting async adapters…")

        # OpenTelemetry
        init_tracing()

        # Prometheus metrics server
        start_prometheus_server()

        # Redis idempotency
        svc = build_idempotency_service()
        if hasattr(svc, "_redis"):          # AsyncIdempotencyService
            await svc._redis.connect()
        self.async_idempotency = svc
        logger.info("Container: idempotency adapter ready (%s)", type(svc).__name__)

        # PostgreSQL audit
        audit_svc = build_audit_service()
        if hasattr(audit_svc, "connect"):   # PostgresAuditService
            dsn = os.getenv("DATABASE_URL", "")
            if dsn:
                await audit_svc.connect(dsn)
        self.async_audit = audit_svc
        logger.info("Container: audit adapter ready (%s)", type(audit_svc).__name__)

        # Kafka event bus
        bus = build_event_bus()
        await bus.start()
        self.async_event_bus = bus
        logger.info("Container: event bus adapter ready (%s)", type(bus).__name__)

        logger.info("Container.init(): all adapters connected")

    async def shutdown(self) -> None:
        """
        Gracefully close all async adapters.

        Called once at FastAPI application shutdown via the lifespan
        context manager in api.py.
        """
        logger.info("Container.shutdown(): closing async adapters…")

        if self.async_event_bus:
            await self.async_event_bus.stop()

        if self.async_audit and hasattr(self.async_audit, "disconnect"):
            await self.async_audit.disconnect()

        if (
            self.async_idempotency
            and hasattr(self.async_idempotency, "_redis")
            and hasattr(self.async_idempotency._redis, "disconnect")
        ):
            await self.async_idempotency._redis.disconnect()

        shutdown_tracing()
        logger.info("Container.shutdown(): done")


container = Container()
