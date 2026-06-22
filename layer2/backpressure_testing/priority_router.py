# layer0_sources/priority_router.py
import time
import json
import logging
from backpressure_monitor import monitor
from stream_buffer import append_to_buffer

# Analytics log for shed events (separate from main logs)
shed_logger = logging.getLogger("shed_analytics")
shed_logger.setLevel(logging.INFO)
handler = logging.FileHandler("./data/stream_buffer/shed_analytics.log")
handler.setFormatter(logging.Formatter('%(asctime)s %(message)s'))
shed_logger.addHandler(handler)


# ── P0 RULES: Immediate / Safety Critical ────────────────
def is_p0(event: dict) -> tuple[bool, str]:
    amount     = float(event.get("TransactionAmount", 0))
    login_att  = int(event.get("LoginAttempts", 1))
    is_foreign = event.get("Location", "") not in INDIAN_CITIES

    # Sanctions hit (checked separately via RAG)
    if event.get("sanctions_hit"):
        return True, "sanctions_hit"

    # Velocity > 10/min flagged upstream
    if event.get("velocity_per_min", 0) > 10:
        return True, "velocity>10/min"

    # Geo jump > 500km from last transaction
    if event.get("geo_jump_km", 0) > 500:
        return True, "geo_jump>500km"

    # High amount + new device
    if amount > 500_000 and event.get("is_new_device"):
        return True, "high_amount+new_device"

    # Foreign location + new device
    if is_foreign and event.get("is_new_device"):
        return True, "foreign+new_device"

    return False, ""


# ── P1 RULES: High Priority ───────────────────────────────
def is_p1(event: dict) -> tuple[bool, str]:
    amount  = float(event.get("TransactionAmount", 0))
    hour    = int(event.get("hour_of_day", 12))
    vel     = event.get("velocity_per_min", 0)

    if event.get("is_new_device"):
        return True, "new_device"

    # Round amount just below thresholds (card testing)
    round_flags = [9, 49, 99, 999, 4999, 9999]
    if any(abs(amount - r*1000) < 50 for r in round_flags):
        return True, "round_amount_threshold"

    if event.get("merchant_category_anomaly"):
        return True, "merchant_category_anomaly"

    # Unusual hour (1am-5am)
    if 1 <= hour <= 5:
        return True, "unusual_time_of_day"

    # Velocity 5-10/min
    if 5 <= vel <= 10:
        return True, "velocity_5-10/min"

    return False, ""


# ── MAIN ROUTER ───────────────────────────────────────────
INDIAN_CITIES = {
    "Mumbai", "Delhi", "Bangalore", "Hyderabad", "Chennai",
    "Kolkata", "Pune", "Ahmedabad", "Jaipur", "Lucknow",
    "Prayagraj", "Indore", "Bhopal", "Surat", "Nagpur"
}

def route_event(event: dict, process_p0_fn, process_p1_fn, process_p2_fn) -> str:
    """
    Routes every incoming transaction to P0/P1/P2/P3.
    Returns the priority string.

    process_p0_fn: your Rust engine / immediate block function
    process_p1_fn: your high-priority agent pipeline
    process_p2_fn: your standard processing pipeline
    """
    monitor.record_event()

    # ── P3: Active Load Shedding ──────────────────────────
    # Check backpressure FIRST before anything else
    if monitor.is_shedding():
        # P0 events are NEVER shed — safety critical always goes through
        p0, p0_reason = is_p0(event)
        if p0:
            process_p0_fn(event)
            return "P0"  # P0 bypasses shedding

        # Everything else gets dropped under backpressure
        shed_reason = f"backpressure | rate={monitor.current_rate():.0f}/s"

        # 1. Log to analytics
        shed_logger.info(json.dumps({
            "tx_id":       event.get("TransactionID"),
            "account_id":  event.get("AccountID"),
            "amount":      event.get("TransactionAmount"),
            "shed_reason": shed_reason,
        }))

        # 2. Append to replay buffer
        append_to_buffer(event, shed_reason)

        return "P3"  # dropped

    # ── Normal routing when system is healthy ─────────────
    p0, p0_reason = is_p0(event)
    if p0:
        process_p0_fn(event)
        return "P0"

    p1, p1_reason = is_p1(event)
    if p1:
        process_p1_fn(event)
        return "P1"

    # Everything else is P2
    process_p2_fn(event)
    return "P2"