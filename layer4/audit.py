"""
audit.py
--------

Dual-mode immutable audit log for FlashGuard Agent 6.

Modes
-----
InMemoryAuditService  (original, default)
    Thread-safe in-memory list with deep-copy immutability guarantees.

PostgresAuditService
    Async asyncpg-backed service that writes records to the
    `audit_events` table (see db_migrations/001_init.sql).
    Falls back to in-memory list if the pool is unavailable.

Factory
-------
    build_audit_service()  reads DATABASE_URL from env.

The module-level singleton `audit_service` is an InMemoryAuditService
so all existing code that imports it continues to work unchanged.
"""

from __future__ import annotations

import json
import logging
import os
from copy import deepcopy
from datetime import datetime
from threading import RLock
from typing import List, Optional
from uuid import uuid4

from models import (
    AuditEvent,
    ExecutionPlan,
    ExecutionResult,
    ExecutionState,
)

logger = logging.getLogger(__name__)


# ──────────────────────────────────────────────────────────────────────────────
# In-Memory Service (original, kept intact)
# ──────────────────────────────────────────────────────────────────────────────

class AuditService:
    """Original thread-safe in-memory audit log."""

    def __init__(self) -> None:
        self._events: List[AuditEvent] = []
        self._lock = RLock()

    def write(
        self,
        plan: ExecutionPlan,
        result: ExecutionResult,
        actor: str = "agent6",
    ) -> AuditEvent:
        event = AuditEvent(
            event_id=f"audit_{uuid4().hex}",
            execution_id=plan.execution_id,
            transaction_id=plan.request.transaction_id,
            timestamp=datetime.utcnow(),
            state=result.state,
            actor=actor,
            description=self._describe(result.state),
            metadata={
                "trace_id": plan.request.trace_id,
                "policy": plan.policy_name,
                "gateway_trace": plan.request.gateway_trace,
                "cached": result.cached,
                "success": result.success,
                "latency_ms": result.latency_ms,
                "action_count": len(result.action_results),
            },
        )
        with self._lock:
            self._events.append(deepcopy(event))
        return event

    def history(self) -> List[AuditEvent]:
        with self._lock:
            return deepcopy(self._events)

    def by_transaction(self, transaction_id: str) -> List[AuditEvent]:
        with self._lock:
            return [
                deepcopy(e)
                for e in self._events
                if e.transaction_id == transaction_id
            ]

    def clear(self) -> None:
        with self._lock:
            self._events.clear()

    @staticmethod
    def _describe(state: ExecutionState) -> str:
        descriptions = {
            ExecutionState.SUCCESS: "Execution completed successfully.",
            ExecutionState.FAILED: "Execution failed.",
            ExecutionState.RETRYING: "Execution retry scheduled.",
            ExecutionState.DEAD_LETTER: "Execution moved to dead-letter queue.",
            ExecutionState.EXECUTING: "Execution started.",
            ExecutionState.PLANNED: "Execution plan created.",
            ExecutionState.VALIDATED: "Request validated.",
            ExecutionState.DEDUPED: "Idempotency check completed.",
            ExecutionState.RECEIVED: "Execution request received.",
        }
        return descriptions.get(state, state.value)


# ──────────────────────────────────────────────────────────────────────────────
# PostgreSQL Service
# ──────────────────────────────────────────────────────────────────────────────

