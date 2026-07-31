"""
gateway/main.py
---------------
FlashGuard Agentic Gateway — Main Entrypoint

Stitches ALL components:
  Pathway Pipeline (L0→L4) → LangGraph Orchestrator → Agent 6 Execution

Architecture:
  1. Pathway streaming pipeline runs in background thread
     - L0: CSV replay (ieee_transactions.csv)
     - L1: Enrich + geo-feature
     - L2: Bitmask + sliding window
     - L3: Rule engine (alert thresholds)
     - L4: ML fraud scoring (XGBoost + HST ensemble)
     → Writes high-score alerts to Redis Stream 'gateway:alerts'

  2. FastAPI REST server handles:
     - POST /submit    — manual transaction submission (for testing)
     - POST /execute   — direct Agent 6 execution bypass
     - GET  /health    — liveness
     - GET  /ready     — readiness (checks Redis + BDH)
     - GET  /metrics   — snapshot of processing stats

  3. Alert consumer: reads 'gateway:alerts' from Redis Stream
     → routes each alert through LangGraph orchestrator
     → sends result to Agent 6 /execute

Run via Docker: CMD in Dockerfile starts this.
"""

from __future__ import annotations

import asyncio
import json
import logging
import os
import sys
import threading
import time
from contextlib import asynccontextmanager
from datetime import datetime
from typing import Any, Dict, Optional

# ── Path setup for imports ────────────────────────────────────────────────────
BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, BASE_DIR)

import redis as redis_sync
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s  [Gateway]  %(levelname)-8s  %(message)s",
)
logger = logging.getLogger("flashguard.gateway")

# ── Config from env ───────────────────────────────────────────────────────────
REDIS_URL = os.getenv("REDIS_URL", "redis://redis:6379/0")
AGENT6_URL = os.getenv("AGENT6_URL", "http://agent6:8000")
BDH_URL = os.getenv("BDH_URL", "http://bdh_watchdog:8090")
ALERTS_STREAM  = "gateway:alerts"
DLQ_STREAM     = "gateway:dlq"          # Dead Letter Queue
OFFSET_KEY     = "gateway:consumer_offset"  # Pathway-style persistent offset

# ── Redis ─────────────────────────────────────────────────────────────────────
_redis: Optional[redis_sync.Redis] = None

def get_redis() -> redis_sync.Redis:
    global _redis
    if _redis is None:
        _redis = redis_sync.Redis.from_url(REDIS_URL, decode_responses=True)
    return _redis


# ── Stats ─────────────────────────────────────────────────────────────────────
stats = {
    "transactions_processed": 0,
    "escalated_to_llm": 0,
    "blocked": 0,
    "approved": 0,
    "held": 0,
    "errors": 0,
    "dlq_count": 0,
    "pending_reclaimed": 0,
    "started_at": datetime.utcnow().isoformat(),
}

# Per-message retry counter (in-memory; reset on restart — intentional)
_msg_retry_counts: Dict[str, int] = {}
MAX_RETRIES = 3
PENDING_IDLE_MS = 30_000   # Reclaim messages idle > 30s (were in-flight on last crash)

# ── LangGraph Orchestrator ────────────────────────────────────────────────────

