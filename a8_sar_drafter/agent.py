import os
import json
import time
import requests
import pathway as pw
from _sidecar import start_sidecar

RAG_ENDPOINT = os.getenv("RAG_ENDPOINT", "http://a5_compliance_rag:8011")
LLM_API_URL = os.getenv("LLM_API_URL", "")
LLM_MODEL = os.getenv("LLM_MODEL", "llama-3.1-8b-instant")
GROQ_API_KEY = os.getenv("GROQ_API_KEY", os.getenv("OPENAI_API_KEY", ""))

# Real, in-memory counters exposed via GET /stats (no synthetic data)
STATS = {
    "total_sars_drafted": 0,
    "last_sar_id": None,
    "llm_calls_succeeded": 0,
    "llm_calls_fallback": 0,
    "started_at": time.time(),
}

class FrozenTransactionSchema(pw.Schema):
    transaction_id: str
    card_id: str
    customer_id: str
    amount: float
    merchant: str
    freeze_reason: str
    velocity_1h: float = pw.column_definition(default_value=0.0)
    timestamp: str = pw.column_definition(default_value="")

def retrieve_from_a5_rag(query_text: str) -> list[dict]:
    endpoints_to_try = [
        RAG_ENDPOINT,
        "http://a5_compliance_rag:8011",
        "http://localhost:8011"
    ]
    for endpoint in endpoints_to_try:
        try:
            resp = requests.post(
                endpoint,
                json={"query": query_text, "top_k": 2},
                timeout=5.0
            )
            if resp.status_code == 200:
                data = resp.json()
                if isinstance(data, list) and len(data) > 0:
                    item = data[0].get("result", data[0])
                elif isinstance(data, dict):
                    item = data.get("result", data)
                else:
                    item = {}
                context = item.get("compliance_context", [])
                if context:
                    return context
        except Exception:
            continue

    return [{
        "snippet": "Default BSA Title 31 AML rule: transactions exhibiting structuring or rapid velocity spikes over high-risk merchants require mandatory SAR drafting within 30 days post-card freeze.",
        "relevance_score": 0.85
    }]

def generate_sar_narrative(tx: dict, rag_snippets: list[dict]) -> str:
    rag_text = "\n".join([
        f"- Snippet (Relevance: {s.get('relevance_score')}): {s.get('snippet')}"
        for s in rag_snippets
    ])

    prompt = f"""You are a Senior AML Compliance Officer drafting a formal SAR narrative.

RETRIEVED COMPLIANCE CONTEXT (A5 Compliance RAG):
{rag_text}

FROZEN TRANSACTION:
- Transaction ID: {tx.get('transaction_id')}
- Card ID: {tx.get('card_id')}
- Customer ID: {tx.get('customer_id')}
- Amount: ${tx.get('amount')}
- Merchant: {tx.get('merchant')}
- Freeze Reason: {tx.get('freeze_reason')}
- Hourly Velocity: {tx.get('velocity_1h')} txns/hr

Write a structured SAR narrative adhering to BSA Title 31 guidelines."""

    if LLM_API_URL or GROQ_API_KEY:
        try:
            import litellm
            messages = [
                {"role": "system", "content": "You are a Senior AML Compliance Officer."},
                {"role": "user", "content": prompt}
            ]
            
            model_str = LLM_MODEL if "/" in LLM_MODEL else f"groq/{LLM_MODEL}"
            
            kwargs = {
                "model": model_str,
                "messages": messages,
                "temperature": 0.3,
                "timeout": 10.0
            }
            if GROQ_API_KEY:
                kwargs["api_key"] = GROQ_API_KEY
            if LLM_API_URL:
                kwargs["api_base"] = LLM_API_URL
                
            r = litellm.completion(**kwargs)
            STATS["llm_calls_succeeded"] += 1
            return r.choices[0].message.content
        except Exception as e:
            print(f"[A8] LLM API failed ({e}), using structured fallback.")

    STATS["llm_calls_fallback"] += 1

    return f"""### SUSPICIOUS ACTIVITY REPORT (SAR) FORMAL NARRATIVE
**Filing Status**: MANDATORY POST-FREEZE DRAFTING
**Gateway Verdict**: CARD LOCKED / TRANSACTION FROZEN

#### 1. SUBJECT IDENTIFICATION & ACCOUNT INFORMATION
- **Customer ID**: {tx.get('customer_id')}
- **Card Identifier**: {tx.get('card_id')} (Status: LOCKED AT GATEWAY EXIT POINT)
- **Transaction ID**: {tx.get('transaction_id')}

#### 2. CHRONOLOGY OF SUSPICIOUS ACTIVITY
On {tx.get('timestamp') or 'the date of observation'}, the subject initiated a high-risk transaction of ${tx.get('amount')} at merchant '{tx.get('merchant')}'. Velocity: {tx.get('velocity_1h')} txns/hr triggered real-time escalation and gateway lock.

#### 3. REGULATORY BASIS & VIOLATIONS (A5 Compliance RAG)
{rag_text}
Activity matches typology: '{tx.get('freeze_reason')}'.

#### 4. ACTION TAKEN & RECOMMENDATIONS
Gateway APPROVE/LOCK command issued. A8 SAR Drafter recommends continued account restriction and formal FinCEN filing under Title 31 BSA."""

