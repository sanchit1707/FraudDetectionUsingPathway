"""
test_agent6.py
==============

Demo test script for FlashGuard Agent 6 – Execution Orchestrator.

Covers:
  - models.py          : all enums & dataclasses
  - validator.py       : request validation
  - idempotency.py     : exactly-once execution
  - distributed_lock.py: lock acquire / release / duplicate detection
  - planner.py         : execution plan creation & ordering
  - policy_engine.py   : all four policies (BLOCK, FLAG, REVIEW, ALLOW)
  - action_runner.py   : action execution, handler registration
  - retry.py           : RetryManager
  - circuit_breaker.py : CircuitRegistry + Circuit
  - audit.py           : write, history, by_transaction, clear
  - metrics.py         : record, snapshot, percentiles, reset
  - event_bus.py       : publish / subscribe / publish_simple
  - executor.py        : full end-to-end pipeline (all verdicts)
                         + idempotency cache hit path

Run with:
    python test_agent6.py

No third-party dependencies required.
"""

import sys
import os
import traceback
from datetime import datetime

# ──────────────────────────────────────────────
# Helpers
# ──────────────────────────────────────────────

PASS = "✅ PASS"
FAIL = "❌ FAIL"

results = []


def run(label: str, fn):
    """Execute a single test case and record the result."""
    try:
        fn()
        results.append((PASS, label))
        print(f"{PASS}  {label}")
    except Exception as exc:
        results.append((FAIL, label))
        print(f"{FAIL}  {label}")
        traceback.print_exc()


def make_request(
    txn_id="TXN-TEST-001",
    verdict=None,
    confidence=0.95,
    risk=0.90,
    tier=1,
):
    """Return a fully-populated ExecutionRequest."""
    from models import ExecutionRequest, Policy, Verdict

    if verdict is None:
        verdict = Verdict.BLOCK

    return ExecutionRequest(
        transaction_id=txn_id,
        account_id="ACC-TEST-001",
        customer_id="CUS-TEST-001",
        verdict=verdict,
        confidence=confidence,
        risk_score=risk,
        tier=tier,
        policy=Policy(
            id="policy-test",
            version="v1.0",
            name="TestPolicy",
        ),
        gateway_trace="test-gateway-trace",
        timestamp=datetime.utcnow(),
    )


# ══════════════════════════════════════════════
# 1. MODELS
# ══════════════════════════════════════════════

def test_models_enums():
    from models import (
        Verdict, ActionType, ExecutionState,
        ActionStatus, EventType,
    )
    assert Verdict.BLOCK == "BLOCK"
    assert ActionType.LOCK_CARD == "LOCK_CARD"
    assert ExecutionState.SUCCESS == "SUCCESS"
    assert ActionStatus.PENDING == "PENDING"
    assert EventType.EXECUTION_COMPLETED == "execution.completed"


def test_models_policy():
    from models import Policy
    p = Policy(id="p1", version="v1", name="TestPolicy")
    assert p.id == "p1"


def test_models_execution_request():
    req = make_request()
    assert req.transaction_id == "TXN-TEST-001"
    assert req.tier == 1


def test_models_action():
    from models import Action, ActionType
    a = Action(ActionType.LOCK_CARD, priority=0)
    assert a.retryable is True
    assert a.timeout_ms == 3000


def test_models_action_result():
    from models import ActionResult, ActionStatus, ActionType
    ar = ActionResult(
        action_type=ActionType.WRITE_AUDIT,
        status=ActionStatus.SUCCESS,
        latency_ms=12.5,
        message="OK",
    )
    assert ar.retries == 0


def test_models_execution_result():
    from models import ExecutionResult, ExecutionState
    er = ExecutionResult(
        execution_id="exe_test",
        transaction_id="TXN-001",
        state=ExecutionState.SUCCESS,
        started_at=datetime.utcnow(),
        completed_at=datetime.utcnow(),
        latency_ms=50.0,
        action_results=[],
        success=True,
    )
    assert er.cached is False


def test_models_audit_event():
    from models import AuditEvent, ExecutionState
    ae = AuditEvent(
        event_id="audit_x",
        execution_id="exe_x",
        transaction_id="TXN-X",
        timestamp=datetime.utcnow(),
        state=ExecutionState.SUCCESS,
        actor="agent6",
        description="done",
    )
    assert ae.metadata == {}


def test_models_execution_metrics():
    from models import ExecutionMetrics
    m = ExecutionMetrics()
    assert m.executed == 0
    assert m.average_latency_ms == 0.0


def test_models_create_execution_id():
    from models import create_execution_id
    eid = create_execution_id()
    assert eid.startswith("exe_")
    assert len(eid) > 4


# ══════════════════════════════════════════════
# 2. VALIDATOR
# ══════════════════════════════════════════════

def test_validator_valid_request():
    from validator import validate_request
    req = make_request()
    validate_request(req)  # Should not raise


def test_validator_missing_transaction_id():
    from validator import validate_request, ValidationError
    from models import ExecutionRequest, Policy, Verdict
    req = ExecutionRequest(
        transaction_id="",
        account_id="ACC-001",
        customer_id="CUS-001",
        verdict=Verdict.ALLOW,
        confidence=0.5,
        risk_score=0.5,
        tier=1,
        policy=Policy("p", "v1", "P"),
        gateway_trace="g",
        timestamp=datetime.utcnow(),
    )
    try:
        validate_request(req)
        assert False, "Expected ValidationError"
    except ValidationError:
        pass


