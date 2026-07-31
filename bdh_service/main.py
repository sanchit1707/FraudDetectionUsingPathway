"""
bdh_service/main.py
-------------------
BDH (Behavioral Drift and Hallucination) Watchdog
— Standalone FastAPI microservice —

This is the OUT-OF-BAND watchdog described in the PS rubric:
  "isolated, low-latency asynchronous microservice... sniffing the
   active Pathway event stream out-of-band"

Two responsibilities:
1. HTTP POST /audit  — pre-flight validation for every LLM tool call
   Called by the gateway's LangGraph Node 4 BEFORE executing any tool.
   Returns ALLOW or BLOCK with reason.

2. Background stream consumer — reads `pathway:events` Redis Stream
   via XREAD consumer group, logs all events, emits alerts for
   SCHEMA_VIOLATION / INFINITE_LOOP / IDEMPOTENCY events.
"""

import hashlib
import json
import logging
import os
import threading
import time
from typing import Any, Dict

import redis
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel, ValidationError, Field, constr

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s  [BDH]  %(levelname)-8s  %(message)s",
)
logger = logging.getLogger("flashguard.bdh")

# ── Redis ─────────────────────────────────────────────────────────────────────
REDIS_URL = os.getenv("REDIS_URL", "redis://redis:6379/0")
STREAM_KEY = "pathway:events"
CONSUMER_GROUP = "bdh_watchdog_group"
CONSUMER_NAME = "bdh_worker_1"

_redis_client = None

def get_redis():
    global _redis_client
    if _redis_client is None:
        _redis_client = redis.Redis.from_url(REDIS_URL, decode_responses=True)
    return _redis_client


# ── BDH Schema Definitions ───────────────────────────────────────────────────

class GetAccountDetailsSchema(BaseModel):
    account_id: constr(min_length=1, max_length=100)
    reason: constr(min_length=1, max_length=1000)


class QueryComplianceRulesSchema(BaseModel):
    search_query: constr(min_length=1, max_length=1000)


class BlockAccountSchema(BaseModel):
    account_id: constr(min_length=1, max_length=100)
    reason: constr(min_length=1, max_length=1000)


class EscalateSchema(BaseModel):
    transaction_id: constr(min_length=1, max_length=100)
    risk_summary: constr(min_length=1, max_length=2000)


ALLOWED_TOOLS = {
    "get_account_details": GetAccountDetailsSchema,
    "query_compliance_rules": QueryComplianceRulesSchema,
    "block_account": BlockAccountSchema,
    "escalate_to_investigator": EscalateSchema,
}

CRITICAL_TOOLS = ["block_account", "escalate_to_investigator"]


# ── Per-session State ─────────────────────────────────────────────────────────

class SessionState:
    def __init__(self, target_account_id: str):
        self.target_account_id = target_account_id
        self.tool_call_count = 0
        self.last_tool_hash = None
        self.repeat_count = 0
        self.executed_critical_actions = []

    def to_dict(self):
        return {
            "target_account_id": self.target_account_id,
            "tool_call_count": self.tool_call_count,
            "last_tool_hash": self.last_tool_hash,
            "repeat_count": self.repeat_count,
            "executed_critical_actions": self.executed_critical_actions,
        }

    @classmethod
    def from_dict(cls, data: dict):
        s = cls(data.get("target_account_id", ""))
        s.tool_call_count = data.get("tool_call_count", 0)
        s.last_tool_hash = data.get("last_tool_hash")
        s.repeat_count = data.get("repeat_count", 0)
        s.executed_critical_actions = data.get("executed_critical_actions", [])
        return s


def _get_session(anomaly_id: str, target_account: str) -> SessionState:
    r = get_redis()
    raw = r.get(f"bdh:session:{anomaly_id}")
    if raw:
        return SessionState.from_dict(json.loads(raw))
    return SessionState(target_account_id=target_account)


def _save_session(anomaly_id: str, session: SessionState) -> None:
    r = get_redis()
    r.setex(f"bdh:session:{anomaly_id}", 300, json.dumps(session.to_dict()))


# ── Core Audit Logic ─────────────────────────────────────────────────────────

