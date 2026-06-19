import pathway as pw
from layer0_sources.transaction_connector import get_transaction_stream
from layer0_sources.customer_profile_loader import get_customer_profiles

# Global Geolocation Dictionary mapping dataset cities to explicit coordinates
CITY_COORDINATES = {
    "Philadelphia": (39.9526, -75.1652),
    "Austin": (30.2672, -97.7431),
    "Milwaukee": (43.0389, -87.9065),
    "Louisville": (38.2527, -85.7585),
    "New York": (40.7128, -74.0060),
    "Houston": (29.7604, -95.3698),
    "San Diego": (32.7157, -117.1611),
    "Atlanta": (33.7490, -84.3880),
    "Phoenix": (33.4484, -112.0740),
    "Chicago": (41.8781, -87.6298)
}

def get_city_lat(location: str) -> float:
    return CITY_COORDINATES.get(location, (0.0, 0.0))[0]

def get_city_lon(location: str) -> float:
    return CITY_COORDINATES.get(location, (0.0, 0.0))[1]

def build_enriched_stream(mode: str = "demo") -> pw.Table:
    """
    Step 7: Complete Prefetcher Engine Module
    Successfully maps, joins, and secures all transaction and profile metadata.
    """
    txn_stream = get_transaction_stream(mode=mode)
    profile_table = get_customer_profiles()
    
    # Map city locations to coordinates
    txn_mapped = txn_stream.with_columns(
        txn_lat=pw.apply(get_city_lat, txn_stream.Location),
        txn_lon=pw.apply(get_city_lon, txn_stream.Location)
    )
    
    # Perform the streaming left join
    enriched = txn_mapped.join_left(
        profile_table,
        txn_mapped.AccountID == profile_table.customer_id
    ).select(
        # Streaming transaction properties
        txn_id=pw.left.TransactionID,
        account_id=pw.left.AccountID,
        amount=pw.left.TransactionAmount,
        location_city=pw.left.Location,
        
        # FIX: Extract with_columns mutations safely using bracket strings off pw.left
        txn_lat=pw.left["txn_lat"],
        txn_lon=pw.left["txn_lon"],
        
        device_id=pw.left.DeviceID,
        ip_address=pw.coalesce(pw.left["IP Address"], "0.0.0.0"),
        txn_date_str=pw.left.TransactionDate,
        txn_type=pw.left.TransactionType,
        merchant_id=pw.left.MerchantID,
        channel=pw.left.Channel,
        prev_txn_date_str=pw.left.PreviousTransactionDate,
        
        # Pulling remaining historical lookup parameters with clean fallbacks
        avg_spend_30d=pw.coalesce(pw.right.avg_spend_30d, 0.0),
        usual_merchants=pw.coalesce(pw.right.usual_merchants, "[]"),
        known_devices=pw.coalesce(pw.right.known_devices, "[]"),
        home_city=pw.coalesce(pw.right.home_city, "unknown"),
        usual_lat=pw.coalesce(pw.right.usual_lat, 0.0),
        usual_lon=pw.coalesce(pw.right.usual_lon, 0.0),
        historical_balance=pw.coalesce(pw.right.account_balance, 0.0),
        risk_tier=pw.coalesce(pw.right.risk_tier, "low")
    )
    
    return enriched
