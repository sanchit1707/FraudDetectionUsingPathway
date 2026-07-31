"""
orcestrator/nodes.py
--------------------
LangGraph nodes for the FlashGuard fraud detection orchestrator.

Node 1: watchdog_node         — Loop detection via Redis counter
Node 2: parallel_scoring_model — A2/A3/A4 fraud scoring (parallel)
Node 3: action_gateway_node   — Merge scores → tier / action
Node 4: llm_escalation_node   — LLM agent with 4 MCP tools (BDH-guarded)
Fallback: fallback_node       — Watchdog trip → safe default

All nodes emit events to the Pathway Redis Stream and save checkpoints.
"""

import asyncio
import json
import logging
import os
import time
from typing import Any, Dict, List, Optional

import redis as redis_sync

from orcestrator.state import OrchestratorState

from orcestrator.stream_emitter import (
    emit_node_enter,
    emit_node_exit,
    emit_tool_call,
    emit_llm_thought,
)
from orcestrator.mcp_tools import TOOLS, execute_tool

logger = logging.getLogger(__name__)

# ── Redis (sync, for watchdog counter) ────────────────────────────────────────
_REDIS_URL = os.getenv("REDIS_URL", "redis://redis:6379/0")
_cache = redis_sync.Redis.from_url(_REDIS_URL, decode_responses=True)

# ── BDH Watchdog HTTP endpoint ─────────────────────────────────────────────────
BDH_URL = os.getenv("BDH_URL", "http://bdh_watchdog:8090")


def _bdh_audit(anomaly_id: str, target_account: str, tool_name: str, tool_args: Dict) -> Dict[str, str]:
    """
    Pre-flight BDH check before every tool call.
    Returns {"status": "ALLOW"} or {"status": "BLOCK", "reason": "..."}.
    Falls back to ALLOW if BDH service is unreachable (logged as warning).
    """
    import urllib.request

    payload = json.dumps({
        "anomaly_id": anomaly_id,
        "target_account": target_account,
        "tool_name": tool_name,
        "tool_args": tool_args,
    }).encode()

    try:
        req = urllib.request.Request(
            f"{BDH_URL}/audit",
            data=payload,
            headers={"Content-Type": "application/json"},
            method="POST",
        )
        with urllib.request.urlopen(req, timeout=3) as resp:
            return json.loads(resp.read())
    except Exception as exc:
        logger.warning("[BDH] Unreachable (%s) — defaulting to ALLOW", exc)
        return {"status": "ALLOW", "reason": "BDH_UNREACHABLE_ALLOW_PASSTHROUGH"}


def log_llm_latency(llm_resp: dict, start_time: float) -> dict:
    """
    Extracts and logs Time to First Token (TTFT) and Last Token latency.
    Groq provides precise internal timings in the `usage` block.
    """
    end_time = time.time()
    network_latency = end_time - start_time
    
    usage = llm_resp.get("usage", {})
    
    # TTFT is roughly the prompt processing time + network queue
    prompt_time = usage.get("prompt_time", 0.0)
    completion_time = usage.get("completion_time", 0.0)
    total_groq_time = usage.get("total_time", prompt_time + completion_time)
    
    logger.info(
        "[LLM Latency] TTFT (Prompt Time): %.3fs | Generation Time: %.3fs | "
        "Last Token (Total Internal): %.3fs | Total Network Latency: %.3fs",
        prompt_time, completion_time, total_groq_time, network_latency
    )
    
    return {
        "ttft_s": prompt_time,
        "last_token_s": total_groq_time,
        "network_latency_s": network_latency
    }


# ═══════════════════════════════════════════════════════════════════════════════
# NODE 1: Watchdog
# ═══════════════════════════════════════════════════════════════════════════════

def watchdog_node(state: OrchestratorState) -> dict:
    txn_id = state["txn_id"]
    emit_node_enter(txn_id, "watchdog", {"txn_id": txn_id})

    loop_key = f"orchestrator_loops:{txn_id}"
    try:
        loop_count = int(_cache.incr(loop_key))
        _cache.expire(loop_key, 300)
    except Exception:
        loop_count = 1

    if loop_count > 3:
        logger.warning("[Watchdog] KILL — txn %s looped %dx", txn_id, loop_count)
        result = {
            "loop_count": loop_count,
            "killed": True,
            "error": f"Loop detected after {loop_count} iterations",
        }
        emit_node_exit(txn_id, "watchdog", {"killed": True, "loop_count": loop_count})
        return result

    result = {"loop_count": loop_count, "killed": False}
    emit_node_exit(txn_id, "watchdog", result)
    return result


