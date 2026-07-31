"""
orcestrator/graph.py
---------------------
LangGraph graph definition for FlashGuard's fraud detection orchestrator.

Flow:
  watchdog → parallel_scoring → action_gateway
                                      ↓
                            score in (0.40, 0.75)?
                              YES → llm_escalation → END
                              NO  → END
  watchdog killed → fallback → END
"""

import logging
from langgraph.graph import StateGraph, END

from orcestrator.state import OrchestratorState
from orcestrator.nodes import (
    watchdog_node,
    parallel_scoring_model,
    action_gateway_node,
    llm_escalation_node,
    fallback_node,
)

logger = logging.getLogger(__name__)


def route_after_watchdog(state: OrchestratorState) -> str:
    if state.get("killed"):
        return "kill"
    return "continue"


def route_after_gateway(state: OrchestratorState) -> str:
    """
    Ambiguous score range (0.40–0.75) → LLM escalation.
    Clear decisions → finish immediately.
    """
    score = state.get("final_score") or 0.0
    sanctions = state.get("sanctions_hit") or False
    ring = state.get("ring_detected") or False

    # Clear-cut fraud or clear-cut clean — no need for LLM
    if sanctions or score > 0.75 or score < 0.40:
        return "finish"

    # Ambiguous — needs LLM reasoning
    return "escalate"


def building_flow_graph() -> StateGraph:
    graph = StateGraph(OrchestratorState)

    # ── Nodes ─────────────────────────────────────────────────────────────────
    graph.add_node("watchdog", watchdog_node)
    graph.add_node("parallel_scoring", parallel_scoring_model)
    graph.add_node("action_gateway", action_gateway_node)
    graph.add_node("llm_escalation", llm_escalation_node)
    graph.add_node("fallback", fallback_node)

    # ── Entry ─────────────────────────────────────────────────────────────────
    graph.set_entry_point("watchdog")

    # ── Edges ─────────────────────────────────────────────────────────────────
    graph.add_conditional_edges(
        "watchdog",
        route_after_watchdog,
        {
            "continue": "parallel_scoring",
            "kill": "fallback",
        },
    )

    graph.add_edge("parallel_scoring", "action_gateway")

    graph.add_conditional_edges(
        "action_gateway",
        route_after_gateway,
        {
            "finish": END,
            "escalate": "llm_escalation",
        },
    )

    graph.add_edge("llm_escalation", END)
    graph.add_edge("fallback", END)

    # Connect to Redis Checkpointer
    import os
    from redis import Redis
    from langgraph.checkpoint.redis import RedisSaver
    
    redis_url = os.getenv("REDIS_URL", "redis://redis:6379/0")
    redis_conn = Redis.from_url(redis_url)
    checkpointer = RedisSaver(redis_client=redis_conn)

    return graph.compile(checkpointer=checkpointer)


# Module-level compiled graph (singleton — avoids rebuilding per transaction)
_compiled_graph = None


def get_graph():
    global _compiled_graph
    if _compiled_graph is None:
        _compiled_graph = building_flow_graph()
        logger.info("[Graph] LangGraph compiled ✓")
    return _compiled_graph
