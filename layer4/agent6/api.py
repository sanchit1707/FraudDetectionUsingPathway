"""
api.py
------

FastAPI REST API for FlashGuard Agent 6 – Execution Orchestrator.

Endpoints
---------
  POST /execute                   Execute a transaction verdict
  GET  /health                    Liveness probe
  GET  /ready                     Readiness probe
  GET  /audit/{transaction_id}    Fetch audit trail for a transaction
  GET  /metrics                   Redirect to Prometheus metrics port
  GET  /docs                      Swagger UI (auto-generated)
  GET  /redoc                     ReDoc UI (auto-generated)

Run with:
  python api.py

Or via uvicorn directly:
  uvicorn api:app --host 0.0.0.0 --port 8000 --reload

Environment variables (see .env.example):
  DATABASE_URL, REDIS_URL, KAFKA_BOOTSTRAP_SERVERS,
  OTLP_ENDPOINT, PROMETHEUS_PORT, API_HOST, API_PORT
"""

from __future__ import annotations

import logging
import os
from contextlib import asynccontextmanager
from datetime import datetime
from typing import Any, Dict, List, Optional

from fastapi import FastAPI, HTTPException, Path, Request, status
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse, RedirectResponse
from pydantic import BaseModel, Field, field_validator

# Load .env before anything else
try:
    from dotenv import load_dotenv
    load_dotenv()
except ImportError:
    pass  # python-dotenv optional

from models import (
    ActionStatus,
    ActionType,
    ExecutionRequest,
    ExecutionState,
    Policy,
    Verdict,
)
from container import container
from metrics import start_prometheus_server

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s  %(levelname)-8s  %(name)s  %(message)s",
)
logger = logging.getLogger("flashguard.api")


# ──────────────────────────────────────────────────────────────────────────────
# Pydantic request / response schemas
# ──────────────────────────────────────────────────────────────────────────────

class PolicySchema(BaseModel):
    id: str = Field("policy-default", example="policy-block-v1")
    version: str = Field("v1.0", example="v1.0")
    name: str = Field("DefaultPolicy", example="BlockPolicy")


class ExecutionRequestSchema(BaseModel):
    """
    Incoming execution request from an upstream fraud-detection agent.
    """
    transaction_id: str = Field(..., example="TXN-20240101-0001")
    account_id: str = Field(..., example="ACC-001")
    customer_id: str = Field(..., example="CUS-001")
    verdict: str = Field(..., example="BLOCK")
    confidence: float = Field(..., ge=0.0, le=1.0, example=0.97)
    risk_score: float = Field(..., ge=0.0, le=1.0, example=0.91)
    tier: int = Field(..., ge=1, le=4, example=1)
    policy: PolicySchema = Field(default_factory=PolicySchema)
    gateway_trace: str = Field("gateway", example="gw-trace-abc123")
    evidence: Dict[str, Any] = Field(default_factory=dict)
    metadata: Dict[str, Any] = Field(default_factory=dict)

    @field_validator("verdict")
    @classmethod
    def validate_verdict(cls, v: str) -> str:
        allowed = {e.value for e in Verdict}
        if v.upper() not in allowed:
            raise ValueError(f"verdict must be one of {allowed}")
        return v.upper()


class ActionResultSchema(BaseModel):
    action_type: str
    status: str
    latency_ms: float
    message: str
    retries: int
    response: Optional[Any]


class ExecutionResultSchema(BaseModel):
    execution_id: str
    transaction_id: str
    state: str
    started_at: datetime
    completed_at: Optional[datetime]
    latency_ms: float
    success: bool
    cached: bool
    message: str
    action_results: List[ActionResultSchema]


class AuditEventSchema(BaseModel):
    event_id: str
    execution_id: str
    transaction_id: str
    timestamp: datetime
    state: str
    actor: str
    description: str
    metadata: Dict[str, Any]


class HealthSchema(BaseModel):
    status: str
    service: str
    version: str
    timestamp: datetime


