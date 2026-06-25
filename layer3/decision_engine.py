import pathway as pw

def evaluate_fraud_rules(windowed_analytics: pw.Table) -> pw.Table:
    """
    Module L3-1: Rule & Alerting Engine
    Evaluates real-time windows against risk thresholds to flag suspicious activity.
    """
    # Define our deterministic fraud detection thresholds
    MAX_ALLOWED_TXNS_10M = 3
    MAX_ALLOWED_SPEND_10M = 5000.0

    # Evaluate safety conditions across all sliding windows
    alert_stream = windowed_analytics.with_columns(
        velocity_alert=windowed_analytics.txn_count_10m >= MAX_ALLOWED_TXNS_10M,
        
        spend_alert=windowed_analytics.rolling_spend_10m > MAX_ALLOWED_SPEND_10M,
        
        watchlist_alert=windowed_analytics.active_threats != "clean"
    )

    final_alerts = alert_stream.with_columns(
        is_fraudulent=(
            pw.this.velocity_alert | 
            pw.this.spend_alert | 
            pw.this.watchlist_alert
        )
    )

    return final_alerts
