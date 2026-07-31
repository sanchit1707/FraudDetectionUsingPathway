from typing import TypedDict, Optional, List, Any


class OrchestratorState(TypedDict):
    # ── Input ─────────────────────────────────────────────────────────────────
    txn_id: str
    cust_token: str
    amount: float
    timestamp: int
    priority: int
    bitmask: int
    features: dict

    # ── Scoring ───────────────────────────────────────────────────────────────
    fraud_score: Optional[float]
    fraud_reasons: Optional[List[str]]

    sanctions_hit: Optional[bool]
    sanctions_conf: Optional[float]
    matched_entity: Optional[str]

    ring_detected: Optional[bool]
    ring_size: Optional[int]
    ring_node: Optional[str]

    # ── Final verdict ─────────────────────────────────────────────────────────
    final_tier: Optional[int]
    final_action: Optional[str]
    final_score: Optional[float]

    # ── LLM Escalation (Node 4) ───────────────────────────────────────────────
    llm_source: Optional[str]          # "cache" | "groq_low" | "groq_medium" | None
    llm_reasoning: Optional[str]       # LLM chain-of-thought summary
    llm_verdict: Optional[str]         # "BLOCK" | "HOLD" | "APPROVE" | None
    llm_tool_calls: Optional[List[Any]]  # list of tool call dicts
    llm_escalated: Optional[bool]      # whether Node 4 ran

    # ── Watchdog / Control ────────────────────────────────────────────────────
    loop_count: int
    killed: bool
    error: Optional[str]

    # ── Checkpointing ─────────────────────────────────────────────────────────
    checkpoint_node: Optional[str]     # last completed node name
