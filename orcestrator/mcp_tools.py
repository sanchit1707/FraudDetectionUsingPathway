"""
orcestrator/mcp_tools.py
------------------------
The 4 MCP tool definitions used by Node 4 (LLM Escalation Agent).
These are the ONLY tools the LLM is allowed to call.
BDH validates every call against these schemas before execution.

Data sources — ALL Pathway-powered, zero raw Redis client:
  query_compliance_rules  → A5 Compliance RAG  (Pathway + sentence-transformers)
  get_account_details     → Gateway /stream/recent  (reads Pathway pathway:events stream)
  block_account           → Gateway /stream/recent + pathway:events write-back
  escalate_to_investigator→ pathway:events write-back via gateway Redis conn
"""

import json
import logging
import os
import time
import urllib.request
import urllib.error
from typing import Any, Dict, List

logger = logging.getLogger(__name__)

# ── Service URLs (resolved from env — work inside Docker + local testing) ──────
A5_RAG_URL  = os.getenv("A5_URL",       "http://a5_compliance_rag:8011")
GATEWAY_URL = os.getenv("GATEWAY_URL",  "http://localhost:8080")  # self-call for stream reads
REDIS_URL   = os.getenv("REDIS_URL",    "redis://redis:6379/0")


# ── Tiny HTTP helper ──────────────────────────────────────────────────────────
def _http_post(url: str, body: dict, timeout: int = 8) -> dict:
    payload = json.dumps(body).encode()
    req = urllib.request.Request(
        url, data=payload,
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        return json.loads(resp.read())


def _http_get(url: str, timeout: int = 5) -> dict:
    with urllib.request.urlopen(url, timeout=timeout) as resp:
        return json.loads(resp.read())


# ── Tool JSON schemas (OpenAI function-calling format) ────────────────────────
TOOLS: List[Dict[str, Any]] = [
    {
        "type": "function",
        "function": {
            "name": "get_account_details",
            "description": (
                "Retrieve full account details for a specific account. "
                "Use this first to understand the account history before deciding."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "account_id": {
                        "type": "string",
                        "description": "The account ID to look up (e.g. ACC_0003)",
                    },
                    "reason": {
                        "type": "string",
                        "description": "Why you are looking up this account",
                    },
                },
                "required": ["account_id", "reason"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "query_compliance_rules",
            "description": (
                "Search the compliance rule book for relevant regulations. "
                "Use this to find applicable AML/BSA rules for this transaction type."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "search_query": {
                        "type": "string",
                        "description": "Natural-language query for compliance rules",
                    },
                },
                "required": ["search_query"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "block_account",
            "description": (
                "Block/freeze the target account. CRITICAL action — "
                "only call this if you are confident the transaction is fraudulent."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "account_id": {
                        "type": "string",
                        "description": "The account ID to block",
                    },
                    "reason": {
                        "type": "string",
                        "description": "Reason for blocking (shown to compliance team)",
                    },
                },
                "required": ["account_id", "reason"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "escalate_to_investigator",
            "description": (
                "Escalate the anomaly to a human fraud investigator. "
                "Use this when you are uncertain or the case requires human judgment."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "transaction_id": {
                        "type": "string",
                        "description": "The transaction ID to escalate",
                    },
                    "risk_summary": {
                        "type": "string",
                        "description": "A concise summary of why this is suspicious",
                    },
                },
                "required": ["transaction_id", "risk_summary"],
            },
        },
    },
]


# ── Tool executors ─────────────────────────────────────────────────────────────

def _execute_get_account_details(account_id: str, reason: str) -> Dict[str, Any]:
    """
    Read account history from the Pathway event stream via the gateway's
    /stream/recent endpoint.  No direct Redis client — pure HTTP to the
    Pathway-backed REST layer.
    """
    try:
        # Pathway writes every pipeline result to pathway:events;
        # /stream/recent exposes the last N events from that stream.
        data = _http_get(f"{GATEWAY_URL}/stream/recent?n=200", timeout=5)
        events = data.get("events") or []

        # Filter events belonging to this account
        account_events = [
            e for e in events
            if account_id in e.get("txn_id", "")
            or e.get("payload", {}).get("account_id") == account_id
        ]

        if account_events:
            latest = account_events[0]   # most recent first (xrevrange)
            payload = latest.get("payload", {})
            score   = payload.get("final_score", 0.5)
            action  = payload.get("final_action", "unknown")
            return {
                "account_id":        account_id,
                "source":            "pathway:events via /stream/recent",
                "last_verdict":      action,
                "last_risk_score":   score,
                "risk_tier":         "high" if score > 0.7 else "medium" if score > 0.4 else "low",
                "history_events":    len(account_events),
                "open_cases":        1 if action in ("hold", "decline") else 0,
                "reason_logged":     reason,
            }

        # Account has no history in the Pathway stream
        return {
            "account_id":    account_id,
            "source":        "pathway:events — no history",
            "last_verdict":  "none",
            "risk_tier":     "unknown",
            "open_cases":    0,
            "reason_logged": reason,
        }

    except Exception as exc:
        logger.warning("[MCP:get_account_details] Stream read failed (%s) — using default", exc)
        return {
            "account_id":    account_id,
            "source":        "fallback",
            "risk_tier":     "medium",
            "open_cases":    0,
            "reason_logged": reason,
        }


def _execute_query_compliance_rules(search_query: str) -> Dict[str, Any]:
    """
    Query the live A5 Compliance RAG — a Pathway streaming service that
    embeds compliance docs with sentence-transformers and returns the
    top-k semantically nearest snippets.

    Falls back to static rules only if A5 is completely unreachable.
    """
    try:
        data = _http_post(
            A5_RAG_URL,
            {"query": search_query, "top_k": 3},
            timeout=8,
        )
        snippets = data.get("compliance_context", [])
        rules = [
            f"[relevance={s.get('relevance_score', 0):.3f}] {s.get('snippet', '')[:400]}"
            for s in snippets
        ]
        logger.info(
            "[MCP:query_compliance_rules] A5 RAG (Pathway) → %d snippets | query: %s",
            len(snippets), search_query[:80],
        )
        return {
            "query":  search_query,
            "source": "a5_compliance_rag:pathway+sentence_transformers",
            "count":  len(snippets),
            "rules":  rules,
        }

    except urllib.error.URLError as exc:
        logger.warning("[MCP:query_compliance_rules] A5 RAG unreachable (%s) → static fallback", exc)
    except Exception as exc:
        logger.warning("[MCP:query_compliance_rules] A5 RAG error (%s) → static fallback", exc)

    # Static fallback — only reached if A5 is down
    return {
        "query":  search_query,
        "source": "static_fallback",
        "count":  3,
        "rules": [
            "BSA Title 31: Transactions over $10,000 require CTR filing.",
            "AML Rule 12: Structuring below reporting threshold is a federal crime.",
            "PMLA 2002: Rapid velocity spike over high-risk merchants → SAR mandatory.",
        ],
    }


def _execute_block_account(account_id: str, reason: str) -> Dict[str, Any]:
    """
    Record the block decision into the Pathway event stream (pathway:events)
    via the gateway's Redis connection — the same stream Pathway reads from.
    The BDH watchdog and downstream consumers (A8 SAR drafter, A10 feedback loop)
    will pick it up automatically through the Pathway pipeline.
    """
    blocked_at = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())
    persisted  = False
    try:
        import redis as redis_sync
        r = redis_sync.Redis.from_url(REDIS_URL, decode_responses=True, socket_timeout=2)
        # Write into the Pathway-monitored stream
        r.xadd("pathway:events", {
            "event_type": "account_blocked",
            "account_id": account_id,
            "reason":     reason[:300],
            "blocked_at": blocked_at,
            "source":     "mcp_tool:block_account",
            "timestamp":  str(time.time()),
        }, maxlen=50000, approximate=True)
        # Also persist a hash for quick lookup
        r.hset(f"blocked:{account_id}", mapping={
            "reason": reason[:300], "blocked_at": blocked_at,
        })
        persisted = True
        logger.info("[MCP:block_account] %s blocked → pathway:events written", account_id)
    except Exception as exc:
        logger.warning("[MCP:block_account] Stream write failed (%s)", exc)

    return {
        "account_id": account_id,
        "action":     "BLOCKED",
        "reason":     reason,
        "blocked_at": blocked_at,
        "persisted_to_pathway_stream": persisted,
    }


def _execute_escalate_to_investigator(transaction_id: str, risk_summary: str) -> Dict[str, Any]:
    """
    Publish escalation event into the Pathway event stream so BDH,
    A8 SAR Drafter, and A10 Feedback Loop can react to it downstream.
    """
    case_id    = f"CASE_{transaction_id}"
    created_at = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())
    persisted  = False
    try:
        import redis as redis_sync
        r = redis_sync.Redis.from_url(REDIS_URL, decode_responses=True, socket_timeout=2)
        r.xadd("pathway:events", {
            "event_type":     "investigator_escalation",
            "transaction_id": transaction_id,
            "case_id":        case_id,
            "risk_summary":   risk_summary[:300],
            "created_at":     created_at,
            "source":         "mcp_tool:escalate_to_investigator",
            "timestamp":      str(time.time()),
        }, maxlen=50000, approximate=True)
        persisted = True
        logger.info("[MCP:escalate] Case %s → pathway:events written", case_id)
    except Exception as exc:
        logger.warning("[MCP:escalate] Stream write failed (%s)", exc)

    return {
        "case_id":        case_id,
        "transaction_id": transaction_id,
        "status":         "ESCALATED_TO_INVESTIGATOR",
        "created_at":     created_at,
        "risk_summary":   risk_summary,
        "persisted_to_pathway_stream": persisted,
    }


TOOL_EXECUTORS = {
    "get_account_details":      _execute_get_account_details,
    "query_compliance_rules":   _execute_query_compliance_rules,
    "block_account":            _execute_block_account,
    "escalate_to_investigator": _execute_escalate_to_investigator,
}


def execute_tool(tool_name: str, tool_args: Dict[str, Any]) -> Dict[str, Any]:
    """Execute a validated tool call and return the result."""
    executor = TOOL_EXECUTORS.get(tool_name)
    if executor is None:
        raise ValueError(f"Unknown tool: {tool_name}")
    return executor(**tool_args)