def audit_llm_tool_call(
    anomaly_id: str,
    target_account: str,
    tool_name: str,
    tool_args: Dict[str, Any],
) -> Dict[str, str]:
    """
    5-rule deterministic audit. Returns {"status": "ALLOW"} or {"status": "BLOCK", "reason": "..."}.
    """
    session = _get_session(anomaly_id, target_account)
    session.tool_call_count += 1

    logger.info(
        "👁️  Auditing tool='%s' anomaly=%s step=%d",
        tool_name, anomaly_id, session.tool_call_count,
    )

    def finish(status, reason):
        _save_session(anomaly_id, session)
        return {"status": status, "reason": reason}

    # ── Rule 1: Context Exhaustion ────────────────────────────────────────────
    if session.tool_call_count > 5:
        reason = "CONTEXT_EXHAUSTION: LLM exceeded max 5 steps. Forcing escalation to human."
        _emit_bdh_alert(anomaly_id, "CONTEXT_EXHAUSTION", tool_name, reason)
        return finish("BLOCK", reason)

    # ── Rule 2: Schema Validation ─────────────────────────────────────────────
    if tool_name not in ALLOWED_TOOLS:
        reason = f"SCHEMA_VIOLATION: Hallucinated tool '{tool_name}' not in registry."
        _emit_bdh_alert(anomaly_id, "SCHEMA_VIOLATION", tool_name, reason)
        return finish("BLOCK", reason)

    try:
        ALLOWED_TOOLS[tool_name](**tool_args)
    except ValidationError as e:
        error_msg = "; ".join([f"{err['loc'][0]}: {err['msg']}" for err in e.errors()])
        reason = f"SCHEMA_VIOLATION: Invalid args for '{tool_name}'. Errors: {error_msg}"
        _emit_bdh_alert(anomaly_id, "SCHEMA_VIOLATION", tool_name, reason)
        return finish("BLOCK", reason)

    # ── Rule 3: State Drift ───────────────────────────────────────────────────
    if "account_id" in tool_args and tool_args["account_id"] != session.target_account_id:
        reason = (
            f"STATE_DRIFT: LLM targeted {tool_args['account_id']} "
            f"but anomaly is for {session.target_account_id}."
        )
        _emit_bdh_alert(anomaly_id, "STATE_DRIFT", tool_name, reason)
        return finish("BLOCK", reason)

    # ── Rule 4: Infinite Loop ─────────────────────────────────────────────────
    call_sig = f"{tool_name}_{json.dumps(tool_args, sort_keys=True)}"
    call_hash = hashlib.md5(call_sig.encode()).hexdigest()

    if call_hash == session.last_tool_hash:
        session.repeat_count += 1
    else:
        session.repeat_count = 1
        session.last_tool_hash = call_hash

    if session.repeat_count >= 3:
        reason = "INFINITE_LOOP: LLM called exact same tool 3x without progress."
        _emit_bdh_alert(anomaly_id, "INFINITE_LOOP", tool_name, reason)
        return finish("BLOCK", reason)

    # ── Rule 5: Idempotency ───────────────────────────────────────────────────
    if tool_name in CRITICAL_TOOLS:
        if tool_name in session.executed_critical_actions:
            reason = f"IDEMPOTENCY_VIOLATION: '{tool_name}' already executed for anomaly {anomaly_id}."
            _emit_bdh_alert(anomaly_id, "IDEMPOTENCY_VIOLATION", tool_name, reason)
            return finish("BLOCK", reason)
        if tool_name not in session.executed_critical_actions:
            session.executed_critical_actions.append(tool_name)

    logger.info("✅ ALLOW  tool='%s' anomaly=%s", tool_name, anomaly_id)
    return finish("ALLOW", "PASSED_ALL_5_CHECKS")


def _emit_bdh_alert(anomaly_id: str, rule: str, tool_name: str, reason: str) -> None:
    """Write alert to pathway:events stream so it's visible in telemetry."""
    try:
        r = get_redis()
        r.xadd(
            STREAM_KEY,
            {
                "event_type": "bdh_alert",
                "txn_id": anomaly_id,
                "source": "bdh_watchdog",
                "timestamp": str(time.time()),
                "payload": json.dumps({
                    "rule": rule,
                    "tool_name": tool_name,
                    "reason": reason,
                    "severity": "HIGH",
                }),
            },
            maxlen=50000,
            approximate=True,
        )
    except Exception as exc:
        logger.warning("Stream emit failed: %s", exc)