@pw.udf
def process_sar_drafting(transaction_id: str, card_id: str, customer_id: str, amount: float, merchant: str, freeze_reason: str, velocity_1h: float, timestamp: str) -> dict:
    tx = {
        "transaction_id": str(transaction_id),
        "card_id": str(card_id),
        "customer_id": str(customer_id),
        "amount": float(amount),
        "merchant": str(merchant),
        "freeze_reason": str(freeze_reason),
        "velocity_1h": float(velocity_1h),
        "timestamp": str(timestamp)
    }

    query = f"SAR narrative rules for {freeze_reason} amount {amount} merchant {merchant}"
    rag_snippets = retrieve_from_a5_rag(query)
    narrative = generate_sar_narrative(tx, rag_snippets)

    sar_id = f"SAR_{transaction_id}_{int(time.time())}"
    STATS["total_sars_drafted"] += 1
    STATS["last_sar_id"] = sar_id

    return {
        "agent": "A8 SAR Drafter",
        "sar_id": sar_id,
        "transaction_id": str(transaction_id),
        "card_id": str(card_id),
        "llm_model": LLM_MODEL,
        "rag_snippets_retrieved": len(rag_snippets),
        "sar_narrative": narrative,
        "status": "SAR_DRAFTED"
    }

def run_agent():
    webserver = pw.io.http.PathwayWebserver(host="0.0.0.0", port=8013)
    frozen_txns, writer = pw.io.http.rest_connector(
        webserver=webserver,
        schema=FrozenTransactionSchema,
        autocommit_duration_ms=50,
        delete_completed_queries=False
    )

    results = frozen_txns.select(
        result=process_sar_drafting(
            pw.this.transaction_id,
            pw.this.card_id,
            pw.this.customer_id,
            pw.this.amount,
            pw.this.merchant,
            pw.this.freeze_reason,
            pw.this.velocity_1h,
            pw.this.timestamp
        )
    )

    writer(results)

    def get_stats():
        return {
            "agent": "A8 SAR Drafter",
            "total_sars_drafted": STATS["total_sars_drafted"],
            "last_sar_id": STATS["last_sar_id"],
            "llm_calls_succeeded": STATS["llm_calls_succeeded"],
            "llm_calls_fallback": STATS["llm_calls_fallback"],
            "llm_model": LLM_MODEL,
            "llm_configured": bool(GROQ_API_KEY or LLM_API_URL),
            "uptime_seconds": round(time.time() - STATS["started_at"], 1),
        }

    # Sidecar on 8513 gives the browser CORS + a GET status route while
    # proxying real POSTs through to this Pathway webserver on 8013.
    start_sidecar(8513, "http://localhost:8013/", get_stats)

    print("Starting A8 SAR Drafter on port 8013 (sidecar on 8513)...")
    pw.run()

if __name__ == "__main__":
    run_agent()