def run_orchestrator(txn_input: Dict[str, Any]) -> Dict[str, Any]:
    """
    Run the LangGraph orchestrator for a single transaction.
    Returns the final state dict.
    """
    from orcestrator.graph import get_graph

    txn_id = txn_input.get("txn_id", "unknown")
    graph = get_graph()

    # Build initial state
    initial_state = {
        "txn_id": txn_input.get("txn_id", "unknown"),
        "cust_token": txn_input.get("account_id", "ACC_UNKNOWN"),
        "amount": float(txn_input.get("amount", 0)),
        "timestamp": int(time.time()),
        "priority": txn_input.get("priority", 3),
        "bitmask": txn_input.get("bitmask", 0),
        "features": {
            "amount": float(txn_input.get("amount", 0)),
            "rolling_spend_10m": float(txn_input.get("rolling_spend_10m", 0)),
            "txn_count_10m": int(txn_input.get("txn_count_10m", 1)),
        },
        # Optional pre-computed scores from Pathway
        "fraud_score": txn_input.get("ml_fraud_score"),
        "fraud_reasons": txn_input.get("fraud_reasons", []),
        "sanctions_hit": txn_input.get("sanctions_hit", False),
        "sanctions_conf": 0.0,
        "matched_entity": None,
        "ring_detected": False,
        "ring_size": 0,
        "ring_node": None,
        "final_tier": None,
        "final_action": None,
        "final_score": None,
        "llm_source": None,
        "llm_reasoning": None,
        "llm_verdict": None,
        "llm_tool_calls": [],
        "llm_escalated": False,
        "loop_count": 0,
        "killed": False,
        "error": None,
        "checkpoint_node": None,
        "groq_api_key": txn_input.get("groq_api_key"),
    }

    try:
        config = {"configurable": {"thread_id": txn_id}}
        final_state = graph.invoke(initial_state, config)
    except Exception as exc:
        logger.exception("[Orchestrator] LangGraph error for txn=%s: %s", txn_id, exc)
        final_state = {
            **initial_state,
            "final_score": 0.5,
            "final_tier": 2,
            "final_action": "hold",
            "error": str(exc),
        }

    return final_state


# ── Agent 6 Caller ─────────────────────────────────────────────────────────────

def call_agent6(txn_id: str, account_id: str, verdict: str, score: float, tier: int) -> Dict[str, Any]:
    """
    POST the final verdict to Agent 6's /execute endpoint.
    Returns Agent 6's response or a fallback dict.
    """
    import urllib.request
    import urllib.error

    payload = json.dumps({
        "transaction_id": txn_id,
        "account_id": account_id,
        "customer_id": account_id,
        "verdict": verdict.upper(),
        "confidence": score,
        "risk_score": score,
        "tier": tier,
        "policy": {"id": "policy-auto", "version": "v1.0", "name": "AutoPolicy"},
        "gateway_trace": f"gw-{txn_id}",
        "evidence": {},
        "metadata": {},
    }).encode()

    try:
        req = urllib.request.Request(
            f"{AGENT6_URL}/execute",
            data=payload,
            headers={"Content-Type": "application/json"},
            method="POST",
        )
        with urllib.request.urlopen(req, timeout=10) as resp:
            return json.loads(resp.read())
    except urllib.error.HTTPError as e:
        logger.warning("[Agent6] HTTP %d for txn=%s", e.code, txn_id)
        return {"status": "agent6_error", "code": e.code}
    except Exception as exc:
        logger.warning("[Agent6] Unreachable (%s) — verdict stored locally", exc)
        return {"status": "agent6_offline", "verdict": verdict, "txn_id": txn_id}


# ── Full Pipeline (Pathway alert → Orchestrator → Agent 6) ───────────────────

