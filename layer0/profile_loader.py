import sys

# Hardcode your exact project root directory at the top of the search path
sys.path.insert(0, "/home/snottyunhunter/Documents/FraudDetectionUsingPathway")

import pathway as pw
from config import Config

def get_customer_profiles() -> pw.Table:
    schema = pw.schema_from_dict({
        "customer_id": str,
        "avg_spend_30d": float,
        "usual_merchants": str,
        "known_devices": str,
        "home_city": str,
        "usual_lat": float,
        "usual_lon": float,
        "account_balance": float,
        "txn_count": int,
        "fraud_count": int,
        "risk_tier": str
    })

    return pw.io.fs.read(
        Config.PROFILES_PATH,
        schema=schema,
        format='csv',
        mode="static"
    )