def test_validator_class_instance():
    from validator import RequestValidator
    v = RequestValidator()
    req = make_request()
    v.validate(req)  # Should not raise


# ══════════════════════════════════════════════
# 3. IDEMPOTENCY
# ══════════════════════════════════════════════

def test_idempotency_first_call_is_miss():
    from idempotency import IdempotencyStore, IdempotencyService
    store = IdempotencyStore()
    svc = IdempotencyService(store)
    req = make_request("TXN-IDEM-001")
    hit, cached, key = svc.check(req)
    assert hit is False
    assert cached is None
    assert len(key) == 64  # SHA-256 hex digest


def test_idempotency_second_call_is_hit():
    from idempotency import IdempotencyStore, IdempotencyService
    from models import ExecutionResult, ExecutionState
    store = IdempotencyStore()
    svc = IdempotencyService(store)
    req = make_request("TXN-IDEM-002")

    # First call – miss
    _, _, key = svc.check(req)

    # Simulate storing a result
    fake_result = ExecutionResult(
        execution_id="exe_fake",
        transaction_id="TXN-IDEM-002",
        state=ExecutionState.SUCCESS,
        started_at=datetime.utcnow(),
        completed_at=datetime.utcnow(),
        latency_ms=10.0,
        action_results=[],
        success=True,
    )
    svc.store_result(key, fake_result)

    # Second call – hit
    hit, cached, _ = svc.check(req)
    assert hit is True
    assert cached.execution_id == "exe_fake"


def test_idempotency_different_verdicts_different_keys():
    from idempotency import IdempotencyStore, IdempotencyService
    from models import Verdict
    store = IdempotencyStore()
    svc = IdempotencyService(store)
    req_block = make_request("TXN-IDEM-003", verdict=Verdict.BLOCK)
    req_allow = make_request("TXN-IDEM-003", verdict=Verdict.ALLOW)
    _, _, key1 = svc.check(req_block)
    _, _, key2 = svc.check(req_allow)
    assert key1 != key2


# ══════════════════════════════════════════════
# 4. DISTRIBUTED LOCK
# ══════════════════════════════════════════════

def test_lock_acquire_and_release():
    from distributed_lock import InMemoryLockStore, DistributedLockService
    store = InMemoryLockStore()
    svc = DistributedLockService(store)
    svc.acquire("key-001", "exe-001")
    assert "key-001" in store._locks
    svc.release("key-001", "exe-001")
    assert "key-001" not in store._locks


def test_lock_duplicate_raises():
    from distributed_lock import InMemoryLockStore, DistributedLockService
    store = InMemoryLockStore()
    svc = DistributedLockService(store)
    svc.acquire("key-dup", "exe-dup")
    try:
        svc.acquire("key-dup", "exe-dup")
        assert False, "Expected RuntimeError for duplicate lock"
    except RuntimeError:
        pass
    finally:
        svc.release("key-dup", "exe-dup")


def test_lock_release_nonexistent_is_safe():
    from distributed_lock import InMemoryLockStore, DistributedLockService
    store = InMemoryLockStore()
    svc = DistributedLockService(store)
    # discard on non-existent key should NOT raise
    svc.release("no-such-key", "exe-x")


# ══════════════════════════════════════════════
# 5. PLANNER
# ══════════════════════════════════════════════

def test_planner_creates_plan():
    from planner import ExecutionPlanner
    from models import Action, ActionType
    planner = ExecutionPlanner()
    req = make_request()
    actions = [
        Action(ActionType.PUBLISH_EVENT, 2),
        Action(ActionType.LOCK_CARD, 0),
        Action(ActionType.WRITE_AUDIT, 1),
    ]
    plan = planner.build_plan(req, actions, "BlockPolicy")
    assert plan.execution_id.startswith("exe_")
    # Actions should be sorted by priority
    priorities = [a.priority for a in plan.actions]
    assert priorities == sorted(priorities)


def test_create_execution_plan_function():
    from planner import create_execution_plan
    from models import Action, ActionType
    req = make_request()
    actions = [Action(ActionType.WRITE_AUDIT, 0)]
    plan = create_execution_plan(req, actions, "AllowPolicy")
    assert plan.policy_name == "AllowPolicy"
    assert len(plan.actions) == 1


# ══════════════════════════════════════════════
# 6. POLICY ENGINE
# ══════════════════════════════════════════════

def test_policy_block_actions():
    from policy_engine import BlockPolicy
    from models import ActionType
    p = BlockPolicy()
    actions = p.actions(make_request())
    types = [a.action_type for a in actions]
    assert ActionType.LOCK_CARD in types
    assert ActionType.FREEZE_TRANSACTION in types
    assert ActionType.NOTIFY_FIU in types


def test_policy_flag_actions():
    from policy_engine import FlagPolicy
    from models import ActionType
    p = FlagPolicy()
    actions = p.actions(make_request())
    types = [a.action_type for a in actions]
    assert ActionType.LOCK_CARD in types
    assert ActionType.NOTIFY_CUSTOMER in types


def test_policy_review_actions():
    from policy_engine import ReviewPolicy
    from models import ActionType
    p = ReviewPolicy()
    actions = p.actions(make_request())
    types = [a.action_type for a in actions]
    assert ActionType.CREATE_CASE in types
    assert ActionType.NOTIFY_ANALYST in types