# ──────────────────────────────────────────────────────────────────────────────
# App lifespan – startup / shutdown
# ──────────────────────────────────────────────────────────────────────────────

@asynccontextmanager
async def lifespan(app: FastAPI):
    """Connect all async adapters on startup, disconnect on shutdown."""
    logger.info("FlashGuard Agent 6 – starting up…")
    await container.init()
    logger.info("FlashGuard Agent 6 – ready to serve requests")
    yield
    logger.info("FlashGuard Agent 6 – shutting down…")
    await container.shutdown()
    logger.info("FlashGuard Agent 6 – shutdown complete")


# ──────────────────────────────────────────────────────────────────────────────
# FastAPI application
# ──────────────────────────────────────────────────────────────────────────────

app = FastAPI(
    title="FlashGuard Agent 6 – Execution Orchestrator",
    description=(
        "Final execution layer of the FlashGuard fraud detection pipeline.\n\n"
        "Validates, deduplicates, plans, executes, audits, and publishes "
        "every transaction verdict as a safe, atomic operation."
    ),
    version="2.0.0",
    contact={
        "name": "FlashGuard Engineering",
        "url": "https://github.com/flashguard",
    },
    license_info={
        "name": "Educational / Portfolio",
    },
    lifespan=lifespan,
    docs_url="/docs",
    redoc_url="/redoc",
)

# CORS (allow all origins for demo – restrict in production)
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)


# ──────────────────────────────────────────────────────────────────────────────
# Request logging middleware
# ──────────────────────────────────────────────────────────────────────────────

@app.middleware("http")
async def log_requests(request: Request, call_next):
    start = datetime.utcnow()
    response = await call_next(request)
    latency_ms = (datetime.utcnow() - start).total_seconds() * 1000
    logger.info(
        "%s %s → %d  (%.1f ms)",
        request.method,
        request.url.path,
        response.status_code,
        latency_ms,
    )
    return response


# ──────────────────────────────────────────────────────────────────────────────
# Helpers
# ──────────────────────────────────────────────────────────────────────────────

def _to_execution_result_schema(result) -> ExecutionResultSchema:
    return ExecutionResultSchema(
        execution_id=result.execution_id,
        transaction_id=result.transaction_id,
        state=result.state.value,
        started_at=result.started_at,
        completed_at=result.completed_at,
        latency_ms=result.latency_ms,
        success=result.success,
        cached=result.cached,
        message=result.message,
        action_results=[
            ActionResultSchema(
                action_type=ar.action_type.value,
                status=ar.status.value,
                latency_ms=ar.latency_ms,
                message=ar.message,
                retries=ar.retries,
                response=ar.response,
            )
            for ar in result.action_results
        ],
    )


def _to_audit_event_schema(event) -> AuditEventSchema:
    return AuditEventSchema(
        event_id=event.event_id,
        execution_id=event.execution_id,
        transaction_id=event.transaction_id,
        timestamp=event.timestamp,
        state=event.state.value,
        actor=event.actor,
        description=event.description,
        metadata=event.metadata,
    )


# ──────────────────────────────────────────────────────────────────────────────
# Routes
# ──────────────────────────────────────────────────────────────────────────────

@app.get(
    "/health",
    response_model=HealthSchema,
    summary="Liveness probe",
    tags=["Operations"],
)
async def health():
    """Returns 200 OK if the service is alive."""
    return HealthSchema(
        status="ok",
        service="flashguard-agent6",
        version="2.0.0",
        timestamp=datetime.utcnow(),
    )


@app.get(
    "/ready",
    summary="Readiness probe",
    tags=["Operations"],
)
async def ready():
    """Returns 200 OK when all adapters are initialised."""
    checks: Dict[str, str] = {}

    # Redis
    if container.async_idempotency and hasattr(
        container.async_idempotency, "_redis"
    ):
        redis_store = container.async_idempotency._redis
        checks["redis"] = "up" if redis_store._client else "degraded"
    else:
        checks["redis"] = "in-memory"

    # PostgreSQL
    if container.async_audit and hasattr(container.async_audit, "_pool"):
        checks["postgres"] = "up" if container.async_audit._pool else "degraded"
    else:
        checks["postgres"] = "in-memory"

    # Kafka
    if container.async_event_bus and hasattr(container.async_event_bus, "_ready"):
        checks["kafka"] = "up" if container.async_event_bus._ready else "degraded"
    else:
        checks["kafka"] = "in-memory"

    return {"status": "ready", "adapters": checks, "timestamp": datetime.utcnow()}