def process_alert(alert_data: Dict[str, Any]) -> Dict[str, Any]:
    """Process a single fraud alert through the full pipeline."""
    txn_id = alert_data.get("txn_id", "unknown")
    logger.info("[Pipeline] Processing txn=%s", txn_id)

    start_ms = time.monotonic() * 1000

    # Step 1: LangGraph orchestration
    final_state = run_orchestrator(alert_data)

    action = final_state.get("final_action", "hold")
    score = final_state.get("final_score", 0.5)
    tier = final_state.get("final_tier", 2)
    llm_escalated = final_state.get("llm_escalated", False)

    # Map action → verdict for Agent 6
    verdict_map = {"decline": "BLOCK", "hold": "FLAG", "approve": "ALLOW"}
    verdict = verdict_map.get(action, "FLAG")

    # Step 2: Agent 6 execution
    account_id = alert_data.get("account_id", txn_id)
    a6_result = call_agent6(txn_id, account_id, verdict, score, tier)

    elapsed_ms = (time.monotonic() * 1000) - start_ms

    # Update stats
    stats["transactions_processed"] += 1
    if llm_escalated:
        stats["escalated_to_llm"] += 1
    if action == "decline":
        stats["blocked"] += 1
    elif action == "approve":
        stats["approved"] += 1
    else:
        stats["held"] += 1

    result = {
        "txn_id": txn_id,
        "final_action": action,
        "final_score": score,
        "final_tier": tier,
        "verdict": verdict,
        "llm_escalated": llm_escalated,
        "llm_verdict": final_state.get("llm_verdict"),
        "llm_reasoning": final_state.get("llm_reasoning"),
        "llm_tool_calls": final_state.get("llm_tool_calls"),
        "agent6_result": a6_result,
        "elapsed_ms": round(elapsed_ms, 2),
    }

    logger.info(
        "[Pipeline] txn=%s → %s (score=%.3f, llm=%s, %.0fms)",
        txn_id, action.upper(), score, llm_escalated, elapsed_ms,
    )

    # Emit final result to stream
    try:
        r = get_redis()
        r.xadd(
            "pathway:events",
            {
                "event_type": "pipeline_result",
                "txn_id": txn_id,
                "source": "gateway",
                "timestamp": str(time.time()),
                "payload": json.dumps(result),
            },
            maxlen=50000,
            approximate=True,
        )
    except Exception:
        pass

    return result


# ── Pathway Pipeline Thread ───────────────────────────────────────────────────

def run_pathway_pipeline():
    """
    Runs the Pathway streaming pipeline (L0→L4) in a background thread.
    High-scoring alerts are written to 'gateway:alerts' Redis Stream
    for the alert consumer to pick up.

    This uses Pathway's incremental computation engine running inside Docker.
    """
    try:
        import pathway as pw
        from layer0.transaction_connector import get_transaction_stream
        from layer1.prefetcher import build_enriched_stream
        from layer2.bitmask import compute_flags, apply_bitmask
        from layer2.state_window_engine import build_state_window_stream
        from layer3.decision_engine import evaluate_fraud_rules
        from layer4.fraud_scorer import apply_fraud_scoring

        logger.info("[Pathway] Starting pipeline...")

        # L0 → L1: Ingest + Enrich
        enriched = build_enriched_stream(mode="demo")

        # L2a: Compute Flags
        flags_stream = compute_flags(enriched)

        # L2b: Sliding window (10-min)
        windowed = build_state_window_stream(flags_stream)

        # L2c: Bitmask
        bitmask_stream = apply_bitmask(windowed)

        # L3: Rule engine
        alerts = evaluate_fraud_rules(bitmask_stream)

        # L4: ML scoring
        scored = apply_fraud_scoring(alerts)

        # Emit high-score alerts to Redis Stream via Pathway UDF
        r_client = get_redis()

        @pw.udf
        def emit_alert_to_redis(
            account_id: str,
            amount: float,
            ml_fraud_score: float,
            rolling_spend_10m: float,
            txn_count_10m: float,
            is_fraudulent: bool,
            active_threats: str,
            bitmask: int,
        ) -> int:
            if ml_fraud_score > 0.35 or is_fraudulent:
                alert = {
                    "txn_id": f"TXN_{account_id}_{int(time.time()*1000)}",
                    "account_id": account_id,
                    "amount": amount,
                    "ml_fraud_score": ml_fraud_score,
                    "rolling_spend_10m": rolling_spend_10m,
                    "txn_count_10m": txn_count_10m,
                    "is_fraudulent": is_fraudulent,
                    "active_threats": active_threats,
                    "bitmask": bitmask,
                }
                try:
                    r_client.xadd(
                        ALERTS_STREAM,
                        {"data": json.dumps(alert)},
                        maxlen=10000,
                        approximate=True,
                    )
                except Exception:
                    pass
            return 1

        scored.select(
            _emitted=emit_alert_to_redis(
                pw.this.account_id,
                pw.this.amount,
                pw.this.ml_fraud_score,
                pw.this.rolling_spend_10m,
                pw.this.txn_count_10m,
                pw.this.is_fraudulent,
                pw.this.active_threats,
                pw.this.bitmask,
            )
        )

        logger.info("[Pathway] Pipeline running — streaming transactions from CSV")
        pw.run()

    except Exception as exc:
        logger.error("[Pathway] Pipeline crashed: %s", exc)
        logger.warning("[Pathway] Running in REST-only mode (no Pathway streaming)")