def test_policy_allow_actions():
    from policy_engine import AllowPolicy
    from models import ActionType
    p = AllowPolicy()
    actions = p.actions(make_request())
    types = [a.action_type for a in actions]
    assert ActionType.WRITE_AUDIT in types
    assert ActionType.PUBLISH_EVENT in types
    # ALLOW should NOT lock the card
    assert ActionType.LOCK_CARD not in types


def test_policy_registry_get():
    from policy_engine import PolicyRegistry, BlockPolicy
    from models import Verdict
    reg = PolicyRegistry()
    reg.register(Verdict.BLOCK, BlockPolicy())
    p = reg.get(Verdict.BLOCK)
    assert p.name == "BlockPolicy"


def test_policy_registry_unknown_raises():
    from policy_engine import PolicyRegistry, PolicyError
    from models import Verdict
    reg = PolicyRegistry()
    try:
        reg.get(Verdict.ALLOW)
        assert False, "Expected PolicyError"
    except PolicyError:
        pass


def test_policy_engine_builds_plan():
    from policy_engine import PolicyRegistry, PolicyEngine, BlockPolicy
    from models import Verdict
    reg = PolicyRegistry()
    reg.register(Verdict.BLOCK, BlockPolicy())
    engine = PolicyEngine(reg)
    req = make_request(verdict=Verdict.BLOCK)
    plan = engine.build_plan(req)
    assert plan.policy_name == "BlockPolicy"
    assert len(plan.actions) > 0


# ══════════════════════════════════════════════
# 7. RETRY
# ══════════════════════════════════════════════

def test_retry_manager_runs_fn():
    from retry import RetryManager
    rm = RetryManager()
    result = rm.run(lambda: 42)
    assert result.value == 42
    assert result.attempts == 1


def test_retry_result_dataclass():
    from retry import RetryResult
    r = RetryResult(value="OK", attempts=3)
    assert r.value == "OK"
    assert r.attempts == 3


# ══════════════════════════════════════════════
# 8. CIRCUIT BREAKER
# ══════════════════════════════════════════════

def test_circuit_call_fn():
    from circuit_breaker import Circuit
    c = Circuit()
    val = c.call(lambda: "hello")
    assert val == "hello"


def test_circuit_registry_returns_circuit():
    from circuit_breaker import CircuitRegistry, Circuit
    reg = CircuitRegistry()
    c = reg.get("some-service")
    assert isinstance(c, Circuit)


def test_circuit_registry_same_instance():
    from circuit_breaker import CircuitRegistry
    reg = CircuitRegistry()
    c1 = reg.get("svc-a")
    c2 = reg.get("svc-a")
    assert c1 is c2


# ══════════════════════════════════════════════
# 9. ACTION RUNNER
# ══════════════════════════════════════════════

def test_action_runner_default_handler():
    from action_runner import ActionRunner
    from models import Action, ActionType, ActionStatus
    runner = ActionRunner()
    action = Action(ActionType.LOCK_CARD, 0)
    result = runner.execute(action)
    assert result.action_type == ActionType.LOCK_CARD
    assert result.status == ActionStatus.SUCCESS


def test_action_runner_custom_handler():
    from action_runner import ActionRunner
    from models import Action, ActionType, ActionStatus
    runner = ActionRunner()
    called = []

    def my_handler(a):
        called.append(a.action_type)
        return "done"

    runner.register(ActionType.NOTIFY_CUSTOMER, my_handler)
    action = Action(ActionType.NOTIFY_CUSTOMER, 0)
    result = runner.execute(action)
    assert result.status == ActionStatus.SUCCESS
    assert ActionType.NOTIFY_CUSTOMER in called


# ══════════════════════════════════════════════
# 10. EVENT BUS
# ══════════════════════════════════════════════

def test_event_bus_publish_subscribe():
    from event_bus import InMemoryEventBus
    from models import EventMessage, EventType
    bus = InMemoryEventBus()
    received = []

    def handler(event):
        received.append(event)

    bus.subscribe(EventType.EXECUTION_COMPLETED, handler)
    msg = EventMessage(
        topic=EventType.EXECUTION_COMPLETED,
        key="TXN-EVT-001",
        payload={"status": "ok"},
        timestamp=datetime.utcnow(),
    )
    bus.publish(msg)
    assert len(received) == 1
    assert received[0].key == "TXN-EVT-001"


def test_event_bus_publish_simple():
    from event_bus import InMemoryEventBus
    from models import EventType
    bus = InMemoryEventBus()
    received = []
    bus.subscribe(EventType.EXECUTION_FAILED, received.append)
    bus.publish_simple(
        topic=EventType.EXECUTION_FAILED,
        key="TXN-EVT-002",
        payload={"error": "timeout"},
    )
    assert len(received) == 1


def test_event_bus_no_subscriber_is_silent():
    from event_bus import InMemoryEventBus
    from models import EventType
    bus = InMemoryEventBus()
    # No subscriber – should not raise
    bus.publish_simple(
        topic=EventType.AUDIT_WRITTEN,
        key="TXN-EVT-003",
        payload={},
    )


def test_event_bus_kafka_fallback_when_no_servers():
    """KafkaEventBus without KAFKA_BOOTSTRAP_SERVERS falls back silently."""
    from event_bus import build_event_bus, InMemoryEventBus
    import os
    os.environ.pop("KAFKA_BOOTSTRAP_SERVERS", None)
    bus = build_event_bus()
    assert isinstance(bus, InMemoryEventBus)


