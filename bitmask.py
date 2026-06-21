import pathway as pw
from config import Config

@pw.udf

def compute_bitmask(
    amount:float,
    velocity_10min:float,
    geo_jump_km:float,
    is_new_device:bool,
    sanction_candidate:bool,
    ip_in_block_list:bool,
    round_amount:bool,
    merchant_anomaly:bool,
    time_of_day_risk:bool
)->dict:
    bitmask=0

    if sanction_candidate or ip_in_block_list:
        bitmask |=(1<<0)
    if velocity_10min > Config.Velocity_threshold:
        bitmask |=(1<<0)
    if geo_jump_km>Config.geo_jump_threshold:
        bitmask |=(1<<2)
    if amount>Config.high_value_threshold:
        bitmask |=(1<<3)
    if is_new_device:
        bitmask |= (1<<4)

    ## assign priority

    p0_bits= bitmask & 0b00111
    p1_bits=bitmask & 0b11000

    if p0_bits:
        priority="P0"
    elif p1_bits or round_amount or merchant_anomaly:
        priority="P1"
    elif time_of_day_risk:
        priority="P2"
    else:
        priority="p2"

    return {
        "bitmask":bitmask,
        "priority":priority,
        "bits":{
            "sanctions":bool((bitmask & (1<<0))),
            "velocity":bool((bitmask & (1<<1))),
            "geo_jump":bool((bitmask & (1<<2))),
            "high_value":bool((bitmask & (1<<3))),
            "new_device":bool((bitmask & (1<<4)))
        }
    }

def apply_bitmask(enriched_table: pw.Table) -> pw.Table:
    """Apply bitmask computation to the enriched stream"""
    return enriched_table.select(
        *pw.this,
        bitmask_result = compute_bitmask(
            pw.this.amount,
            pw.this.velocity_10min,
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
## add computed bitmask to the stream
    