"""
executor.py
-----------

Main orchestration layer for Agent 6.

Changes from original
---------------------
- OpenTelemetry spans wrap the full execute() call and each individual action.
- All existing logic (validate → idempotency → lock → plan → run → audit → event)
  is unchanged.
- A new async execute_async() method is provided for use by the FastAPI layer.
"""

from __future__ import annotations

import logging
from datetime import datetime

from models import (
    ExecutionRequest,
    ExecutionResult,
    ExecutionState,
    EventType,
)
from validator import validate_request
from idempotency import idempotency
from distributed_lock import distributed_lock
from policy_engine import policy_engine
from action_runner import action_runner
from audit import audit_service
from event_bus import event_bus
from tracing import get_tracer

logger = logging.getLogger(__name__)
tracer = get_tracer("flashguard.executor")


class Executor:

    # ──────────────────────────────────────────────────────────────────────────
    # Synchronous path (CLI / unit-test compatible)
    # ──────────────────────────────────────────────────────────────────────────

    def execute(self, request: ExecutionRequest) -> ExecutionResult:
        """
        Full synchronous execution pipeline with OTEL tracing.

        Span hierarchy:
            agent6.execute
              └─ agent6.action.<ACTION_TYPE>   (one per action)
        """
        with tracer.start_as_current_span("agent6.execute") as span:
            span.set_attribute("txn.id", request.transaction_id)
            span.set_attribute("txn.verdict", request.verdict.value)
            span.set_attribute("txn.trace_id", request.trace_id)

            started = datetime.utcnow()

            # 1. Validate
            validate_request(request)
            span.add_event("request.validated")

            # 2. Idempotency
            hit, cached, key = idempotency.check(request)
            if hit:
                span.set_attribute("idempotency.hit", True)
                return cached
            span.set_attribute("idempotency.hit", False)

            # 3. Build plan
            plan = policy_engine.build_plan(request)
            span.set_attribute("plan.id", plan.execution_id)
            span.set_attribute("plan.policy", plan.policy_name)
            span.set_attribute("plan.action_count", len(plan.actions))
            span.add_event("plan.built")

            # 4. Acquire lock
            distributed_lock.acquire(
                execution_key=key,
                execution_id=plan.execution_id,
            )
            span.add_event("lock.acquired")

            try:
                # 5. Execute actions
                action_results = []
                for action in plan.actions:
                    with tracer.start_as_current_span(
                        f"agent6.action.{action.action_type.value}"
                    ) as action_span:
                        action_span.set_attribute(
                            "action.type", action.action_type.value
                        )
                        action_span.set_attribute("action.priority", action.priority)
                        result_item = action_runner.execute(action)
                        action_span.set_attribute(
                            "action.status", result_item.status.value
                        )
                        action_span.set_attribute(
                            "action.latency_ms", result_item.latency_ms
                        )
                        action_results.append(result_item)

                success = all(
                    r.status.value == "SUCCESS" for r in action_results
                )

                completed = datetime.utcnow()
                latency = (completed - started).total_seconds() * 1000

                result = ExecutionResult(
                    execution_id=plan.execution_id,
                    transaction_id=request.transaction_id,
                    state=(
                        ExecutionState.SUCCESS if success
                        else ExecutionState.FAILED
                    ),
                    started_at=started,
                    completed_at=completed,
                    latency_ms=round(latency, 2),
                    action_results=action_results,
                    cached=False,
                    success=success,
                    message=(
                        "Execution completed" if success
                        else "Execution failed"
                    ),
                )

                span.set_attribute("result.state", result.state.value)
                span.set_attribute("result.latency_ms", result.latency_ms)

                # 6. Cache result
                idempotency.store_result(key, result)

                # 7. Audit
                audit_service.write(plan, result)
                span.add_event("audit.written")

                # 8. Publish event
                event_bus.publish_simple(
                    topic=(
                        EventType.EXECUTION_COMPLETED if success
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
                span.add_event("event.published")

                return result

            finally:
                distributed_lock.release(
                    execution_key=key,
                    execution_id=plan.execution_id,
                )
                span.add_event("lock.released")

    # ──────────────────────────────────────────────────────────────────────────
    # Async path (FastAPI)
    # ──────────────────────────────────────────────────────────────────────────

    async def execute_async(
        self,
        request: ExecutionRequest,
        async_idempotency=None,
        async_audit=None,
        async_event_bus=None,
    ) -> ExecutionResult:
        """
        Async execution pipeline for use from FastAPI request handlers.

        Accepts optional async adapters for idempotency, audit, and event bus.
        Falls back to the sync module-level singletons when adapters are None.
        """
        with tracer.start_as_current_span("agent6.execute_async") as span:
            span.set_attribute("txn.id", request.transaction_id)
            span.set_attribute("txn.verdict", request.verdict.value)
            span.set_attribute("txn.trace_id", request.trace_id)

            started = datetime.utcnow()

            # 1. Validate
            validate_request(request)

            # 2. Idempotency (async)
            _idem = async_idempotency or idempotency
            if hasattr(_idem, "check") and asyncio_is_coroutine_function(
                _idem.check
            ):
                hit, cached, key = await _idem.check(request)
            else:
                hit, cached, key = _idem.check(request)

            if hit:
                span.set_attribute("idempotency.hit", True)
                return cached
            span.set_attribute("idempotency.hit", False)

            # 3. Build plan
            plan = policy_engine.build_plan(request)
            span.set_attribute("plan.id", plan.execution_id)
            span.set_attribute("plan.policy", plan.policy_name)

            # 4. Acquire lock
            distributed_lock.acquire(
                execution_key=key,
                execution_id=plan.execution_id,
            )

            try:
                # 5. Execute actions
                action_results = []
                for action in plan.actions:
                    with tracer.start_as_current_span(
                        f"agent6.action.{action.action_type.value}"
                    ) as action_span:
                        action_span.set_attribute(
                            "action.type", action.action_type.value
                        )
                        result_item = action_runner.execute(action)
                        action_span.set_attribute(
                            "action.status", result_item.status.value
                        )
                        action_results.append(result_item)

                success = all(
                    r.status.value == "SUCCESS" for r in action_results
                )
                completed = datetime.utcnow()
                latency = (completed - started).total_seconds() * 1000

                result = ExecutionResult(
                    execution_id=plan.execution_id,
                    transaction_id=request.transaction_id,
                    state=(
                        ExecutionState.SUCCESS if success
                        else ExecutionState.FAILED
                    ),
                    started_at=started,
                    completed_at=completed,
                    latency_ms=round(latency, 2),
                    action_results=action_results,
                    cached=False,
                    success=success,
                    message=(
                        "Execution completed" if success
                        else "Execution failed"
                    ),
                )

                # 6. Cache result
                if hasattr(_idem, "store_result") and asyncio_is_coroutine_function(
                    _idem.store_result
                ):
                    await _idem.store_result(key, result)
                else:
                    _idem.store_result(key, result)

                # 7. Audit (async)
                _audit = async_audit or audit_service
                if hasattr(_audit, "async_write"):
                    await _audit.async_write(plan, result)
                else:
                    _audit.write(plan, result)

                # 8. Publish event (async)
                _bus = async_event_bus or event_bus
                if hasattr(_bus, "async_publish_simple"):
                    await _bus.async_publish_simple(
                        topic=(
                            EventType.EXECUTION_COMPLETED if success
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
                else:
                    _bus.publish_simple(
                        topic=(
                            EventType.EXECUTION_COMPLETED if success
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


def asyncio_is_coroutine_function(fn) -> bool:
    import asyncio
    return asyncio.iscoroutinefunction(fn)


executor = Executor()