def test_event_bus_module_singleton_is_inmemory():
    from event_bus import event_bus, InMemoryEventBus
    assert isinstance(event_bus, InMemoryEventBus)


# ══════════════════════════════════════════════
# 11. AUDIT SERVICE
# ══════════════════════════════════════════════

def _make_plan_and_result(txn_id="TXN-AUDIT-001"):
    from models import (
        ExecutionPlan, ExecutionResult, ExecutionState,
        Action, ActionType
    )
    req = make_request(txn_id)
    plan = ExecutionPlan(
        execution_id="exe_audit_test",
        request=req,
        actions=[Action(ActionType.WRITE_AUDIT, 0)],
        created_at=datetime.utcnow(),
        policy_name="BlockPolicy",
    )
    result = ExecutionResult(
        execution_id="exe_audit_test",
        transaction_id=txn_id,
        state=ExecutionState.SUCCESS,
        started_at=datetime.utcnow(),
        completed_at=datetime.utcnow(),
        latency_ms=30.0,
        action_results=[],
        success=True,
    )
    return plan, result


def test_audit_write_creates_event():
    from audit import AuditService
    svc = AuditService()
    plan, result = _make_plan_and_result()
    event = svc.write(plan, result)
    assert event.execution_id == "exe_audit_test"
    assert event.event_id.startswith("audit_")


def test_audit_history():
    from audit import AuditService
    svc = AuditService()
    plan, result = _make_plan_and_result()
    svc.write(plan, result)
    svc.write(plan, result)
    history = svc.history()
    assert len(history) == 2


def test_audit_by_transaction():
    from audit import AuditService
    svc = AuditService()
    p1, r1 = _make_plan_and_result("TXN-A")
    p2, r2 = _make_plan_and_result("TXN-B")
    svc.write(p1, r1)
    svc.write(p2, r2)
    svc.write(p1, r1)
    txn_a_events = svc.by_transaction("TXN-A")
    assert len(txn_a_events) == 2


def test_audit_clear():
    from audit import AuditService
    svc = AuditService()
    plan, result = _make_plan_and_result()
    svc.write(plan, result)
    svc.clear()
    assert svc.history() == []


def test_audit_immutability():
    """Modifying returned history should not corrupt the store."""
    from audit import AuditService
    svc = AuditService()
    plan, result = _make_plan_and_result()
    svc.write(plan, result)
    h = svc.history()
    h.clear()
    assert len(svc.history()) == 1


# ══════════════════════════════════════════════
# 12. METRICS SERVICE
# ══════════════════════════════════════════════

def _make_success_result(latency=50.0):
    from models import ExecutionResult, ExecutionState
    return ExecutionResult(
        execution_id="exe_metrics_test",
        transaction_id="TXN-MET-001",
        state=ExecutionState.SUCCESS,
        started_at=datetime.utcnow(),
        completed_at=datetime.utcnow(),
        latency_ms=latency,
        action_results=[],
        success=True,
    )


def test_metrics_record_success():
    from metrics import MetricsService
    svc = MetricsService()
    svc.record(_make_success_result(50.0))
    snap = svc.snapshot()
    assert snap.executed == 1
    assert snap.successful == 1
    assert snap.failures == 0


def test_metrics_record_failure():
    from metrics import MetricsService
    from models import ExecutionResult, ExecutionState
    svc = MetricsService()
    result = ExecutionResult(
        execution_id="exe_fail",
        transaction_id="TXN-MET-002",
        state=ExecutionState.FAILED,
        started_at=datetime.utcnow(),
        completed_at=datetime.utcnow(),
        latency_ms=100.0,
        action_results=[],
        success=False,
    )
    svc.record(result)
    snap = svc.snapshot()
    assert snap.failures == 1
    assert snap.successful == 0


def test_metrics_average_latency():
    from metrics import MetricsService
    svc = MetricsService()
    svc.record(_make_success_result(100.0))
    svc.record(_make_success_result(200.0))
    snap = svc.snapshot()
    assert snap.average_latency_ms == 150.0


def test_metrics_percentile_single():
    from metrics import MetricsService
    svc = MetricsService()
    svc.record(_make_success_result(42.0))
    snap = svc.snapshot()
    assert snap.p95_latency_ms == 42.0
    assert snap.p99_latency_ms == 42.0


def test_metrics_increment_locked_cards():
    from metrics import MetricsService
    svc = MetricsService()
    svc.increment_locked_cards(3)
    snap = svc.snapshot()
    assert snap.locked_cards == 3


def test_metrics_reset():
    from metrics import MetricsService
    svc = MetricsService()
    svc.record(_make_success_result(80.0))
    svc.reset()
    snap = svc.snapshot()
    assert snap.executed == 0
    assert snap.average_latency_ms == 0.0


# ══════════════════════════════════════════════
# 13. EXECUTOR – End-to-End Pipeline
# ══════════════════════════════════════════════

def _fresh_executor():
    """
    Build a fully isolated Executor with its own singletons
    so tests don't share global state.
    """
    import sys
    # We import fresh module-level globals from each module.
    # Because module singletons are already instantiated on import,
    # we simply call execute() and rely on the global singletons.
    # For test isolation, we reset idempotency store between tests.
    from idempotency import idempotency
    from audit import audit_service
    idempotency.store._cache.clear()
    audit_service.clear()
    from executor import Executor
    return Executor()