# ═══════════════════════════════════════════════════════════════════════════════
# NODE 2: Parallel Scoring
# ═══════════════════════════════════════════════════════════════════════════════

def _run_fraud_scorer(features: dict, base_score: float = 0.0) -> dict:
    """Simple local fraud scorer (adds heuristics to base Pathway ML score)."""
    amount = features.get("amount", 0)
    rolling_spend = features.get("rolling_spend_10m", 0)
    txn_count = features.get("txn_count_10m", 0)

    score = base_score
    reasons = []
    if amount > 5000:
        score += 0.4
        reasons.append("HIGH_AMOUNT")
    if rolling_spend > 5000:
        score += 0.3
        reasons.append("HIGH_ROLLING_SPEND")
    if txn_count > 3:
        score += 0.3
        reasons.append("HIGH_VELOCITY")

    return {"fraud_score": min(score, 1.0), "fraud_reasons": reasons}


def _run_sanction_screen(state: OrchestratorState) -> dict:
    """Check bitmask bit 0 for sanctions flag."""
    bitmask = state.get("bitmask", 0)
    sanctions_hit = bool(bitmask & (1 << 0))
    return {
        "sanctions_hit": sanctions_hit,
        "sanctions_conf": 0.99 if sanctions_hit else 0.0,
        "matched_entity": "WATCHLIST_MERCHANT" if sanctions_hit else None,
    }


def _run_ring_detection(state: OrchestratorState) -> dict:
    """Simple ring detection placeholder — checks bitmask velocity bit."""
    bitmask = state.get("bitmask", 0)
    velocity_flag = bool(bitmask & (1 << 1))
    return {
        "ring_detected": velocity_flag,
        "ring_size": 5 if velocity_flag else 0,
        "ring_node": state.get("cust_token") if velocity_flag else None,
    }


def parallel_scoring_model(state: OrchestratorState) -> dict:
    txn_id = state["txn_id"]
    emit_node_enter(txn_id, "parallel_scoring", {"bitmask": state.get("bitmask")})

    features = state.get("features", {})
    bitmask = state.get("bitmask", 0)

    # Run A4 (ring detection) only when velocity bit is set
    ring_run = bool(bitmask & (1 << 1))
    base_score = state.get("fraud_score") or 0.0

    if ring_run:
        a2 = _run_fraud_scorer(features, base_score)
        a3 = _run_sanction_screen(state)
        a4 = _run_ring_detection(state)
    else:
        a2 = _run_fraud_scorer(features, base_score)
        a3 = _run_sanction_screen(state)
        a4 = {"ring_detected": False, "ring_size": 0, "ring_node": None}

    # Unwrap exceptions
    def _safe(r, default):
        return default if isinstance(r, Exception) else r

    a2 = _safe(a2, {"fraud_score": 0.5, "fraud_reasons": ["SCORER_ERROR"]})
    a3 = _safe(a3, {"sanctions_hit": False, "sanctions_conf": 0.0, "matched_entity": None})
    a4 = _safe(a4, {"ring_detected": False, "ring_size": 0, "ring_node": None})

    result = {
        "fraud_score": a2["fraud_score"],
        "fraud_reasons": a2["fraud_reasons"],
        "sanctions_hit": a3["sanctions_hit"],
        "sanctions_conf": a3.get("sanctions_conf", 0.0),
        "matched_entity": a3.get("matched_entity"),
        "ring_detected": a4["ring_detected"],
        "ring_size": a4.get("ring_size", 0),
        "ring_node": a4.get("ring_node"),
    }

    emit_node_exit(txn_id, "parallel_scoring", {
        "fraud_score": result["fraud_score"],
        "sanctions_hit": result["sanctions_hit"],
        "ring_detected": result["ring_detected"],
    })
    return result


# ═══════════════════════════════════════════════════════════════════════════════
# NODE 3: Action Gateway
# ═══════════════════════════════════════════════════════════════════════════════

