import urllib.request
import json
import uuid
import time
import random

API_URL = "http://localhost:8000/execute"

def send_request(verdict: str, tier: int):
    transaction_id = f"TXN-DEMO-{uuid.uuid4().hex[:8].upper()}"
    
    payload = {
        "transaction_id": transaction_id,
        "account_id": "ACC-DEMO-123",
        "customer_id": "CUS-DEMO-456",
        "verdict": verdict,
        "confidence": round(random.uniform(0.7, 0.99), 2),
        "risk_score": round(random.uniform(0.5, 0.99), 2),
        "tier": tier,
        "gateway_trace": f"gw-trace-{uuid.uuid4().hex[:6]}"
    }
    
    data = json.dumps(payload).encode("utf-8")
    req = urllib.request.Request(API_URL, data=data, headers={"Content-Type": "application/json"}, method="POST")
    
    try:
        with urllib.request.urlopen(req) as response:
            res_body = response.read().decode("utf-8")
            print(f"[{verdict: <6}] Transaction {transaction_id} executed successfully. Latency: {json.loads(res_body).get('latency_ms')} ms")
    except urllib.error.URLError as e:
        print(f"[{verdict: <6}] Request failed: {e}")

if __name__ == "__main__":
    print("🚀 Starting FlashGuard Agent 6 Demo Load...")
    print("Sending various verdicts to the API (http://localhost:8000/execute)\n")
    
    scenarios = [
        ("BLOCK", 1),
        ("ALLOW", 2),
        ("FLAG", 1),
        ("REVIEW", 3),
        ("BLOCK", 1) # Another block to show distribution
    ]
    
    for verdict, tier in scenarios:
        send_request(verdict, tier)
        time.sleep(1) # Small pause for realism
        
    print("\n✅ Demo complete! Check your UI dashboards for the results.")