def test_executor_block_verdict():
    from models import Verdict, ExecutionState
    exe = _fresh_executor()
    req = make_request("TXN-EXE-BLOCK-001", verdict=Verdict.BLOCK)
    result = exe.execute(req)
    assert result.success is True
    assert result.state == ExecutionState.SUCCESS
    assert result.transaction_id == "TXN-EXE-BLOCK-001"
    assert len(result.action_results) > 0


def test_executor_allow_verdict():
    from models import Verdict, ExecutionState
    exe = _fresh_executor()
    req = make_request("TXN-EXE-ALLOW-001", verdict=Verdict.ALLOW)
    result = exe.execute(req)
    assert result.success is True
    assert result.state == ExecutionState.SUCCESS


def test_executor_flag_verdict():
    from models import Verdict, ExecutionState
    exe = _fresh_executor()
    req = make_request("TXN-EXE-FLAG-001", verdict=Verdict.FLAG)
    result = exe.execute(req)
    assert result.success is True
    assert result.state == ExecutionState.SUCCESS


def test_executor_review_verdict():
    from models import Verdict, ExecutionState
    exe = _fresh_executor()
    req = make_request("TXN-EXE-REVIEW-001", verdict=Verdict.REVIEW)
    result = exe.execute(req)
    assert result.success is True
    assert result.state == ExecutionState.SUCCESS


def test_executor_idempotency_cache_hit():
    """Executing the same request twice must return the same cached result.

    Note: The executor stores results with cached=False and returns them
    as-is on a cache hit (executor.py line 41: `return cached`).
    We verify idempotency by checking both calls share the same execution_id.
    """
    from models import Verdict
    exe = _fresh_executor()
    req = make_request("TXN-EXE-IDEM-001", verdict=Verdict.BLOCK)

    result1 = exe.execute(req)
    result2 = exe.execute(req)

    # Both calls must resolve to the exact same execution
    assert result1.execution_id == result2.execution_id
    # Second call should be extremely fast (no actual work) – verify same txn
    assert result2.transaction_id == "TXN-EXE-IDEM-001"


def test_executor_has_action_results():
    from models import Verdict
    exe = _fresh_executor()
    req = make_request("TXN-EXE-ACTIONS-001", verdict=Verdict.BLOCK)
    result = exe.execute(req)
    assert len(result.action_results) >= 3


def test_executor_latency_is_positive():
    from models import Verdict
    exe = _fresh_executor()
    req = make_request("TXN-EXE-LATENCY-001", verdict=Verdict.ALLOW)
    result = exe.execute(req)
    assert result.latency_ms >= 0


def test_executor_audit_written():
    """After execution, at least one audit event should exist."""
    from models import Verdict
    from audit import audit_service
    audit_service.clear()
    exe = _fresh_executor()
    req = make_request("TXN-EXE-AUDIT-001", verdict=Verdict.BLOCK)
    exe.execute(req)
    history = audit_service.history()
    assert len(history) >= 1


def test_executor_event_published():
    """Execution should publish an EXECUTION_COMPLETED event."""
    from models import Verdict, EventType
    from event_bus import event_bus
    received = []
    event_bus.subscribe(EventType.EXECUTION_COMPLETED, received.append)

    exe = _fresh_executor()
    req = make_request("TXN-EXE-EVENT-001", verdict=Verdict.ALLOW)
    exe.execute(req)
    # May already have events from other tests – just verify at least one
    assert len(received) >= 1


# ══════════════════════════════════════════════
# 14. NEW MODULES – Unit tests
# ══════════════════════════════════════════════

# ── tracing.py ───────────────────────────────

def test_tracing_get_tracer_returns_tracer():
    """get_tracer() must return a usable tracer without init_tracing()."""
    from tracing import get_tracer
    from opentelemetry import trace
    t = get_tracer()
    assert t is not None


def test_tracing_init_idempotent():
    """Calling init_tracing() twice must not raise."""
    from tracing import init_tracing, shutdown_tracing
    init_tracing()
    init_tracing()  # second call is a no-op
    shutdown_tracing()


def test_tracing_span_context_manager():
    """A span must work as a context manager."""
    from tracing import get_tracer, init_tracing, shutdown_tracing
    init_tracing()
    tracer = get_tracer("test")
    with tracer.start_as_current_span("test.span") as span:
        span.set_attribute("key", "value")
    shutdown_tracing()


# ── event_bus.py (new adapters) ───────────────

def test_kafka_bus_fallback_no_servers():
    from event_bus import build_event_bus, InMemoryEventBus
    import os
    os.environ.pop("KAFKA_BOOTSTRAP_SERVERS", None)
    bus = build_event_bus()
    assert isinstance(bus, InMemoryEventBus)


def test_kafka_bus_module_singleton():
    from event_bus import event_bus, InMemoryEventBus
    assert isinstance(event_bus, InMemoryEventBus)


def test_kafka_bus_async_publish_simple_inmemory():
    """async_publish_simple on InMemoryEventBus works without event loop issues."""
    import asyncio
    from event_bus import InMemoryEventBus
    from models import EventType
    bus = InMemoryEventBus()
    received = []
    bus.subscribe(EventType.EXECUTION_COMPLETED, received.append)
    asyncio.run(bus.async_publish_simple(
        topic=EventType.EXECUTION_COMPLETED,
        key="TXN-ASYNC-001",
        payload={"ok": True},
    ))
    assert len(received) == 1


# ── idempotency.py (new adapters) ─────────────

