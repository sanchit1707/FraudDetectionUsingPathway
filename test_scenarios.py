import asyncio
import aiohttp
import time
import json
import argparse

# Define test scenarios mapping to different system reactions
SCENARIOS = [
    {
        "name": "Auto-Approve (Clean Transaction)",
        "desc": "Low amount, low velocity. Expected: APPROVE, Tier 3.",
        "payload": {
            "txn_id": "TXN_CLEAN_1",
            "account_id": "ACC_NORMAL",
            "amount": 150.0,
            "rolling_spend_10m": 150.0,
            "txn_count_10m": 1,
            "bitmask": 0,
            "ml_fraud_score": 0.1
        }
    },
    {
        "name": "Auto-Decline (High Fraud Score)",
        "desc": "High amount, high rolling spend, high velocity. Expected: BLOCK, Tier 1.",
        "payload": {
            "txn_id": "TXN_HIGH_FRAUD_1",
            "account_id": "ACC_FRAUDSTER",
            "amount": 8000.0,
            "rolling_spend_10m": 12000.0,
            "txn_count_10m": 6,
            "bitmask": 0,
            "ml_fraud_score": 0.9
        }
    },
    {
        "name": "Auto-Decline (Sanctions Hit)",
        "desc": "Bitmask 1 triggers sanctions hit. Expected: BLOCK, Tier 1.",
        "payload": {
            "txn_id": "TXN_SANCTIONS_1",
            "account_id": "ACC_WATCHLIST",
            "amount": 100.0,
            "bitmask": 1, # Bit 0 set -> sanctions hit
            "ml_fraud_score": 0.1
        }
    },
    {
        "name": "Hold (Ring Detection)",
        "desc": "Bitmask 2 (Velocity flag), moderate score. Expected: HOLD, Tier 2 (or BLOCK Tier 1 if score high enough).",
        "payload": {
            "txn_id": "TXN_RING_1",
            "account_id": "ACC_RING_NODE",
            "amount": 6000.0, # gives +0.4 score
            "rolling_spend_10m": 2000.0,
            "txn_count_10m": 2,
            "bitmask": 2, # Bit 1 set -> ring detection
            "ml_fraud_score": 0.2 # Total score ~0.6 -> Hold
        }
    },
    {
        "name": "LLM Escalation (Ambiguous Score - Fallback Hold)",
        "desc": "Score between 0.40 and 0.75 without API key. Expected: HOLD (via LLM fallback).",
        "payload": {
            "txn_id": "TXN_AMBIG_HOLD_1",
            "account_id": "ACC_UNKNOWN",
            "amount": 5500.0, # Gives +0.4 score -> total 0.5
            "rolling_spend_10m": 100.0,
            "txn_count_10m": 1,
            "bitmask": 0,
            "ml_fraud_score": 0.1,
            "groq_api_key": "" # Triggers deterministic fallback
        }
    },
    {
        "name": "LLM Escalation (Ambiguous Score - API Call Attempt)",
        "desc": "Score between 0.40 and 0.75 WITH a fake API key to trigger actual Groq API call.",
        "payload": {
            "txn_id": "TXN_AMBIG_API_1",
            "account_id": "ACC_API_TEST",
            "amount": 5500.0, 
            "rolling_spend_10m": 100.0,
            "txn_count_10m": 1,
            "bitmask": 0,
            "ml_fraud_score": 0.1,
            "groq_api_key": "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"
        }
    }
]


async def run_scenario(session, url, scenario):
    print(f"\n--- Running Scenario: {scenario['name']} ---")
    print(f"Description: {scenario['desc']}")
    
    # Update timestamp for unique TXN IDs
    scenario['payload']['txn_id'] = f"{scenario['payload']['txn_id']}_{int(time.time())}"
    
    try:
        start = time.time()
        async with session.post(url, json=scenario['payload']) as response:
            status = response.status
            data = await response.json()
            elapsed = time.time() - start
            
            print(f"HTTP Status: {status} ({elapsed:.2f}s)")
            
            # Print the relevant reaction details
            print(f"Final Action:  {data.get('final_action', 'N/A').upper()}")
            print(f"Final Tier:    {data.get('final_tier', 'N/A')}")
            print(f"Final Score:   {data.get('final_score', 'N/A')}")
            
            llm_escalated = data.get('llm_escalated', False)
            print(f"LLM Escalated? {llm_escalated}")
            
            if llm_escalated:
                print(f"LLM Verdict:   {data.get('llm_verdict', 'N/A')}")
                print(f"LLM Reasoning: {data.get('llm_reasoning', 'N/A')}")
            
            print(f"Agent6 Result: {data.get('agent6_result', 'N/A')}")
            
    except Exception as e:
        print(f"Error calling gateway: {e}")

async def main(url):
    print(f"Targeting Gateway at: {url}")
    async with aiohttp.ClientSession() as session:
        for scenario in SCENARIOS:
            await run_scenario(session, url, scenario)
            await asyncio.sleep(1) # Small pause for readability

if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Test different transaction reactions and API calls")
    parser.add_argument("--url", type=str, default="http://localhost:8080/submit", help="Gateway submit endpoint")
    args = parser.parse_args()
    
    asyncio.run(main(args.url))
