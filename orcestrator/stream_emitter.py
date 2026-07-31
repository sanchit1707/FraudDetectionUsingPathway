"""
orcestrator/stream_emitter.py
-----------------------------
Emits immutable events to the Pathway event stream (Redis Stream).

Every prompt, thought, tool invocation, and BDH decision becomes an
append-only event in the `pathway:events` Redis Stream.

The BDH watchdog service subscribes to this stream out-of-band via XREAD.
"""

import json
import logging
import os
import time
from typing import Any, Dict, Optional

logger = logging.getLogger(__name__)

STREAM_KEY = "pathway:events"
_redis_client = None


def _get_redis():
    global _redis_client
    if _redis_client is None:
        import redis
        url = os.getenv("REDIS_URL", "redis://redis:6379/0")
        _redis_client = redis.Redis.from_url(url, decode_responses=True)
    return _redis_client


def emit_event(
    event_type: str,
    txn_id: str,
    payload: Dict[str, Any],
    source: str = "gateway",
) -> None:
    """
    Append an immutable event to the Pathway Redis Stream.

    Args:
        event_type: e.g. "node_enter", "tool_call", "bdh_decision", "llm_thought"
        txn_id: Transaction ID for correlation
        payload: Arbitrary event data
        source: Which service emitted this event
    """
    event = {
        "event_type": event_type,
        "txn_id": txn_id,
        "source": source,
        "timestamp": time.time(),
        "payload": json.dumps(payload),
    }
    try:
        r = _get_redis()
        msg_id = r.xadd(STREAM_KEY, event, maxlen=50000, approximate=True)
        logger.debug("[Stream] %s → %s (msg_id=%s)", event_type, txn_id, msg_id)
    except Exception as exc:
        # Never let stream emission crash the pipeline
        logger.warning("[Stream] Emit failed (%s) — event dropped: %s", exc, event_type)


def emit_node_enter(txn_id: str, node_name: str, state_summary: Dict[str, Any]) -> None:
    emit_event("node_enter", txn_id, {"node": node_name, "state": state_summary})


def emit_node_exit(txn_id: str, node_name: str, result_summary: Dict[str, Any]) -> None:
    emit_event("node_exit", txn_id, {"node": node_name, "result": result_summary})


def emit_tool_call(
    txn_id: str,
    tool_name: str,
    tool_args: Dict[str, Any],
    bdh_decision: str,
    bdh_reason: str,
) -> None:
    emit_event(
        "tool_call",
        txn_id,
        {
            "tool_name": tool_name,
            "tool_args": tool_args,
            "bdh_decision": bdh_decision,
            "bdh_reason": bdh_reason,
        },
    )


def emit_llm_thought(txn_id: str, thought: str, step: int) -> None:
    emit_event("llm_thought", txn_id, {"thought": thought, "step": step})


def emit_bdh_alert(
    txn_id: str,
    rule_triggered: str,
    tool_name: str,
    reason: str,
) -> None:
    emit_event(
        "bdh_alert",
        txn_id,
        {
            "rule": rule_triggered,
            "tool_name": tool_name,
            "reason": reason,
            "severity": "HIGH",
        },
        source="bdh_watchdog",
    )


def emit_pipeline_result(
    txn_id: str,
    final_tier: int,
    final_action: str,
    final_score: float,
    llm_escalated: bool,
) -> None:
    emit_event(
        "pipeline_result",
        txn_id,
        {
            "tier": final_tier,
            "action": final_action,
            "score": final_score,
            "llm_escalated": llm_escalated,
        },
    )