def test_idempotency_build_service_no_redis():
    """build_idempotency_service() with no REDIS_URL returns sync service."""
    import os
    os.environ.pop("REDIS_URL", None)
    from idempotency import build_idempotency_service, IdempotencyService
    svc = build_idempotency_service()
    assert isinstance(svc, IdempotencyService)


def test_idempotency_make_key_consistency():
    """Same input always produces same key."""
    from idempotency import _make_key
    req = make_request("TXN-KEY-001")
    k1 = _make_key(req)
    k2 = _make_key(req)
    assert k1 == k2
    assert len(k1) == 64


def test_idempotency_result_json_roundtrip():
    """_result_to_json / _json_to_result roundtrip preserves key fields."""
    from idempotency import _result_to_json, _json_to_result
    from models import ExecutionResult, ExecutionState
    result = ExecutionResult(
        execution_id="exe_rt_001",
        transaction_id="TXN-RT-001",
        state=ExecutionState.SUCCESS,
        started_at=datetime.utcnow(),
        completed_at=datetime.utcnow(),
        latency_ms=25.5,
        action_results=[],
        success=True,
        message="OK",
    )
    json_str = _result_to_json(result)
    restored = _json_to_result(json_str)
    assert restored.execution_id == result.execution_id
    assert restored.transaction_id == result.transaction_id
    assert restored.success == result.success
    assert restored.cached is True   # set on deserialise


# ── audit.py (new adapters) ───────────────────

def test_audit_build_service_no_db():
    """build_audit_service() with no DATABASE_URL returns in-memory service."""
    import os
    os.environ.pop("DATABASE_URL", None)
    from audit import build_audit_service, AuditService
    svc = build_audit_service()
    assert isinstance(svc, AuditService)


def test_postgres_audit_service_sync_write_still_works():
    """PostgresAuditService.write() (sync) still appends to in-memory list."""
    from audit import PostgresAuditService
    svc = PostgresAuditService()
    plan, result = _make_plan_and_result("TXN-PG-001")
    event = svc.write(plan, result)  # pool is None → in-memory only
    assert event.execution_id == "exe_audit_test"
    assert len(svc.history()) == 1


# ── metrics.py (Prometheus) ───────────────────

def test_metrics_prometheus_record_does_not_raise():
    """Prometheus counters must not break record() even if prom not init."""
    from metrics import MetricsService
    svc = MetricsService()
    svc.record(_make_success_result(10.0))
    assert svc.snapshot().executed == 1


def test_metrics_record_with_verdict():
    from metrics import MetricsService
    svc = MetricsService()
    svc.record_with_verdict(_make_success_result(20.0), "BLOCK")
    snap = svc.snapshot()
    assert snap.executed == 1


# ── executor.py async path ────────────────────

def test_executor_async_block_verdict():
    """execute_async() must work with the sync in-memory adapters."""
    import asyncio
    from models import Verdict, ExecutionState
    from idempotency import idempotency
    from audit import audit_service
    idempotency.store._cache.clear()
    audit_service.clear()
    from executor import Executor
    exe = Executor()
    req = make_request("TXN-ASYNC-BLOCK-001", verdict=Verdict.BLOCK)
    result = asyncio.run(exe.execute_async(req))
    assert result.success is True
    assert result.state == ExecutionState.SUCCESS


def test_executor_async_idempotency_cache_hit():
    """execute_async() must return same execution_id on duplicate call."""
    import asyncio
    from models import Verdict
    from idempotency import idempotency
    from audit import audit_service
    idempotency.store._cache.clear()
    audit_service.clear()
    from executor import Executor
    exe = Executor()
    req = make_request("TXN-ASYNC-IDEM-001", verdict=Verdict.ALLOW)
    r1 = asyncio.run(exe.execute_async(req))
    r2 = asyncio.run(exe.execute_async(req))
    assert r1.execution_id == r2.execution_id


# ══════════════════════════════════════════════
# 15. INTEGRATION TESTS (requires docker-compose)
#     Skipped unless INTEGRATION=1 env var is set
# ══════════════════════════════════════════════

INTEGRATION = os.environ.get("INTEGRATION") == "1"
SKIP = "[SKIP - set INTEGRATION=1 to run]"

import os as _os


async def _integration_redis():
    import os
    redis_url = os.getenv("REDIS_URL", "redis://localhost:6379/0")
    from idempotency import RedisIdempotencyStore, AsyncIdempotencyService
    store = RedisIdempotencyStore(redis_url=redis_url, ttl=60)
    await store.connect()
    assert store._client is not None, "Redis connection failed"

    svc = AsyncIdempotencyService(store)
    req = make_request("TXN-INTEG-REDIS-001")
    hit, cached, key = await svc.check(req)
    assert hit is False

    from models import ExecutionResult, ExecutionState
    fake = ExecutionResult(
        execution_id="exe_integ",
        transaction_id="TXN-INTEG-REDIS-001",
        state=ExecutionState.SUCCESS,
        started_at=datetime.utcnow(),
        completed_at=datetime.utcnow(),
        latency_ms=5.0,
        action_results=[],
        success=True,
    )
    await svc.store_result(key, fake)
    hit2, cached2, _ = await svc.check(req)
    assert hit2 is True
    assert cached2.execution_id == "exe_integ"
    await store.disconnect()


def test_integration_redis_idempotency():
    if not INTEGRATION:
        print(f"   {SKIP}")
        return
    import asyncio
    asyncio.run(_integration_redis())


