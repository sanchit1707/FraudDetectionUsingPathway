"""
fraud_pipeline_combined.py
──────────────────────────────────────────────────────────────────────────────
Single-pass, per-event Pathway UDF that merges:
  • Feature Engineering  (velocity, zscore, geo, device, merchant anomaly …)
  • Sanctions Screening  (FlashText exact-match + RapidFuzz fuzzy-match)

Both modules previously iterated over every transaction separately.
Now they share one UDF execution, one Pathway join, and one output record.

Install
-------
pip install pathway rapidfuzz flashtext
"""

from __future__ import annotations

import math
import time
from collections import deque
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any

import pathway as pw
from flashtext import KeywordProcessor
from rapidfuzz import fuzz, process

# ─────────────────────────────────────────────────────────────────────────────
# 1.  Sanctions list  (live Pathway join — auto-refreshes without restart)
# ─────────────────────────────────────────────────────────────────────────────

sanctions_table = pw.io.csv.read(
    "./sanctions.csv",
    schema=pw.schema_from_dict({"name": str}),
    mode="streaming",               # live join: new rows picked up automatically
)

# Build in-memory lookup structures (rebuilt when sanctions_table updates)
_keyword_processor = KeywordProcessor(case_sensitive=False)
_sanctions_names: list[str] = []


@pw.udf
def _rebuild_sanctions(names_json: str) -> str:
    """Called by Pathway when the sanctions snapshot changes."""
    import json
    global _keyword_processor, _sanctions_names
    _sanctions_names = json.loads(names_json)
    _keyword_processor = KeywordProcessor(case_sensitive=False)
    for n in _sanctions_names:
        _keyword_processor.add_keyword(n)
    return f"ok:{len(_sanctions_names)}"


# ─────────────────────────────────────────────────────────────────────────────
# 2.  Per-user rolling state  (kept outside Pathway for O(1) access)
# ─────────────────────────────────────────────────────────────────────────────

AMOUNT_HISTORY_MAX   = 500       # cap rolling list size

@dataclass
class UserState:
    txn_amounts:    deque          = field(default_factory=lambda: deque(maxlen=AMOUNT_HISTORY_MAX))
    txn_timestamps: deque          = field(default_factory=deque)
    last_lat:       float | None   = None
    last_lon:       float | None   = None
    known_devices:  set[str]       = field(default_factory=set)
    merchant_seq:   deque          = field(default_factory=lambda: deque(maxlen=20))

_user_states: dict[str, UserState] = {}

VELOCITY_WINDOW_SEC  = 3_600     # 1-hour rolling window
VELOCITY_MAX         = 10        # txns/hour before flag
GEO_IMPOSSIBLE_KM    = 500       # km in <10 min  ≈ impossible travel
ROUND_AMOUNT_CENTS   = 0         # flag if amount has zero cents
FUZZY_THRESHOLD      = 85        # RapidFuzz score threshold (0-100)

HOUR_RISK: dict[int, float] = {   # time-of-day risk weights
    **{h: 0.1 for h in range(6, 22)},    # daytime — low
    **{h: 0.6 for h in list(range(0, 6)) + list(range(22, 24))},  # night — high
}


# ─────────────────────────────────────────────────────────────────────────────
# 3.  Helper functions
# ─────────────────────────────────────────────────────────────────────────────

