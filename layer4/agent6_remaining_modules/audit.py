
"""
audit.py
--------

Immutable in-memory audit log for Agent 6.
Replace AuditStore with a database or append-only log in production.
"""

from __future__ import annotations

from copy import deepcopy
from datetime import datetime
from threading import RLock
from uuid import uuid4
from typing import List

from models import (
    AuditEvent,
    ExecutionPlan,
    ExecutionResult,
    ExecutionState,
)


class AuditService:
    def __init__(self):
        self._events: List[AuditEvent] = []
        self._lock = RLock()

    def write(
        self,
        plan: ExecutionPlan,
        result: ExecutionResult,
        actor: str = "agent6",
    ) -> AuditEvent:
        """
        Persist an immutable audit event.
        """

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

    def by_transaction(
        self,
        transaction_id: str,
    ) -> List[AuditEvent]:
        with self._lock:
            return [
                deepcopy(e)
                for e in self._events
                if e.transaction_id == transaction_id
            ]

    def clear(self):
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


audit_service = AuditService()