def action_gateway_node(state: OrchestratorState) -> dict:
    txn_id = state["txn_id"]
    emit_node_enter(txn_id, "action_gateway", {"fraud_score": state.get("fraud_score")})

    score = state.get("fraud_score") or 0.0
    sanctions_hit = state.get("sanctions_hit") or False
    ring_detected = state.get("ring_detected") or False
    ring_size = state.get("ring_size") or 0

    if sanctions_hit:
        result = {"final_score": 1.0, "final_tier": 1, "final_action": "decline"}
    elif ring_detected and ring_size >= 5 and score > 0.5:
        score = min(score + 0.3, 1.0)
        tier, action = (1, "decline") if score > 0.6 else (2, "hold")
        result = {"final_score": round(score, 4), "final_tier": tier, "final_action": action}
    elif score > 0.85:
        result = {"final_score": round(score, 4), "final_tier": 1, "final_action": "decline"}
    elif score > 0.6:
        result = {"final_score": round(score, 4), "final_tier": 2, "final_action": "hold"}
    else:
        result = {"final_score": round(score, 4), "final_tier": 3, "final_action": "approve"}

    emit_node_exit(txn_id, "action_gateway", result)
    return result


# ═══════════════════════════════════════════════════════════════════════════════
# NODE 4: LLM Escalation Agent ⭐ (The ONLY place LLM is called)
# ═══════════════════════════════════════════════════════════════════════════════


import litellm