@app.post(
    "/execute",
    response_model=ExecutionResultSchema,
    status_code=status.HTTP_200_OK,
    summary="Execute a transaction verdict",
    tags=["Execution"],
)
async def execute(body: ExecutionRequestSchema):
    """
    Execute a fraud verdict for a transaction.

    - Validates the request
    - Checks idempotency (returns cached result on duplicate)
    - Selects and runs the appropriate policy
    - Writes audit log
    - Publishes event to Kafka
    - Returns the full execution result
    """
    try:
        request = ExecutionRequest(
            transaction_id=body.transaction_id,
            account_id=body.account_id,
            customer_id=body.customer_id,
            verdict=Verdict(body.verdict),
            confidence=body.confidence,
            risk_score=body.risk_score,
            tier=body.tier,
            policy=Policy(
                id=body.policy.id,
                version=body.policy.version,
                name=body.policy.name,
            ),
            gateway_trace=body.gateway_trace,
            timestamp=datetime.utcnow(),
            evidence=body.evidence,
            metadata=body.metadata,
        )

        result = await container.executor.execute_async(
            request=request,
            async_idempotency=container.async_idempotency,
            async_audit=container.async_audit,
            async_event_bus=container.async_event_bus,
        )

        # Record metrics with verdict label
        container.metrics.record_with_verdict(result, body.verdict)

        return _to_execution_result_schema(result)

    except ValueError as exc:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail=str(exc),
        )
    except Exception as exc:
        logger.exception("Unexpected error during execution: %s", exc)
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Internal server error: {exc}",
        )


@app.get(
    "/audit/{transaction_id}",
    response_model=List[AuditEventSchema],
    summary="Get audit trail for a transaction",
    tags=["Audit"],
)
async def get_audit(
    transaction_id: str = Path(
        ...,
        example="TXN-20240101-0001",
        description="The transaction ID to look up",
    )
):
    """
    Returns all audit events for the given transaction ID.

    Events are returned in reverse chronological order (newest first).
    """
    audit = container.async_audit or container.audit

    if hasattr(audit, "async_by_transaction"):
        events = await audit.async_by_transaction(transaction_id)
    else:
        events = audit.by_transaction(transaction_id)

    return [_to_audit_event_schema(e) for e in events]


@app.get(
    "/metrics-snapshot",
    summary="In-memory metrics snapshot",
    tags=["Operations"],
)
async def metrics_snapshot():
    """
    Returns the current in-memory execution metrics snapshot.

    For the full Prometheus metrics endpoint, see port 8001 (or PROMETHEUS_PORT).
    """
    snap = container.metrics.snapshot()
    return {
        "executed": snap.executed,
        "successful": snap.successful,
        "failures": snap.failures,
        "cache_hits": snap.cache_hits,
        "retries": snap.retries,
        "locked_cards": snap.locked_cards,
        "average_latency_ms": snap.average_latency_ms,
        "p95_latency_ms": snap.p95_latency_ms,
        "p99_latency_ms": snap.p99_latency_ms,
    }


@app.get(
    "/",
    include_in_schema=False,
)
async def root():
    """Redirect root to the Swagger docs."""
    return RedirectResponse(url="/docs")


# ──────────────────────────────────────────────────────────────────────────────
# Entry point
# ──────────────────────────────────────────────────────────────────────────────

if __name__ == "__main__":
    import uvicorn
    uvicorn.run(
        "api:app",
        host=os.getenv("API_HOST", "0.0.0.0"),
        port=int(os.getenv("API_PORT", "8000")),
        reload=True,
        log_level="info",
    )
