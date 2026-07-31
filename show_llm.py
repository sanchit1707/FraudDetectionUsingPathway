import requests
import json
import time

payload = {
    "txn_id": "TEST_LLM_SHOWCASE",
    "account_id": "ACC_SHOWCASE_001",
    "amount": 950.0,
    "rolling_spend_10m": 1200.0,
    "txn_count_10m": 1,
    "bitmask": 0,
    "ml_fraud_score": 0.55,
    "is_fraudulent": False,
    "active_threats": "clean",
    "sanctions_hit": False,
}

print("Submitting ambiguous transaction to Gateway...")
r = requests.post("http://localhost:8080/submit", json=payload).json()
print("\n--- GATEWAY RESPONSE ---")
print(f"Action: {r.get('final_action')}")
print(f"LLM Escalated: {r.get('llm_escalated')}")
print(f"LLM Verdict: {r.get('llm_verdict')}")
print(f"\n--- LLM REASONING (Final Thoughts) ---")
print(r.get("llm_reasoning"))
print(f"\n--- LLM TOOL CALLS ---")
print(json.dumps(r.get("llm_tool_calls", []), indent=2))