def llm_escalation_node(state: OrchestratorState) -> dict:
    txn_id = state["txn_id"]
    target_account = state.get("cust_token") or state.get("account_id", "UNKNOWN")

    emit_node_enter(txn_id, "llm_escalation", {
        "fraud_score": state.get("fraud_score"),
        "final_tier": state.get("final_tier"),
    })
    
    LLM_MODEL = os.getenv("LLM_MODEL", "llama-3.3-70b-versatile")
    model_str = LLM_MODEL if "/" in LLM_MODEL else f"groq/{LLM_MODEL}"
    active_groq_key = state.get("groq_api_key") or os.getenv("GROQ_API_KEY", "")
    
    # Check if a valid API key is present
    if not active_groq_key or active_groq_key == "your_groq_api_key_here":
        score = state.get("fraud_score", 0.5)
        verdict = "decline" if score > 0.65 else "hold"
        tier = 1 if verdict == "decline" else 2
        result = {
            "llm_verdict": verdict.upper(),
            "llm_reasoning": "Deterministic fallback (no LLM API key provided)",
            "llm_tool_calls": [],
            "llm_escalated": True,
            "final_tier": tier,
            "final_action": verdict,
            "final_score": score,
        }
        emit_node_exit(txn_id, "llm_escalation", {"llm_verdict": result["llm_verdict"], "tool_calls": 0, "final_action": verdict})
        return result

    # Initial System Prompt
    system_prompt = (
        "You are the FlashGuard LLM Escalation Agent. Your goal is to investigate this ambiguous "
        "transaction and determine whether it should be APPROVED, HELD, or BLOCKED.\n"
        f"Transaction ID: {txn_id}\n"
        f"Account ID: {target_account}\n"
        f"Initial Fraud Score: {state.get('fraud_score', 0):.3f}\n"
        "You have several tools at your disposal: get_account_details, query_compliance_rules, "
        "escalate_to_investigator, and block_account. Iteratively use these tools to gather evidence.\n"
        "Once you have enough evidence, provide your final response with exactly one of the words: [APPROVE, HOLD, BLOCK] and your reasoning."
    )
    
    messages = [{"role": "system", "content": system_prompt}]
    
    iterations = 0
    max_iterations = 5
    llm_verdict = "HOLD"
    llm_reasoning = "LLM reached max iterations without a final verdict."
    total_tool_calls = 0
    executed_tools = []
    
    while iterations < max_iterations:
        iterations += 1
        try:
            start_time = time.time()
            # Call Litellm
            llm_resp_obj = litellm.completion(
                model=model_str,
                messages=messages,
                tools=TOOLS,
                api_key=active_groq_key,
                temperature=0.1,
                timeout=15
            )
            llm_resp = llm_resp_obj.model_dump() if hasattr(llm_resp_obj, "model_dump") else dict(llm_resp_obj)
            log_llm_latency(llm_resp, start_time)
            
            message = llm_resp["choices"][0]["message"]
            messages.append(message)
            
            # If the LLM wants to call tools
            if message.get("tool_calls"):
                for tool_call in message["tool_calls"]:
                    total_tool_calls += 1
                    tool_name = tool_call["function"]["name"]
                    
                    try:
                        tool_args = json.loads(tool_call["function"]["arguments"])
                    except Exception:
                        tool_args = {}
                        
                    executed_tools.append(tool_name)
                    
                    # ── BDH WATCHDOG AUDIT ──
                    audit_res = _bdh_audit(txn_id, target_account, tool_name, tool_args)
                    
                    if audit_res.get("status") == "BLOCK":
                        # The BDH Watchdog blocked this action! Feed the block reason back to the LLM.
                        logger.warning("[BDH] Tool %s blocked: %s", tool_name, audit_res.get("reason"))
                        messages.append({
                            "role": "tool",
                            "tool_call_id": tool_call["id"],
                            "name": tool_name,
                            "content": f"BDH_WATCHDOG_BLOCKED: {audit_res.get('reason')}"
                        })
                    else:
                        # Action allowed by BDH, execute it!
                        try:
                            logger.info("[Agent] Executing tool: %s", tool_name)
                            tool_result = execute_tool(tool_name, tool_args)
                            messages.append({
                                "role": "tool",
                                "tool_call_id": tool_call["id"],
                                "name": tool_name,
                                "content": json.dumps(tool_result)
                            })
                        except Exception as e:
                            logger.error("[Agent] Tool %s failed: %s", tool_name, e)
                            messages.append({
                                "role": "tool",
                                "tool_call_id": tool_call["id"],
                                "name": tool_name,
                                "content": f"ERROR executing tool: {e}"
                            })
                            
            else:
                # LLM provided a final text response instead of a tool call
                content = message.get("content", "").upper()
                llm_reasoning = message.get("content", "")
                
                if "BLOCK" in content:
                    llm_verdict = "BLOCK"
                elif "APPROVE" in content:
                    llm_verdict = "APPROVE"
                elif "HOLD" in content:
                    llm_verdict = "HOLD"
                else:
                    llm_verdict = "HOLD"  # fallback if ambiguous text
                    
                break # We have a verdict, end the agent loop!
                
        except Exception as e:
            logger.error("[Agent] Litellm call failed: %s", e)
            llm_reasoning = f"LLM error: {e}"
            break
            
    # Map LLM verdict to tier/action
    if llm_verdict == "BLOCK":
        final_tier, final_action = 1, "decline"
        final_score = max(state.get("fraud_score", 0.75), 0.86)
    elif llm_verdict == "APPROVE":
        final_tier, final_action = 3, "approve"
        final_score = min(state.get("fraud_score", 0.5), 0.39)
    else:
        final_tier, final_action = 2, "hold"
        final_score = state.get("fraud_score", 0.6)

    result = {
        "llm_verdict": llm_verdict,
        "llm_reasoning": llm_reasoning[:500],
        "llm_tool_calls": executed_tools,
        "llm_source": model_str,
        "llm_escalated": True,
        "final_tier": final_tier,
        "final_action": final_action,
        "final_score": round(final_score, 4),
    }

    emit_node_exit(txn_id, "llm_escalation", {
        "llm_verdict": llm_verdict,
        "tool_calls": total_tool_calls,
        "final_action": final_action,
    })
    return result


# ═══════════════════════════════════════════════════════════════════════════════
# FALLBACK Node (watchdog trip)
# ═══════════════════════════════════════════════════════════════════════════════

def fallback_node(state: OrchestratorState) -> dict:
    txn_id = state.get("txn_id", "unknown")
    amount = state.get("amount", 0)
    bitmask = state.get("bitmask", 0)

    emit_node_enter(txn_id, "fallback", {"amount": amount, "bitmask": bitmask})

    if amount > 5000 or bitmask > 0:
        tier, action = 2, "hold"
    else:
        tier, action = 3, "approve"

    result = {
        "final_score": 0.5,
        "final_tier": tier,
        "final_action": action,
        "error": "watchdog_fallback",
        "llm_escalated": False,
    }
    emit_node_exit(txn_id, "fallback", result)
    return result