# ── Background Stream Consumer ────────────────────────────────────────────────

def _ensure_consumer_group():
    try:
        r = get_redis()
        r.xgroup_create(STREAM_KEY, CONSUMER_GROUP, id="0", mkstream=True)
        logger.info("Created consumer group '%s'", CONSUMER_GROUP)
    except redis.exceptions.ResponseError as e:
        if "BUSYGROUP" in str(e):
            pass  # Group already exists
        else:
            logger.warning("Consumer group error: %s", e)


def _stream_consumer_thread():
    """
    Background thread: reads pathway:events stream via XREAD consumer group.
    This is the out-of-band consumption described in the rubric.
    """
    _ensure_consumer_group()
    logger.info("🔍 BDH stream consumer started (group=%s)", CONSUMER_GROUP)

    r = get_redis()
    alert_count = 0

    while True:
        try:
            messages = r.xreadgroup(
                CONSUMER_GROUP,
                CONSUMER_NAME,
                {STREAM_KEY: ">"},
                count=10,
                block=2000,  # 2s block timeout
            )

            if not messages:
                continue

            for stream_name, stream_messages in messages:
                for msg_id, msg_data in stream_messages:
                    event_type = msg_data.get("event_type", "unknown")
                    txn_id = msg_data.get("txn_id", "?")

                    # Log all events
                    logger.debug("[STREAM] %s txn=%s", event_type, txn_id)

                    # Special handling for BDH alerts (self-emitted alerts)
                    if event_type == "bdh_alert":
                        alert_count += 1
                        try:
                            payload = json.loads(msg_data.get("payload", "{}"))
                            logger.warning(
                                "🚨 BDH ALERT #%d | rule=%s | tool=%s | txn=%s",
                                alert_count,
                                payload.get("rule"),
                                payload.get("tool_name"),
                                txn_id,
                            )
                        except Exception:
                            pass

                    # ACK the message
                    r.xack(STREAM_KEY, CONSUMER_GROUP, msg_id)

        except redis.exceptions.ConnectionError:
            logger.warning("Redis connection lost — retrying in 5s")
            time.sleep(5)
        except Exception as exc:
            logger.error("Stream consumer error: %s", exc)
            time.sleep(2)




# ── FastAPI App ────────────────────────────────────────────────────────────────

app = FastAPI(
    title="FlashGuard BDH Watchdog",
    description="Behavioral Drift & Hallucination microservice — out-of-band LLM guard",
    version="1.0.0",
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)


class AuditRequest(BaseModel):
    anomaly_id: str
    target_account: str
    tool_name: str
    tool_args: Dict[str, Any]


class AuditResponse(BaseModel):
    status: str      # "ALLOW" | "BLOCK"
    reason: str


@app.on_event("startup")
def startup_event():
    t = threading.Thread(target=_stream_consumer_thread, daemon=True)
    t.start()
    logger.info("BDH Watchdog started on port 8090")


@app.post("/audit", response_model=AuditResponse)
def audit_endpoint(req: AuditRequest) -> AuditResponse:
    result = audit_llm_tool_call(
        anomaly_id=req.anomaly_id,
        target_account=req.target_account,
        tool_name=req.tool_name,
        tool_args=req.tool_args,
    )
    return AuditResponse(status=result["status"], reason=result.get("reason", ""))


@app.get("/health")
def health():
    return {"status": "ok", "service": "bdh_watchdog", "version": "1.0.0"}


@app.get("/sessions")
def list_sessions():
    """Debug endpoint: show active sessions and their states."""
    r = get_redis()
    keys = r.keys("bdh:session:*")
    results = {}
    for key in keys:
        sid = key.replace("bdh:session:", "")
        raw = r.get(key)
        if raw:
            try:
                s = SessionState.from_dict(json.loads(raw))
                results[sid] = {
                    "target_account": s.target_account_id,
                    "tool_calls": s.tool_call_count,
                    "executed_critical": s.executed_critical_actions,
                    "repeat_count": s.repeat_count,
                }
            except Exception:
                pass
    return results


@app.delete("/sessions/{anomaly_id}")
def clear_session(anomaly_id: str):
    """Clear a session after transaction is complete."""
    r = get_redis()
    r.delete(f"bdh:session:{anomaly_id}")
    return {"cleared": anomaly_id}


if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8090, log_level="info")
