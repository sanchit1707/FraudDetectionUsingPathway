"""
models.py
Core data models for Agent 6 Execution Orchestrator.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum
from typing import Any, Dict, List, Optional
from uuid import uuid4


class Verdict(str, Enum):
    ALLOW = "ALLOW"
    REVIEW = "REVIEW"
    FLAG = "FLAG"
    BLOCK = "BLOCK"


class ActionType(str, Enum):
    LOCK_CARD = "LOCK_CARD"
    FREEZE_TRANSACTION = "FREEZE_TRANSACTION"
    FREEZE_ACCOUNT = "FREEZE_ACCOUNT"
    CREATE_CASE = "CREATE_CASE"
    NOTIFY_CUSTOMER = "NOTIFY_CUSTOMER"
    NOTIFY_ANALYST = "NOTIFY_ANALYST"
    NOTIFY_FIU = "NOTIFY_FIU"
    WRITE_AUDIT = "WRITE_AUDIT"
    PUBLISH_EVENT = "PUBLISH_EVENT"
    UPDATE_METRICS = "UPDATE_METRICS"


class ExecutionState(str, Enum):
    RECEIVED = "RECEIVED"
    VALIDATED = "VALIDATED"
    DEDUPED = "DEDUPED"
    PLANNED = "PLANNED"
    EXECUTING = "EXECUTING"
    SUCCESS = "SUCCESS"
    FAILED = "FAILED"
    RETRYING = "RETRYING"
    DEAD_LETTER = "DEAD_LETTER"


class ActionStatus(str, Enum):
    PENDING = "PENDING"
    RUNNING = "RUNNING"
    SUCCESS = "SUCCESS"
    FAILED = "FAILED"
    SKIPPED = "SKIPPED"


class EventType(str, Enum):
    ACTION_EXECUTED = "action.executed"
    ACTION_FAILED = "action.failed"
    ACTION_SKIPPED = "action.skipped"
    TRANSACTION_LOCKED = "transaction.locked"
    TRANSACTION_FROZEN = "transaction.frozen"
    ACCOUNT_FROZEN = "account.frozen"
    CASE_CREATED = "case.created"
    CUSTOMER_NOTIFIED = "customer.notified"
    ANALYST_NOTIFIED = "analyst.notified"
    FIU_NOTIFIED = "fiu.notified"
    AUDIT_WRITTEN = "audit.written"
    METRICS_UPDATED = "metrics.updated"
    EXECUTION_COMPLETED = "execution.completed"
    EXECUTION_FAILED = "execution.failed"


@dataclass(frozen=True)
class Policy:
    id: str
    version: str
    name: str


@dataclass
class ExecutionRequest:
    transaction_id: str
    account_id: str
    customer_id: str
    verdict: Verdict
    confidence: float
    risk_score: float
    tier: int
    policy: Policy
    gateway_trace: str
    timestamp: datetime
    trace_id: str = field(default_factory=lambda: uuid4().hex)
    evidence: Dict[str, Any] = field(default_factory=dict)
    metadata: Dict[str, Any] = field(default_factory=dict)


@dataclass
class Action:
    action_type: ActionType
    priority: int
    payload: Dict[str, Any] = field(default_factory=dict)
    retryable: bool = True
    timeout_ms: int = 3000


@dataclass(frozen=True)
class ExecutionPlan:
    execution_id: str
    request: ExecutionRequest
    actions: List[Action]
    created_at: datetime
    policy_name: str


@dataclass
class ActionResult:
    action_type: ActionType
    status: ActionStatus
    latency_ms: float
    message: str
    retries: int = 0
    response: Optional[Any] = None


@dataclass
class ExecutionResult:
    execution_id: str
    transaction_id: str
    state: ExecutionState
    started_at: datetime
    completed_at: Optional[datetime]
    latency_ms: float
    action_results: List[ActionResult]
    cached: bool = False
    success: bool = False
    message: str = ""


@dataclass
class AuditEvent:
    event_id: str
    execution_id: str
    transaction_id: str
    timestamp: datetime
    state: ExecutionState
    actor: str
    description: str
    metadata: Dict[str, Any] = field(default_factory=dict)


@dataclass
class EventMessage:
    topic: EventType
    key: str
    payload: Dict[str, Any]
    timestamp: datetime


@dataclass
class ExecutionMetrics:
    executed: int = 0
    successful: int = 0
    failures: int = 0
    cache_hits: int = 0
    retries: int = 0
    locked_cards: int = 0
    average_latency_ms: float = 0.0
    p95_latency_ms: float = 0.0
    p99_latency_ms: float = 0.0


def create_execution_id() -> str:
    return f"exe_{uuid4().hex}"