# ── Dead Letter Queue helpers ─────────────────────────────────────────────────

def _send_to_dlq(r: redis_sync.Redis, msg_id: str, msg_data: dict, error: str) -> None:
    """
    Write a permanently-failed message to the Dead Letter Queue stream.
    Includes full original payload + error context for later inspection / replay.
    """
    try:
        r.xadd(
            DLQ_STREAM,
            {
                "original_id":  msg_id,
                "data":         msg_data.get("data", "{}"),
                "error":        error[:500],
                "failed_at":    str(time.time()),
                "retries":      str(MAX_RETRIES),
            },
            maxlen=5000,
            approximate=True,
        )
        stats["dlq_count"] += 1
        logger.error(
            "[DLQ] msg_id=%s sent to DLQ after %d retries — %s",
            msg_id, MAX_RETRIES, error[:120],
        )
    except Exception as dlq_exc:
        logger.error("[DLQ] Failed to write DLQ entry: %s", dlq_exc)


def _process_one_message(
    r: redis_sync.Redis,
    consumer_group: str,
    msg_id: str,
    msg_data: dict,
) -> None:
    """
    Process a single stream message with retry tracking and DLQ fallback.
    On success  → XACK + clear retry counter.
    On failure  → increment counter; after MAX_RETRIES send to DLQ + XACK (remove from PEL).
    """
    try:
        alert = json.loads(msg_data.get("data", "{}"))
        process_alert(alert)
        # ✅ Success — acknowledge and clear retry counter
        r.xack(ALERTS_STREAM, consumer_group, msg_id)
        _msg_retry_counts.pop(msg_id, None)

        # 💾 Pathway-style offset persistence: save last successfully processed ID
        r.set(OFFSET_KEY, msg_id)

    except Exception as exc:
        _msg_retry_counts[msg_id] = _msg_retry_counts.get(msg_id, 0) + 1
        retries = _msg_retry_counts[msg_id]
        stats["errors"] += 1

        if retries >= MAX_RETRIES:
            # ☠️ Permanently failed — move to DLQ and ACK so it leaves PEL
            _send_to_dlq(r, msg_id, msg_data, str(exc))
            r.xack(ALERTS_STREAM, consumer_group, msg_id)
            _msg_retry_counts.pop(msg_id, None)
        else:
            logger.warning(
                "[AlertConsumer] msg_id=%s failed (attempt %d/%d): %s — will retry",
                msg_id, retries, MAX_RETRIES, exc,
            )
            # Do NOT XACK — message stays in PEL and will be reclaimed next cycle


# ── Alert Consumer Thread ─────────────────────────────────────────────────────

