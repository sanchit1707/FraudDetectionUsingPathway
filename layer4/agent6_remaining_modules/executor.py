
"""
executor.py
-----------

Main orchestration layer for Agent 6.
"""

from __future__ import annotations

from datetime import datetime

from models import (
    ExecutionRequest,
    ExecutionResult,
    ExecutionState,
)

from validator import validate_request
from idempotency import idempotency
from distributed_lock import distributed_lock
from policy_engine import policy_engine
from action_runner import action_runner
from audit import audit_service
from event_bus import event_bus
from models import EventType


class Executor:

    def execute(self, request: ExecutionRequest) -> ExecutionResult:

        started = datetime.utcnow()

        # 1. Validate
        validate_request(request)

        # 2. Idempotency
        hit, cached, key = idempotency.check(request)
        if hit:
            return cached

        # 3. Build plan
        plan = policy_engine.build_plan(request)

        # 4. Acquire lock
        distributed_lock.acquire(
            execution_key=key,
            execution_id=plan.execution_id,
        )

        try:

            # 5. Execute actions
            action_results = []
            for action in plan.actions:
                action_results.append(
                    action_runner.execute(action)
                )

            success = all(
                r.status.value == "SUCCESS"
                for r in action_results
            )

            completed = datetime.utcnow()

            latency = (
                completed - started
            ).total_seconds() * 1000

            result = ExecutionResult(
                execution_id=plan.execution_id,
                transaction_id=request.transaction_id,
                state=(
                    ExecutionState.SUCCESS
                    if success
                    else ExecutionState.FAILED
                ),
                started_at=started,
                completed_at=completed,
                latency_ms=round(latency, 2),
                action_results=action_results,
                cached=False,
                success=success,
                message=(
                    "Execution completed"
                    if success
                    else "Execution failed"
                ),
            )

            # 6. Save idempotent result
            idempotency.store_result(key, result)

            # 7. Audit
            audit_service.write(plan, result)

            # 8. Publish event
            event_bus.publish_simple(
                topic=(
                    EventType.EXECUTION_COMPLETED
                    if success
                    else EventType.EXECUTION_FAILED
                ),
                key=request.transaction_id,
                payload={
                    "execution_id": plan.execution_id,
                    "transaction_id": request.transaction_id,
                    "success": success,
                    "latency_ms": result.latency_ms,
                    "trace_id": request.trace_id,
                },
            )

            return result

        finally:
            distributed_lock.release(
                execution_key=key,
                execution_id=plan.execution_id,
            )


executor = Executor()