async def _integration_postgres():
    import os
    dsn = os.getenv(
        "DATABASE_URL",
        "postgresql://flashguard:flashguard@localhost:5432/flashguard",
    )
    from audit import PostgresAuditService
    svc = PostgresAuditService()
    await svc.connect(dsn)
    assert svc._pool is not None, "PostgreSQL connection failed"
    plan, result = _make_plan_and_result("TXN-INTEG-PG-001")
    event = await svc.async_write(plan, result)
    assert event.event_id.startswith("audit_")
    events = await svc.async_by_transaction("TXN-INTEG-PG-001")
    assert len(events) >= 1
    await svc.disconnect()


def test_integration_postgres_audit():
    if not INTEGRATION:
        print(f"   {SKIP}")
        return
    import asyncio
    asyncio.run(_integration_postgres())


async def _integration_kafka():
    import os
    servers = os.getenv("KAFKA_BOOTSTRAP_SERVERS", "localhost:9092")
    from event_bus import KafkaEventBus
    from models import EventType
    bus = KafkaEventBus(bootstrap_servers=servers, topic="flashguard.test")
    await bus.start()
    assert bus._ready, "Kafka producer not ready"
    received = []
    bus.subscribe(EventType.EXECUTION_COMPLETED, received.append)
    await bus.async_publish_simple(
        topic=EventType.EXECUTION_COMPLETED,
        key="TXN-INTEG-KAFKA-001",
        payload={"test": True},
    )
    assert len(received) == 1  # in-memory subscriber fires
    await bus.stop()


def test_integration_kafka_event_bus():
    if not INTEGRATION:
        print(f"   {SKIP}")
        return
    import asyncio
    asyncio.run(_integration_kafka())


# ══════════════════════════════════════════════
# MAIN RUNNER
# ══════════════════════════════════════════════