class PostgresAuditService(AuditService):
    """
    Extends AuditService with async PostgreSQL persistence.

    Every `write()` call still appends to the in-memory list (for fast
    in-process reads / tests) AND inserts a row into `audit_events`.

    Falls back silently if the pool is not initialised.
    """

    def __init__(self) -> None:
        super().__init__()
        self._pool = None

    async def connect(self, dsn: str) -> None:
        """Initialise the asyncpg connection pool.  Called at app startup."""
        try:
            import asyncpg
            self._pool = await asyncpg.create_pool(
                dsn=dsn,
                min_size=2,
                max_size=10,
                command_timeout=10,
            )
            logger.info("PostgresAuditService: pool connected → %s", _mask_dsn(dsn))
        except Exception as exc:
            logger.warning(
                "PostgresAuditService: failed to connect (%s). "
                "Audit records will be in-memory only.",
                exc,
            )
            self._pool = None

    async def disconnect(self) -> None:
        if self._pool:
            await self._pool.close()
            self._pool = None

    def write(
        self,
        plan: ExecutionPlan,
        result: ExecutionResult,
        actor: str = "agent6",
    ) -> AuditEvent:
        """Sync write to in-memory store (always succeeds)."""
        event = super().write(plan, result, actor)
        return event

    async def async_write(
        self,
        plan: ExecutionPlan,
        result: ExecutionResult,
        actor: str = "agent6",
    ) -> AuditEvent:
        """Async write: in-memory + PostgreSQL."""
        event = self.write(plan, result, actor)

        if self._pool is None:
            return event

        try:
            async with self._pool.acquire() as conn:
                await conn.execute(
                    """
                    INSERT INTO audit_events
                        (event_id, execution_id, transaction_id, timestamp,
                         state, actor, description, metadata)
                    VALUES ($1, $2, $3, $4, $5, $6, $7, $8)
                    ON CONFLICT (event_id) DO NOTHING
                    """,
                    event.event_id,
                    event.execution_id,
                    event.transaction_id,
                    event.timestamp,
                    event.state.value,
                    event.actor,
                    event.description,
                    json.dumps(event.metadata),
                )
                logger.debug(
                    "PostgresAuditService: wrote event %s for txn %s",
                    event.event_id,
                    event.transaction_id,
                )
        except Exception as exc:
            logger.error(
                "PostgresAuditService: DB write error for event %s: %s",
                event.event_id,
                exc,
            )

        return event

    async def async_by_transaction(
        self,
        transaction_id: str,
    ) -> List[AuditEvent]:
        """Query PostgreSQL for audit events by transaction ID."""
        if self._pool is None:
            return self.by_transaction(transaction_id)

        try:
            async with self._pool.acquire() as conn:
                rows = await conn.fetch(
                    """
                    SELECT event_id, execution_id, transaction_id, timestamp,
                           state, actor, description, metadata
                    FROM   audit_events
                    WHERE  transaction_id = $1
                    ORDER  BY timestamp DESC
                    """,
                    transaction_id,
                )
                return [_row_to_audit_event(r) for r in rows]
        except Exception as exc:
            logger.error(
                "PostgresAuditService: DB query error for txn %s: %s",
                transaction_id,
                exc,
            )
            # Fall back to in-memory
            return self.by_transaction(transaction_id)


# ──────────────────────────────────────────────────────────────────────────────
# Helpers
# ──────────────────────────────────────────────────────────────────────────────

def _row_to_audit_event(row) -> AuditEvent:
    meta = row["metadata"]
    if isinstance(meta, str):
        meta = json.loads(meta)
    return AuditEvent(
        event_id=row["event_id"],
        execution_id=row["execution_id"],
        transaction_id=row["transaction_id"],
        timestamp=row["timestamp"],
        state=ExecutionState(row["state"]),
        actor=row["actor"],
        description=row["description"] or "",
        metadata=meta or {},
    )


def _mask_dsn(dsn: str) -> str:
    """Replace password in DSN with *** for safe logging."""
    import re
    return re.sub(r"(:)([^:@]+)(@)", r"\1***\3", dsn)


# ──────────────────────────────────────────────────────────────────────────────
# Factory
# ──────────────────────────────────────────────────────────────────────────────

def build_audit_service() -> AuditService:
    """
    Return a PostgresAuditService if DATABASE_URL is set,
    otherwise an InMemoryAuditService.

    For PostgresAuditService call `await svc.connect(dsn)` at app startup.
    """
    dsn = os.getenv("DATABASE_URL", "").strip()
    if dsn:
        logger.info("AuditService: PostgreSQL mode")
        return PostgresAuditService()
    logger.info("AuditService: in-memory mode (DATABASE_URL not set)")
    return AuditService()


# ──────────────────────────────────────────────────────────────────────────────
# Module-level singleton (backward compatible)
# ──────────────────────────────────────────────────────────────────────────────
audit_service = AuditService()