def alert_consumer_thread():
    """
    Crash-safe alert consumer.

    On every startup:
      1. Creates consumer group if missing (idempotent).
      2. Uses XAUTOCLAIM to reclaim any messages that were in-flight when the
         gateway last crashed (pending idle > PENDING_IDLE_MS ms).
         This is the Pathway-style "resume from last offset" pattern applied
         to Redis Streams.
      3. Then enters the normal XREADGROUP loop for new messages.

    Retry / DLQ:
      - Each message is attempted up to MAX_RETRIES times.
      - After MAX_RETRIES failures the message is written to gateway:dlq
        and removed from the Pending Entries List (XACK'd) so it can't block
        the consumer forever.
    """
    CONSUMER_GROUP = "gateway_consumer_group"
    CONSUMER_NAME  = "gateway_worker_1"

    r = get_redis()

    # ── Step 1: Ensure consumer group exists ──────────────────────────────────
    try:
        r.xgroup_create(ALERTS_STREAM, CONSUMER_GROUP, id="0", mkstream=True)
        logger.info("[AlertConsumer] Consumer group created")
    except Exception:
        pass  # Already exists — fine

    # ── Step 2: XAUTOCLAIM — reclaim crash-orphaned pending messages ──────────
    # Any message that was delivered but not ACK'd for > PENDING_IDLE_MS ms
    # was in-flight when the previous gateway instance crashed.
    # We re-claim and re-process them now, preventing permanent message loss.
    try:
        autoclaim_result = r.xautoclaim(
            ALERTS_STREAM,
            CONSUMER_GROUP,
            CONSUMER_NAME,
            min_idle_time=PENDING_IDLE_MS,
            start_id="0-0",
            count=100,
        )
        # xautoclaim returns (next_start_id, messages, deleted_ids)
        reclaimed_msgs = autoclaim_result[1] if isinstance(autoclaim_result, (list, tuple)) else []
        if reclaimed_msgs:
            logger.warning(
                "[AlertConsumer] STARTUP: reclaimed %d crash-orphaned messages from PEL",
                len(reclaimed_msgs),
            )
            stats["pending_reclaimed"] += len(reclaimed_msgs)
            for msg_id, msg_data in reclaimed_msgs:
                _process_one_message(r, CONSUMER_GROUP, msg_id, msg_data)
        else:
            logger.info("[AlertConsumer] STARTUP: no pending messages to reclaim ✓")
    except Exception as exc:
        # XAUTOCLAIM not available on very old Redis — log and continue
        logger.warning("[AlertConsumer] XAUTOCLAIM unavailable (%s) — skipping PEL reclaim", exc)

    logger.info("[AlertConsumer] Listening on stream '%s'", ALERTS_STREAM)

    # ── Step 3: Normal consume loop ───────────────────────────────────────────
    from concurrent.futures import ThreadPoolExecutor

    # Using max_workers=10 so we can process multiple stream chunks simultaneously
    executor = ThreadPoolExecutor(max_workers=10)

    while True:
        try:
            messages = r.xreadgroup(
                CONSUMER_GROUP,
                CONSUMER_NAME,
                {ALERTS_STREAM: ">"},
                count=5,
                block=1000,
            )
            if not messages:
                continue

            futures = []
            for _, stream_messages in messages:
                for msg_id, msg_data in stream_messages:
                    # Submit to threadpool so LangGraph can execute concurrently
                    futures.append(
                        executor.submit(_process_one_message, r, CONSUMER_GROUP, msg_id, msg_data)
                    )
            
            # Wait for all to complete before getting the next chunk
            for f in futures:
                f.result()

        except redis.exceptions.ConnectionError:
            logger.warning("[AlertConsumer] Redis disconnected — retrying in 5s")
            time.sleep(5)
        except Exception as exc:
            logger.error("[AlertConsumer] Unexpected: %s", exc)
            time.sleep(1)


import redis.exceptions


# ── FastAPI App ────────────────────────────────────────────────────────────────

@asynccontextmanager
async def lifespan(app: FastAPI):
    # Start Pathway pipeline in background thread
    pathway_thread = threading.Thread(target=run_pathway_pipeline, daemon=True)
    pathway_thread.start()

    # Start alert consumer thread
    consumer_thread = threading.Thread(target=alert_consumer_thread, daemon=True)
    consumer_thread.start()

    logger.info("🚀 FlashGuard Gateway started")
    yield
    logger.info("🛑 FlashGuard Gateway shutting down")


app = FastAPI(
    title="FlashGuard Agentic Gateway",
    description="Pathway-powered fraud detection gateway with LLM escalation",
    version="2.0.0",
    lifespan=lifespan,
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)


