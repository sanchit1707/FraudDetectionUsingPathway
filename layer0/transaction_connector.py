import pathway as pw
from config import Config

def get_transaction_stream(mode: str = "demo") -> pw.Table:
    """
    Reads streaming real-time mock data from CSV or live topics from Redpanda.
    """
    
    schema = pw.schema_from_dict({
        "txn_id": str,
        "customer_id": str,
        "amount": float,
        "merchant": str,
        "merchant_cat": str,
        "card_pan": str,      
        "device_id": str,
        "ip_address": str,
        "lat": float,
        "lon": float,
        "timestamp": int,     
        "card_type": str,
        "country": str
    })

    if mode == "demo":
        print(f"🔄 [L0-1] Replaying Compact Stream From: {Config.PAYSIM_PATH}")
        
        return pw.demo.replay_csv(
            Config.PAYSIM_PATH,
            schema=schema,
            input_rate=Config.REPLAY_RATE  
        )
        
    elif mode == "prod":
        return pw.io.kafka.read(
            rdconfigs={
                "bootstrap.servers": Config.KAFKA_HOST,
                "group.id": "layer0_txn_connector",
                "auto.offset.reset": "earliest"
            },
            topic="transactions",
            schema=schema,
            autocommit_duration_ms=100
        )
    else:
        raise ValueError(f"❌ Unknown runtime environment mode specified: {mode}")
