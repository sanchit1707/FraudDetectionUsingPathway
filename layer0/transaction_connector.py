import pathway as pw
from config import Config

def get_transaction_stream(mode: str = "demo") -> pw.Table:
    """
    Reads streaming real-time mock data from CSV or live topics from Redpanda.
    """
    
    # FIX: Updated schema to exactly match ieee_transactions.csv
    schema = pw.schema_from_dict({
        "TransactionID": str,
        "AccountID": str,
        "TransactionAmount": float,
        "TransactionDate": str,
        "TransactionType": str,
        "Location": str,
        "DeviceID": str,
        "IP Address": str,
        "MerchantID": str,
        "Channel": str,
        "CustomerAge": int,
        "CustomerOccupation": str,
        "TransactionDuration": int,
        "LoginAttempts": int,
        "AccountBalance": float,
        "PreviousTransactionDate": str
    })

    if mode == "demo":
        print(f"🔄 [L0-1] Replaying Compact Stream From: {Config.PAYSIM_PATH}")
        
        return pw.demo.replay_csv(
            Config.PAYSIM_PATH,
            schema=schema,
            input_rate=Config.REPLAY_RATE  
        )
        
    elif mode == "prod":
        return pw.io.kafka.read(#type: ignore
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