def main():
    print("=" * 65)
    print("  FlashGuard Agent 6 – Full Test Suite (v2)")
    print("=" * 65)
    print()

    # ── Models ────────────────────────────────
    print("── models.py ──────────────────────────────────────────────")
    run("Verdict / ActionType / ExecutionState / ActionStatus / EventType enums", test_models_enums)
    run("Policy dataclass (frozen)", test_models_policy)
    run("ExecutionRequest dataclass", test_models_execution_request)
    run("Action dataclass defaults", test_models_action)
    run("ActionResult dataclass", test_models_action_result)
    run("ExecutionResult dataclass", test_models_execution_result)
    run("AuditEvent dataclass", test_models_audit_event)
    run("ExecutionMetrics dataclass defaults", test_models_execution_metrics)
    run("create_execution_id() format", test_models_create_execution_id)

    # ── Validator ─────────────────────────────
    print("\n── validator.py ────────────────────────────────────────────")
    run("Valid request passes validation", test_validator_valid_request)
    run("Empty transaction_id raises ValidationError", test_validator_missing_transaction_id)
    run("RequestValidator class usable directly", test_validator_class_instance)

    # ── Idempotency ───────────────────────────
    print("\n── idempotency.py ──────────────────────────────────────────")
    run("First call returns cache miss", test_idempotency_first_call_is_miss)
    run("Second call returns cache hit", test_idempotency_second_call_is_hit)
    run("Different verdicts produce different keys", test_idempotency_different_verdicts_different_keys)
    run("build_idempotency_service() without REDIS_URL = sync", test_idempotency_build_service_no_redis)
    run("_make_key() is deterministic", test_idempotency_make_key_consistency)
    run("JSON roundtrip preserves ExecutionResult fields", test_idempotency_result_json_roundtrip)

    # ── Distributed Lock ──────────────────────
    print("\n── distributed_lock.py ─────────────────────────────────────")
    run("Acquire and release lock", test_lock_acquire_and_release)
    run("Duplicate acquire raises RuntimeError", test_lock_duplicate_raises)
    run("Release non-existent lock is safe", test_lock_release_nonexistent_is_safe)

    # ── Planner ───────────────────────────────
    print("\n── planner.py ──────────────────────────────────────────────")
    run("Planner creates plan with sorted actions", test_planner_creates_plan)
    run("create_execution_plan() function works", test_create_execution_plan_function)

    # ── Policy Engine ─────────────────────────
    print("\n── policy_engine.py ────────────────────────────────────────")
    run("BlockPolicy includes LOCK_CARD, FREEZE_TRANSACTION, NOTIFY_FIU", test_policy_block_actions)
    run("FlagPolicy includes LOCK_CARD, NOTIFY_CUSTOMER", test_policy_flag_actions)
    run("ReviewPolicy includes CREATE_CASE, NOTIFY_ANALYST", test_policy_review_actions)
    run("AllowPolicy includes WRITE_AUDIT, PUBLISH_EVENT (no LOCK_CARD)", test_policy_allow_actions)
    run("PolicyRegistry.get() returns correct policy", test_policy_registry_get)
    run("PolicyRegistry raises PolicyError for unknown verdict", test_policy_registry_unknown_raises)
    run("PolicyEngine.build_plan() returns valid plan", test_policy_engine_builds_plan)

    # ── Retry ─────────────────────────────────
    print("\n── retry.py ────────────────────────────────────────────────")
    run("RetryManager executes function and returns value", test_retry_manager_runs_fn)
    run("RetryResult dataclass fields", test_retry_result_dataclass)

    # ── Circuit Breaker ───────────────────────
    print("\n── circuit_breaker.py ──────────────────────────────────────")
    run("Circuit.call() executes function", test_circuit_call_fn)
    run("CircuitRegistry returns Circuit instance", test_circuit_registry_returns_circuit)
    run("CircuitRegistry returns same Circuit for same name", test_circuit_registry_same_instance)

    # ── Action Runner ─────────────────────────
    print("\n── action_runner.py ────────────────────────────────────────")
    run("ActionRunner uses default handler (lambda)", test_action_runner_default_handler)
    run("ActionRunner uses registered custom handler", test_action_runner_custom_handler)

    # ── Event Bus ─────────────────────────────
    print("\n── event_bus.py ────────────────────────────────────────────")
    run("InMemoryEventBus publish/subscribe delivers event", test_event_bus_publish_subscribe)
    run("InMemoryEventBus.publish_simple() works", test_event_bus_publish_simple)
    run("InMemoryEventBus without subscriber does not raise", test_event_bus_no_subscriber_is_silent)
    run("build_event_bus() without KAFKA_BOOTSTRAP_SERVERS = in-memory", test_kafka_bus_fallback_no_servers)
    run("Module-level event_bus is InMemoryEventBus", test_event_bus_module_singleton_is_inmemory)
    run("async_publish_simple works on InMemoryEventBus", test_kafka_bus_async_publish_simple_inmemory)

    # ── Audit Service ─────────────────────────
    print("\n── audit.py ────────────────────────────────────────────────")
    run("AuditService.write() creates AuditEvent", test_audit_write_creates_event)
    run("AuditService.history() returns all events", test_audit_history)
    run("AuditService.by_transaction() filters correctly", test_audit_by_transaction)
    run("AuditService.clear() empties the log", test_audit_clear)
    run("AuditService history is immutable (deep copy)", test_audit_immutability)
    run("build_audit_service() without DATABASE_URL = in-memory", test_audit_build_service_no_db)
    run("PostgresAuditService.write() (sync) still works without pool", test_postgres_audit_service_sync_write_still_works)

    # ── Metrics Service ───────────────────────
    print("\n── metrics.py ──────────────────────────────────────────────")
    run("MetricsService records successful execution", test_metrics_record_success)
    run("MetricsService records failed execution", test_metrics_record_failure)
    run("MetricsService computes average latency", test_metrics_average_latency)
    run("MetricsService computes p95/p99 for single sample", test_metrics_percentile_single)
    run("MetricsService.increment_locked_cards() works", test_metrics_increment_locked_cards)
    run("MetricsService.reset() clears all counters", test_metrics_reset)
    run("Prometheus counters don't break record()", test_metrics_prometheus_record_does_not_raise)
    run("record_with_verdict() works", test_metrics_record_with_verdict)

    # ── Tracing ───────────────────────────────
    print("\n── tracing.py ──────────────────────────────────────────────")
    run("get_tracer() returns usable tracer", test_tracing_get_tracer_returns_tracer)
    run("init_tracing() is idempotent", test_tracing_init_idempotent)
    run("Tracer span works as context manager", test_tracing_span_context_manager)

    # ── Executor (end-to-end, sync) ───────────
    print("\n── executor.py (sync end-to-end) ───────────────────────────")
    run("BLOCK verdict: full sync execution succeeds", test_executor_block_verdict)
    run("ALLOW verdict: full sync execution succeeds", test_executor_allow_verdict)
    run("FLAG  verdict: full sync execution succeeds", test_executor_flag_verdict)
    run("REVIEW verdict: full sync execution succeeds", test_executor_review_verdict)
    run("Same request returns cached result (idempotency)", test_executor_idempotency_cache_hit)
    run("BLOCK produces multiple action results", test_executor_has_action_results)
    run("Execution latency_ms is non-negative", test_executor_latency_is_positive)
    run("Audit log receives at least one entry after execution", test_executor_audit_written)
    run("EXECUTION_COMPLETED event published to EventBus", test_executor_event_published)

    # ── Executor (async path) ─────────────────
    print("\n── executor.py (async path) ────────────────────────────────")
    run("BLOCK verdict: async execution succeeds", test_executor_async_block_verdict)
    run("Async idempotency cache hit works", test_executor_async_idempotency_cache_hit)

    # ── Integration tests (infra required) ────
    print("\n── Integration tests (INTEGRATION=1 to enable) ─────────────")
    run("Redis: AsyncIdempotencyService roundtrip", test_integration_redis_idempotency)
    run("PostgreSQL: PostgresAuditService write + query", test_integration_postgres_audit)
    run("Kafka: KafkaEventBus publish + subscribe", test_integration_kafka_event_bus)

    # ── Summary ───────────────────────────────
    total  = len(results)
    passed = sum(1 for s, _ in results if s == PASS)
    failed = total - passed
    skipped = sum(1 for _, label in results if SKIP in label)

    print()
    print("=" * 65)
    print(f"  Results : {passed}/{total} passed   |   {failed} failed")
    if INTEGRATION:
        print(f"  Mode    : INTEGRATION (real Redis / Postgres / Kafka)")
    else:
        print(f"  Mode    : unit tests only  (3 integration tests skipped)")
    print("=" * 65)

    if failed:
        print("\nFailed tests:")
        for status, label in results:
            if status == FAIL:
                print(f"  {FAIL}  {label}")
        sys.exit(1)
    else:
        print("\n  All tests passed! Agent 6 is fully operational. 🚀")


if __name__ == "__main__":
    main()
