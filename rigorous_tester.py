import asyncio
import aiohttp
import time
import json
import argparse
import random

GROQ_API_KEY = "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"

SCENARIOS = [
    {
        "name": "Auto-Approve (Clean)",
        "expected_action": "APPROVE",
        "generate": lambda: {
            "txn_id": f"TXN_CLEAN_{int(time.time()*1000)}_{random.randint(1000, 9999)}",
            "account_id": f"ACC_{random.randint(10000, 99999)}",
            "amount": round(random.uniform(5.0, 50.0), 2),
            "rolling_spend_10m": round(random.uniform(5.0, 50.0), 2),
            "txn_count_10m": 1,
            "bitmask": 0,
            "ml_fraud_score": random.uniform(0.01, 0.2)
        }
    },
    {
        "name": "Auto-Decline (High Fraud)",
        "expected_action": "DECLINE",
        "generate": lambda: {
            "txn_id": f"TXN_FRAUD_{int(time.time()*1000)}_{random.randint(1000, 9999)}",
            "account_id": f"ACC_{random.randint(10000, 99999)}",
            "amount": round(random.uniform(6000.0, 15000.0), 2),
            "rolling_spend_10m": round(random.uniform(10000.0, 20000.0), 2),
            "txn_count_10m": random.randint(5, 15),
            "bitmask": 0,
            "ml_fraud_score": random.uniform(0.85, 0.99)
        }
    },
    {
        "name": "LLM Escalation (Ambiguous)",
        "expected_escalation": True,
        "generate": lambda: {
            "txn_id": f"TXN_AMBIG_{int(time.time()*1000)}_{random.randint(1000, 9999)}",
            "account_id": f"ACC_{random.randint(10000, 99999)}",
            "amount": round(random.uniform(1000.0, 4000.0), 2), 
            "rolling_spend_10m": round(random.uniform(1000.0, 4000.0), 2),
            "txn_count_10m": random.randint(2, 4),
            "bitmask": 0,
            "ml_fraud_score": random.uniform(0.40, 0.70),
            "groq_api_key": GROQ_API_KEY
        }
    }
]

async def submit_transaction(session, url, scenario, results):
    payload = scenario["generate"]()
    start_time = time.time()
    try:
        async with session.post(url, json=payload, timeout=30) as response:
            status = response.status
            data = await response.json()
            latency = time.time() - start_time
            
            action = data.get('final_action', 'N/A').upper()
            escalated = data.get('llm_escalated', False)
            
            success = True
            error_msg = ""
            
            if "expected_action" in scenario and scenario["expected_action"] != action:
                success = False
                error_msg = f"Expected {scenario['expected_action']}, got {action}"
                
            if "expected_escalation" in scenario and scenario["expected_escalation"] != escalated:
                success = False
                error_msg = f"Expected escalation={scenario['expected_escalation']}, got {escalated}"
                
            results.append({
                "scenario": scenario["name"],
                "success": success,
                "latency": latency,
                "error": error_msg,
                "action": action,
                "escalated": escalated
            })
            print(f"[{time.strftime('%H:%M:%S')}] {scenario['name']} -> {action} (Escalated: {escalated}) [{latency:.2f}s] {'[SUCCESS]' if success else '[FAILED] ' + error_msg}")
    except Exception as e:
        results.append({
            "scenario": scenario["name"],
            "success": False,
            "latency": time.time() - start_time,
            "error": str(e),
            "action": "ERROR",
            "escalated": False
        })
        print(f"[{time.strftime('%H:%M:%S')}] {scenario['name']} -> ERROR: {e}")

async def main(url, count):
    print(f"--- Starting Rigorous Transaction Test ---")
    print(f"Targeting: {url}")
    print(f"Transactions to run: {count}")
    
    results = []
    
    async with aiohttp.ClientSession() as session:
        tasks = []
        for _ in range(count):
            scenario = random.choice(SCENARIOS)
            tasks.append(submit_transaction(session, url, scenario, results))
            # Sleep a tiny bit to stagger requests
            await asyncio.sleep(0.5)
            
        await asyncio.gather(*tasks)
        
    print("\n--- Test Summary ---")
    successful = sum(1 for r in results if r["success"])
    total = len(results)
    avg_latency = sum(r["latency"] for r in results) / total if total > 0 else 0
    
    print(f"Total Transactions: {total}")
    print(f"Successful Validations: {successful}/{total} ({successful/total*100:.1f}%)")
    print(f"Average Latency: {avg_latency:.2f}s")
    
    if successful < total:
        print("\n--- Failures ---")
        for r in results:
            if not r["success"]:
                print(f"{r['scenario']}: {r['error']} (Latency: {r['latency']:.2f}s)")
                
    if successful == total:
        print("\n[SUCCESS] All rigorous checks passed.")
    else:
        print("\n[FAILED] Some checks failed.")

if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Rigorous test of the FlashGuard Gateway")
    parser.add_argument("--url", type=str, default="http://localhost:8080/submit", help="Gateway submit endpoint")
    parser.add_argument("--count", type=int, default=15, help="Number of transactions to simulate")
    args = parser.parse_args()
    
    asyncio.run(main(args.url, args.count))