class TransactionRequest(BaseModel):
    txn_id: str
    account_id: str
    amount: float
    rolling_spend_10m: float = 0.0
    txn_count_10m: int = 1
    bitmask: int = 0
    ml_fraud_score: Optional[float] = None
    is_fraudulent: bool = False
    active_threats: str = "clean"
    sanctions_hit: bool = False
    groq_api_key: Optional[str] = None


@app.get("/health")
def health():
    return {
        "status": "ok",
        "service": "flashguard-gateway",
        "version": "2.0.0",
        "timestamp": datetime.utcnow().isoformat(),
    }


@app.get("/ready")
def ready():
    checks = {}
    try:
        get_redis().ping()
        checks["redis"] = "up"
    except Exception:
        checks["redis"] = "down"

    import urllib.request
    try:
        urllib.request.urlopen(f"{BDH_URL}/health", timeout=2)
        checks["bdh"] = "up"
    except Exception:
        checks["bdh"] = "down"

    all_up = all(v == "up" for v in checks.values())
    return {"status": "ready" if all_up else "degraded", "checks": checks}


@app.post("/submit")
def submit_transaction(req: TransactionRequest):
    """
    Submit a transaction for fraud analysis.
    Runs through LangGraph orchestrator synchronously and returns verdict.
    """
    alert = req.dict()
    result = process_alert(alert)
    return result


@app.get("/metrics")
def metrics():
    return stats


@app.get("/dlq")
def get_dlq(n: int = 50):
    """
    Inspect the Dead Letter Queue — messages that failed MAX_RETRIES times.
    Returns the last N entries with original payload and error context.
    """
    try:
        r = get_redis()
        raw = r.xrevrange(DLQ_STREAM, count=n)
        entries = []
        for msg_id, data in raw:
            try:
                payload = json.loads(data.get("data", "{}"))
            except Exception:
                payload = {}
            entries.append({
                "dlq_id":      msg_id,
                "original_id": data.get("original_id"),
                "failed_at":   data.get("failed_at"),
                "retries":     data.get("retries"),
                "error":       data.get("error"),
                "payload":     payload,
            })
        return {"count": len(entries), "entries": entries}
    except Exception as exc:
        return {"error": str(exc)}


@app.post("/dlq/retry")
def retry_dlq_entry(dlq_id: str):
    """
    Replay a single DLQ entry — re-submit its payload through the pipeline.
    On success, delete it from the DLQ stream.
    """
    try:
        r = get_redis()
        raw = r.xrange(DLQ_STREAM, min=dlq_id, max=dlq_id, count=1)
        if not raw:
            return {"error": f"DLQ entry {dlq_id} not found"}

        _, data = raw[0]
        try:
            alert = json.loads(data.get("data", "{}"))
        except Exception:
            return {"error": "Cannot parse DLQ payload"}

        result = process_alert(alert)

        # Remove from DLQ on successful replay
        r.xdel(DLQ_STREAM, dlq_id)
        stats["dlq_count"] = max(0, stats["dlq_count"] - 1)

        logger.info("[DLQ] Replayed %s successfully → %s", dlq_id, result.get("final_action"))
        return {"status": "replayed", "result": result}
    except Exception as exc:
        return {"error": str(exc)}


@app.get("/stream/recent")
def recent_events(n: int = 20):
    """Read the last N events from pathway:events stream (for telemetry)."""
    try:
        r = get_redis()
        raw = r.xrevrange("pathway:events", count=n)
        events = []
        for msg_id, data in raw:
            try:
                payload = json.loads(data.get("payload", "{}"))
            except Exception:
                payload = {}
            events.append({
                "id": msg_id,
                "event_type": data.get("event_type"),
                "txn_id": data.get("txn_id"),
                "source": data.get("source"),
                "payload": payload,
            })
        return {"count": len(events), "events": events}
    except Exception as exc:
        return {"error": str(exc)}


if __name__ == "__main__":
    import uvicorn
    uvicorn.run(
        "main:app",
        host="0.0.0.0",
        port=int(os.getenv("GATEWAY_PORT", "8080")),
        log_level="info",
        reload=False,
    )
