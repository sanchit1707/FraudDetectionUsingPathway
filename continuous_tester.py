import asyncio
import aiohttp
import time
import json
import argparse
import random

SCENARIOS = [
    {
        "name": "Auto-Approve (Clean)",
        "weight": 70, # 70% of traffic
        "generate": lambda: {
            "txn_id": f"TXN_CLEAN_{int(time.time()*1000)}_{random.randint(1000, 9999)}",
            "account_id": f"ACC_{random.randint(10000, 99999)}",
            "amount": round(random.uniform(5.0, 300.0), 2),
            "rolling_spend_10m": round(random.uniform(5.0, 300.0), 2),
            "txn_count_10m": random.randint(1, 2),
            "bitmask": 0,
            "ml_fraud_score": random.uniform(0.01, 0.3)
        }
    },
    {
        "name": "LLM Escalation (Ambiguous)",
        "weight": 15, # 15% of traffic
        "generate": lambda: {
            "txn_id": f"TXN_AMBIG_{int(time.time()*1000)}_{random.randint(1000, 9999)}",
            "account_id": f"ACC_{random.randint(10000, 99999)}",
            "amount": round(random.uniform(1000.0, 4000.0), 2), 
            "rolling_spend_10m": round(random.uniform(1000.0, 4000.0), 2),
            "txn_count_10m": random.randint(2, 4),
            "bitmask": 0,
            "ml_fraud_score": random.uniform(0.40, 0.70),
            "groq_api_key": "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"
        }
    },
    {
        "name": "Auto-Decline (High Fraud)",
        "weight": 10, # 10% of traffic
        "generate": lambda: {
            "txn_id": f"TXN_FRAUD_{int(time.time()*1000)}_{random.randint(1000, 9999)}",
            "account_id": f"ACC_{random.randint(10000, 99999)}",
            "amount": round(random.uniform(6000.0, 15000.0), 2),
            "rolling_spend_10m": round(random.uniform(10000.0, 20000.0), 2),
            "txn_count_10m": random.randint(5, 15),
            "bitmask": 0,
            "ml_fraud_score": random.uniform(0.80, 0.99)
        }
    },
    {
        "name": "Auto-Decline (Sanctions Hit)",
        "weight": 3, # 3% of traffic
        "generate": lambda: {
            "txn_id": f"TXN_SANCTIONS_{int(time.time()*1000)}_{random.randint(1000, 9999)}",
            "account_id": f"ACC_{random.randint(90000, 99999)}",
            "amount": round(random.uniform(10.0, 1000.0), 2),
            "rolling_spend_10m": round(random.uniform(10.0, 1000.0), 2),
            "txn_count_10m": 1,
            "bitmask": 1, # Sanctions flag
            "ml_fraud_score": random.uniform(0.1, 0.3)
        }
    },
    {
        "name": "Hold (Ring Detection)",
        "weight": 2, # 2% of traffic
        "generate": lambda: {
            "txn_id": f"TXN_RING_{int(time.time()*1000)}_{random.randint(1000, 9999)}",
            "account_id": f"ACC_RING_{random.randint(1, 10)}",
            "amount": round(random.uniform(4000.0, 7000.0), 2),
            "rolling_spend_10m": round(random.uniform(4000.0, 7000.0), 2),
            "txn_count_10m": random.randint(3, 8),
            "bitmask": 2, # Velocity / ring flag
            "ml_fraud_score": random.uniform(0.3, 0.6)
        }
    }
]

def pick_scenario():
    total_weight = sum(s["weight"] for s in SCENARIOS)
    r = random.uniform(0, total_weight)
    upto = 0
    for s in SCENARIOS:
        if upto + s["weight"] >= r:
            return s
        upto += s["weight"]
    return SCENARIOS[0]

async def submit_transaction(session, url, scenario):
    payload = scenario["generate"]()
    try:
        async with session.post(url, json=payload) as response:
            status = response.status
            data = await response.json()
            action = data.get('final_action', 'N/A').upper()
            score = data.get('final_score', 'N/A')
            print(f"[{time.strftime('%H:%M:%S')}] {scenario['name']} -> {action} (Score: {score})")
    except Exception as e:
        print(f"[{time.strftime('%H:%M:%S')}] Error: {e}")

async def main(url, interval):
    print(f"Starting continuous generation to {url} (Interval: ~{interval}s)")
    print("Traffic distribution: 70% Clean, 15% LLM Escalation, 10% Fraud, 3% Sanctions, 2% Ring")
    
    async with aiohttp.ClientSession() as session:
        while True:
            scenario = pick_scenario()
            asyncio.create_task(submit_transaction(session, url, scenario))
            
            # Sleep with some random jitter around the interval
            jitter = random.uniform(0.5, 1.5)
            await asyncio.sleep(interval * jitter)

if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Continuously simulate real-world transactions")
    parser.add_argument("--url", type=str, default="http://localhost:8080/submit", help="Gateway submit endpoint")
    parser.add_argument("--interval", type=float, default=2.0, help="Average seconds between transactions")
    args = parser.parse_args()
    
    try:
        asyncio.run(main(args.url, args.interval))
    except KeyboardInterrupt:
        print("Simulation stopped.")
