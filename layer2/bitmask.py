import math
import pathway as pw
from config import Config

@pw.udf
def compute_haversine(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
    """Computes the Haversine distance in km between two lat/lon pairs."""
    try:
        R = 6371.0
        dlat = math.radians(lat2 - lat1)
        dlon = math.radians(lon2 - lon1)
        a = (math.sin(dlat / 2) ** 2 +
             math.cos(math.radians(lat1)) * math.cos(math.radians(lat2)) * math.sin(dlon / 2) ** 2)
        return R * 2 * math.atan2(math.sqrt(a), math.sqrt(1 - a))
    except Exception:
        return 0.0

@pw.udf
def check_string_match(target: str, list_str: str) -> bool:
    """Checks if a target string exists in a stringified list."""
    try:
        return target not in list_str
    except Exception:
        return False

@pw.udf
def check_time_risk(date_str: str) -> bool:
    """Checks if transaction is between 00:00 and 05:00."""
    try:
        # Expected format: "2026-07-15 02:00:00"
        hour = int(date_str.split(" ")[1].split(":")[0])
        return 0 <= hour <= 5
    except Exception:
        return False

def compute_flags(enriched_table: pw.Table) -> pw.Table:
    """Applies row-wise Pathway declarative transformations for L2 feature engineering."""
    return enriched_table.with_columns(
        geo_jump_km = pw.apply(compute_haversine, pw.this.txn_lat, pw.this.txn_lon, pw.this.usual_lat, pw.this.usual_lon),
        is_new_device = pw.apply(check_string_match, pw.this.device_id, pw.this.known_devices),
        sanctions_candidate = pw.this.risk_tier == "high",
        ip_in_blocklist = False, # Standard IP blacklisting requires external DB, mocking for now
        round_amount_flag = (pw.this.amount % 1.0) == 0.0,
        merchant_anomaly = pw.apply(check_string_match, pw.this.merchant_id, pw.this.usual_merchants),
        time_of_day_risk = pw.apply(check_time_risk, pw.this.txn_date_str)
    )

@pw.udf
def compute_bitmask(
    amount: float,
    velocity_10min: int,
    geo_jump_km: float,
    is_new_device: bool,
    sanction_candidate: bool,
    ip_in_block_list: bool,
    round_amount: bool,
    merchant_anomaly: bool,
    time_of_day_risk: bool
) -> dict:
    bitmask = 0

    if sanction_candidate or ip_in_block_list:
        bitmask |= (1 << 0)
    if float(velocity_10min) > Config.Velocity_threshold:
        bitmask |= (1 << 0)
    if geo_jump_km > Config.geo_jump_threshold:
        bitmask |= (1 << 2)
    if amount > Config.high_value_threshold:
        bitmask |= (1 << 3)
    if is_new_device:
        bitmask |= (1 << 4)

    ## assign priority
    p0_bits = bitmask & 0b00111
    p1_bits = bitmask & 0b11000

    if p0_bits:
        priority = "P0"
    elif p1_bits or round_amount or merchant_anomaly:
        priority = "P1"
    elif time_of_day_risk:
        priority = "P2"
    else:
        priority = "p2"

    return {
        "bitmask": bitmask,
        "priority": priority,
        "bits": {
            "sanctions": bool((bitmask & (1 << 0))),
            "velocity": bool((bitmask & (1 << 1))),
            "geo_jump": bool((bitmask & (1 << 2))),
            "high_value": bool((bitmask & (1 << 3))),
            "new_device": bool((bitmask & (1 << 4)))
        }
    }

def apply_bitmask(windowed_table: pw.Table) -> pw.Table:
    """Apply bitmask computation to the windowed stream."""
    return windowed_table.select(
        *pw.this,
        bitmask_result = compute_bitmask(
            pw.this.amount,
            pw.this.txn_count_10m, # Safely use velocity now!
            pw.this.geo_jump_km,
            pw.this.is_new_device,
            pw.this.sanctions_candidate,
            pw.this.ip_in_blocklist,
            pw.this.round_amount_flag,
            pw.this.merchant_anomaly,
            pw.this.time_of_day_risk,
        )
    ).select(
        *pw.this,
        priority = pw.this.bitmask_result["priority"],
        bitmask  = pw.this.bitmask_result["bitmask"],
    )