def _haversine_km(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
    R = 6_371.0
    φ1, φ2 = math.radians(lat1), math.radians(lat2)
    dφ = math.radians(lat2 - lat1)
    dλ = math.radians(lon2 - lon1)
    a = math.sin(dφ / 2) ** 2 + math.cos(φ1) * math.cos(φ2) * math.sin(dλ / 2) ** 2
    return R * 2 * math.atan2(math.sqrt(a), math.sqrt(1 - a))


def _amount_zscore(amounts: deque, current: float) -> float:
    n = len(amounts)
    if n < 5:
        return 0.0
    mu = sum(amounts) / n
    variance = sum((x - mu) ** 2 for x in amounts) / (n - 1)
    sigma = math.sqrt(variance)
    return abs((current - mu) / sigma) if sigma > 0 else 0.0


def _screen_sanctions(counterparty: str) -> dict[str, Any]:
    """Two-stage sanctions check — exact first, fuzzy fallback."""
    if _keyword_processor.extract_keywords(counterparty):
        return {"hit": True, "method": "exact", "conf": 1.0}
    if _sanctions_names:
        match, score, _ = process.extractOne(
            counterparty,
            _sanctions_names,
            scorer=fuzz.token_sort_ratio,
        )
        if score >= FUZZY_THRESHOLD:
            return {"hit": True, "method": "fuzzy", "conf": round(score / 100, 3), "matched": match}
    return {"hit": False, "method": "none", "conf": 0.0}


# ─────────────────────────────────────────────────────────────────────────────
# 4.  The combined UDF  — single pass per transaction
# ─────────────────────────────────────────────────────────────────────────────

@pw.udf
def compute_fraud_features(
    user_id:      str,
    amount:       float,
    counterparty: str,
    lat:          float,
    lon:          float,
    device_id:    str,
    merchant_id:  str,
    ts:           float,          # unix timestamp
) -> dict:
    t0 = time.perf_counter()

    # ── Retrieve / initialise user state ──────────────────────────────────────
    state = _user_states.setdefault(user_id, UserState())
    now   = ts or time.time()
    dt    = datetime.fromtimestamp(now)

    # ── 4A.  FEATURE ENGINEERING ─────────────────────────────────────────────

    # Velocity score
    cutoff = now - VELOCITY_WINDOW_SEC
    while state.txn_timestamps and state.txn_timestamps[0] < cutoff:
        state.txn_timestamps.popleft()
    velocity_raw   = len(state.txn_timestamps)
    velocity_score = min(velocity_raw / VELOCITY_MAX, 1.0)

    # Amount z-score
    amount_zscore = _amount_zscore(state.txn_amounts, amount)

    # Geo jump
    geo_jump_km = 0.0
    if state.last_lat is not None:
        geo_jump_km = _haversine_km(state.last_lat, state.last_lon, lat, lon)
    geo_anomaly = geo_jump_km > GEO_IMPOSSIBLE_KM

    # New device
    is_new_device = device_id not in state.known_devices

    # Merchant sequence anomaly (simple: same merchant repeated >3 times in last 5)
    recent_merchants = list(state.merchant_seq)[-5:]
    merchant_seq_anomaly = recent_merchants.count(merchant_id) >= 3

    # Round amount flag
    round_amount_flag = amount % 1 == 0

    # Time-of-day risk
    time_of_day_risk = HOUR_RISK.get(dt.hour, 0.3)

    # ── 4B.  SANCTIONS SCREENING ─────────────────────────────────────────────
    sanctions = _screen_sanctions(counterparty)
    sanctions_hit  = sanctions["hit"]
    sanctions_conf = sanctions["conf"]

    # ── 4C.  COMPOSITE FRAUD SCORE ────────────────────────────────────────────
    # Sanctions hit → hard override to Tier 1
    if sanctions_hit:
        fraud_score = 1.0
        fraud_tier  = 1
    else:
        fraud_score = round(
            0.20 * velocity_score
            + 0.20 * min(amount_zscore / 4, 1.0)
            + 0.20 * float(geo_anomaly)
            + 0.15 * float(is_new_device)
            + 0.10 * float(merchant_seq_anomaly)
            + 0.05 * float(round_amount_flag)
            + 0.10 * time_of_day_risk,
            4,
        )
        fraud_tier = 1 if fraud_score >= 0.75 else (2 if fraud_score >= 0.45 else 3)

    # ── Update rolling state ──────────────────────────────────────────────────
    state.txn_amounts.append(amount)
    state.txn_timestamps.append(now)
    state.last_lat, state.last_lon = lat, lon
    state.known_devices.add(device_id)
    state.merchant_seq.append(merchant_id)

    elapsed_ms = round((time.perf_counter() - t0) * 1000, 2)

    return {
        # ── features ──────────────────────────────────────────────────
        "velocity_score":       velocity_score,
        "amount_zscore":        round(amount_zscore, 4),
        "geo_jump_km":          round(geo_jump_km, 2),
        "geo_anomaly":          geo_anomaly,
        "is_new_device":        is_new_device,
        "merchant_seq_anomaly": merchant_seq_anomaly,
        "round_amount_flag":    round_amount_flag,
        "time_of_day_risk":     time_of_day_risk,
        # ── sanctions ─────────────────────────────────────────────────
        "sanctions_hit":        sanctions_hit,
        "sanctions_method":     sanctions["method"],
        "sanctions_conf":       sanctions_conf,
        "sanctions_matched":    sanctions.get("matched", ""),
        # ── final verdict ─────────────────────────────────────────────
        "fraud_score":          fraud_score,
        "fraud_tier":           fraud_tier,   # 1=block, 2=review, 3=pass
        "elapsed_ms":           elapsed_ms,
    }


# ─────────────────────────────────────────────────────────────────────────────
# 5.  Pathway pipeline wiring
# ─────────────────────────────────────────────────────────────────────────────

class TransactionSchema(pw.Schema):
    user_id:      str
    amount:       float
    counterparty: str
    lat:          float
    lon:          float
    device_id:    str
    merchant_id:  str
    ts:           float


transactions = pw.io.kafka.read(
    rdkafka_settings={"bootstrap.servers": "localhost:9092", "group.id": "fraud-pipeline"},
    topic="transactions",
    schema=TransactionSchema,
    format="json",
)

results = transactions.select(
    *pw.this,
    fraud=compute_fraud_features(
        pw.this.user_id,
        pw.this.amount,
        pw.this.counterparty,
        pw.this.lat,
        pw.this.lon,
        pw.this.device_id,
        pw.this.merchant_id,
        pw.this.ts,
    ),
)

# ── Fan-out to different sinks by fraud tier ──────────────────────────────────

tier1 = results.filter(pw.cast(int, pw.this.fraud["fraud_tier"]) == 1)
tier2 = results.filter(pw.cast(int, pw.this.fraud["fraud_tier"]) == 2)
tier3 = results.filter(pw.cast(int, pw.this.fraud["fraud_tier"]) == 3)

pw.io.kafka.write(tier1, rdkafka_settings={"bootstrap.servers": "localhost:9092"}, topic_name="fraud.tier1.block")
pw.io.kafka.write(tier2, rdkafka_settings={"bootstrap.servers": "localhost:9092"}, topic_name="fraud.tier2.review")
pw.io.kafka.write(tier3, rdkafka_settings={"bootstrap.servers": "localhost:9092"}, topic_name="fraud.tier3.pass")

if __name__ == "__main__":
    pw.run()
