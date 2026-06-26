import time
import json
import fraud_pipeline_combined as fpc

# Setup fake sanctions data manually to bypass Pathway streaming for the unit test
fpc._sanctions_names = ["Bad Guy", "Evil Corp", "Sanctioned Entity"]
for name in fpc._sanctions_names:
    fpc._keyword_processor.add_keyword(name)

# Extract the raw python function from the UDF
if hasattr(fpc.compute_fraud_features, "__wrapped__"):
    compute_fraud = fpc.compute_fraud_features.__wrapped__
else:
    compute_fraud = fpc.compute_fraud_features

def test_pipeline():
    print("--- Running Fraud Pipeline Demo ---")
    
    # 1. Normal Transaction
    print("\n[Txn 1] Normal Transaction:")
    res1 = compute_fraud(
        user_id="user_123",
        amount=15.50,
        counterparty="Coffee Shop",
        lat=40.7128,
        lon=-74.0060, # NY
        device_id="dev_001",
        merchant_id="merch_A",
        ts=time.time()
    )
    print(json.dumps(res1, indent=2))

    # 2. Impossible Travel (Geo Jump) & Round Amount
    print("\n[Txn 2] Same user, big geo jump (London) + round amount:")
    res2 = compute_fraud(
        user_id="user_123",
        amount=500.00,
        counterparty="Electronics Store",
        lat=51.5074,
        lon=-0.1278, # London
        device_id="dev_002", # new device
        merchant_id="merch_B",
        ts=time.time() + 60 # 1 minute later
    )
    print(json.dumps(res2, indent=2))

    # 3. Sanctions Hit
    print("\n[Txn 3] Sanctions match (exact):")
    res3 = compute_fraud(
        user_id="user_456",
        amount=10.0,
        counterparty="Evil Corp",
        lat=34.0522,
        lon=-118.2437,
        device_id="dev_003",
        merchant_id="merch_C",
        ts=time.time()
    )
    print(json.dumps(res3, indent=2))

if __name__ == "__main__":
    test_pipeline()
    print("\nDemo completed successfully!")
