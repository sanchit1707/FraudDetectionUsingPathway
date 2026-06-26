
"""
container.py
------------

Dependency Injection Container for Agent 6.

Creates and wires all services in one place so the rest of the
application never imports global singletons directly.
"""

from __future__ import annotations

from validator import RequestValidator
from idempotency import IdempotencyStore, IdempotencyService
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
from audit import AuditService
from event_bus import EventBus
from metrics import MetricsService
from executor import Executor
from models import Verdict


class Container:
    """
    Central dependency registry.

    Instantiate once during application startup.
    """

    def __init__(self):

        # ---------- Core ----------
        self.validator = RequestValidator()

        self.idempotency_store = IdempotencyStore()
        self.idempotency = IdempotencyService(
            self.idempotency_store
        )

        self.lock_store = InMemoryLockStore()
        self.distributed_lock = DistributedLockService(
            self.lock_store
        )

        self.planner = ExecutionPlanner()

        self.retry = RetryManager()

        self.circuit_registry = CircuitRegistry()

        self.audit = AuditService()

        self.event_bus = EventBus()

        self.metrics = MetricsService()

        # ---------- Policies ----------
        self.policy_registry = PolicyRegistry()

        self.policy_registry.register(
            Verdict.BLOCK,
            BlockPolicy(),
        )

        self.policy_registry.register(
            Verdict.FLAG,
            FlagPolicy(),
        )

        self.policy_registry.register(
            Verdict.REVIEW,
            ReviewPolicy(),
        )

        self.policy_registry.register(
            Verdict.ALLOW,
            AllowPolicy(),
        )

        self.policy_engine = PolicyEngine(
            self.policy_registry
        )

        # ---------- Action Runner ----------
        self.action_runner = ActionRunner()

        # Register handlers elsewhere during startup.
        # Example:
        #
        # self.action_runner.register(
        #     ActionType.LOCK_CARD,
        #     lock_card_handler,
        # )

        # ---------- Executor ----------
        #
        # Current Executor implementation uses module-level
        # services internally. Keeping this instance here
        # gives callers one access point today.
        #
        # A future refactor should inject dependencies into
        # Executor.__init__ instead of relying on globals.
        #
        self.executor = Executor()


container = Container()
