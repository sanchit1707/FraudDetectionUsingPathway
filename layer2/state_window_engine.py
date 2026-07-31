import pathway as pw
from datetime import datetime, timedelta
from layer0.watchlist_loader import get_watchlist

def parse_custom_timestamp(date_str: str) -> pw.DateTimeNaive:
    try:
        dt = datetime.strptime(str(date_str), "%Y-%m-%d %H:%M:%S")
        return pw.DateTimeNaive(dt)
    except Exception:
        return pw.DateTimeNaive(datetime(2026, 1, 1, 0, 0, 0))

def build_state_window_stream(enriched_stream: pw.Table) -> pw.Table:
    """
    Module L2-2: Incremental Join + State Engine
    """
    # 1. Load the live reference watchlist
    watchlist_table = get_watchlist()
    
    # 2. Add the timeline
    timed_stream = enriched_stream.with_columns(
        event_time=pw.apply(parse_custom_timestamp, enriched_stream.txn_date_str)
    )
    
    # 3. INCREMENTAL JOIN: Match incoming transactions against the watchlist
    # If the merchant is on the list, grab the reason. If not, default to "clean".
    joined_stream = timed_stream.join_left(
        watchlist_table,
        timed_stream.merchant_id == watchlist_table.merchant_id
    ).select(
        account_id=pw.left.account_id,
        amount=pw.left.amount,
        event_time=pw.left.event_time,
        merchant_id=pw.left.merchant_id,
        watchlist_flag=pw.coalesce(pw.right.risk_reason, "clean"),
        # Preserve new feature columns from compute_flags
        geo_jump_km=pw.left.geo_jump_km,
        is_new_device=pw.left.is_new_device,
        sanctions_candidate=pw.left.sanctions_candidate,
        ip_in_blocklist=pw.left.ip_in_blocklist,
        round_amount_flag=pw.left.round_amount_flag,
        merchant_anomaly=pw.left.merchant_anomaly,
        time_of_day_risk=pw.left.time_of_day_risk
    )
    
    # 4. Define the sliding window
    sliding_window = pw.temporal.sliding(
        duration=timedelta(minutes=10),
        hop=timedelta(minutes=1)
    )
    
    # 5. Group and Reduce (using our new joined_stream instead of timed_stream)
    windowed_reducer = joined_stream.windowby(
        joined_stream.event_time,
        window=sliding_window,
        instance=joined_stream.account_id
    ).reduce(
        account_id=pw.this._pw_instance,
        rolling_spend_10m=pw.reducers.sum(pw.this.amount),
        txn_count_10m=pw.reducers.count(),
        active_threats=pw.reducers.max(pw.this.watchlist_flag),
        
        # Pass the amount and computed flags through to Layer 4 & Bitmask!
        amount=pw.reducers.max(pw.this.amount),
        geo_jump_km=pw.reducers.max(pw.this.geo_jump_km),
        is_new_device=pw.reducers.max(pw.this.is_new_device),
        sanctions_candidate=pw.reducers.max(pw.this.sanctions_candidate),
        ip_in_blocklist=pw.reducers.max(pw.this.ip_in_blocklist),
        round_amount_flag=pw.reducers.max(pw.this.round_amount_flag),
        merchant_anomaly=pw.reducers.max(pw.this.merchant_anomaly),
        time_of_day_risk=pw.reducers.max(pw.this.time_of_day_risk)
    )
    
    return windowed_reducer