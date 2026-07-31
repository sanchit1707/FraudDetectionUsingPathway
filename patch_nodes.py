import os
import json
import re

file_path = r"C:\Users\tirth\Downloads\FraudDetectionUsingPathway-to-be-stitched\FraudDetectionUsingPathway-main\orcestrator\nodes.py"

with open(file_path, "r", encoding="utf-8") as f:
    content = f.read()

# I want to find the LLM node and replace it with a new implementation
# that uses a batching queue.

new_node_code = """
import threading
import queue
import urllib.request
import urllib.error
from tenacity import retry, stop_after_attempt, wait_exponential, retry_if_exception_type
from orcestrator.mcp_tools import _execute_get_account_details, _execute_query_compliance_rules

class LLMBatcher:
    def __init__(self):
        self.queue = []
        self.lock = threading.Lock()
        self.cond = threading.Condition(self.lock)
        self.results = {}
        self.thread = threading.Thread(target=self._worker, daemon=True)
        self.thread.start()

    def submit(self, txn_id, state, context):
        event = threading.Event()
        with self.lock:
            self.queue.append({
                "txn_id": txn_id,
                "state": state,
                "context": context,
                "event": event
            })
            self.cond.notify()
        event.wait()
        with self.lock:
            return self.results.pop(txn_id, {"error": "no result"})

    def _worker(self):
        LLM_MODEL = os.getenv("LLM_MODEL", "llama-3.3-70b-versatile")
        
        while True:
            batch = []
            with self.cond:
                # Wait for at least one item
                while not self.queue:
                    self.cond.wait()
                # Wait a bit to accumulate more items
                self.cond.wait(timeout=1.5)
                # Take up to 10 items
                batch = self.queue[:10]
                self.queue = self.queue[10:]
                
            if not batch:
                continue

            active_groq_key = next((item["state"].get("groq_api_key") for item in batch if item["state"].get("groq_api_key")), None) or os.getenv("GROQ_API_KEY", "")
            if not active_groq_key or active_groq_key == "your_groq_api_key_here":
                # Deterministic fallback
                for item in batch:
                    txn_id = item["txn_id"]
                    score = item["state"].get("fraud_score", 0.5)
                    verdict = "BLOCK" if score > 0.65 else "HOLD"
                    with self.lock:
                        self.results[txn_id] = {
                            "verdict": verdict,
                            "reasoning": f"Deterministic fallback (no LLM key provided). Score={score:.3f}"
                        }
                    item["event"].set()
                continue
                
            # Formulate the prompt
            batch_data_str = ""
            for item in batch:
                st = item["state"]
                ctx = item["context"]
                acc = ctx.get("account_details", {})
                rag = ctx.get("rag_snippets", [])
                
                batch_data_str += f\"\"\"
---
TRANSACTION ID: {item['txn_id']}
Account: {st.get('cust_token', 'UNKNOWN')}
Amount: ${st.get('features', {}).get('amount', 0):.2f}
ML Score: {st.get('fraud_score', 0):.3f}
Velocity Flag: {bool(st.get('bitmask', 0) & (1 << 1))}
Account History: Last Verdict: {acc.get('last_verdict')}, Risk Tier: {acc.get('risk_tier')}, Open Cases: {acc.get('open_cases')}
Compliance Rules: {', '.join(rag)}
\"\"\"

            sys_prompt = f\"\"\"You are FlashGuard's fraud investigation agent. You are evaluating a batch of AMBIGUOUS transactions.
For each transaction, you must decide: APPROVE, HOLD, or BLOCK.

{batch_data_str}

Respond STRICTLY with a JSON array of objects. Do not include markdown formatting or extra text.
Format:
[
  {{"txn_id": "STREAM_...", "verdict": "APPROVE|HOLD|BLOCK", "reasoning": "short reason"}}, ...
]
\"\"\"
            
            try:
                # Add a wrapper JSON format instruction because Groq requires response_format string to contain "JSON"
                payload = json.dumps({
                    "model": LLM_MODEL,
                    "messages": [{"role": "user", "content": sys_prompt + "\\n\\nOutput JSON object like: {\\"results\\": [...]}"}],
                    "temperature": 0.1,
                    "response_format": {"type": "json_object"}
                }).encode()

                req = urllib.request.Request(
                    "https://api.groq.com/openai/v1/chat/completions",
                    data=payload,
                    headers={
                        "Content-Type": "application/json",
                        "Authorization": f"Bearer {active_groq_key}",
                        "User-Agent": "FlashGuard/1.0"
                    },
                    method="POST",
                )
                
                @retry(stop=stop_after_attempt(5), wait=wait_exponential(multiplier=1.5, min=2, max=20))
                def _do_call():
                    with urllib.request.urlopen(req, timeout=30) as resp:
                        return json.loads(resp.read())
                
                llm_resp = _do_call()
                content = llm_resp["choices"][0]["message"]["content"]
                
                try:
                    parsed = json.loads(content)
                    results_list = parsed.get("results", [])
                    if isinstance(parsed, list):
                        results_list = parsed
                except Exception as e:
                    logger.error("[LLMBatcher] Failed to parse JSON: %s", e)
                    results_list = []
                    
                # Map results
                res_map = {}
                for r in results_list:
                    if isinstance(r, dict) and "txn_id" in r:
                        res_map[r["txn_id"]] = r
                
                for item in batch:
                    txn_id = item["txn_id"]
                    res = res_map.get(txn_id, {})
                    with self.lock:
                        self.results[txn_id] = {
                            "verdict": res.get("verdict", "HOLD").upper(),
                            "reasoning": res.get("reasoning", "JSON parse failure - fallback HOLD")
                        }
                    item["event"].set()
                    
            except Exception as e:
                logger.error("[LLMBatcher] API call failed: %s", e)
                for item in batch:
                    with self.lock:
                        self.results[item["txn_id"]] = {
                            "verdict": "HOLD",
                            "reasoning": f"Batch API failure: {e}"
                        }
                    item["event"].set()

batcher = LLMBatcher()

def llm_escalation_node(state: OrchestratorState) -> dict:
    txn_id = state["txn_id"]
    target_account = state.get("cust_token", "UNKNOWN")

    emit_node_enter(txn_id, "llm_escalation", {
        "fraud_score": state.get("fraud_score"),
        "final_tier": state.get("final_tier"),
    })
    
    # ── Pre-fetch context ──────────────────────────────────────────────────────
    try:
        acc_details = _execute_get_account_details(target_account, "batch_evaluation")
    except Exception:
        acc_details = {}
        
    try:
        query = f"AML/BSA regulations for transactions with ML Fraud Score {state.get('fraud_score', 0):.3f}"
        rag_data = _execute_query_compliance_rules(query)
        rag_snippets = rag_data.get("compliance_context", [])
    except Exception:
        rag_snippets = []

    # ── Submit to Batcher ──────────────────────────────────────────────────────
    res = batcher.submit(txn_id, state, {
        "account_details": acc_details,
        "rag_snippets": rag_snippets
    })
    
    llm_verdict = res.get("verdict", "HOLD")
    llm_reasoning = res.get("reasoning", "")
    
    # Map LLM verdict to tier/action
    if llm_verdict == "BLOCK":
        final_tier, final_action = 1, "decline"
        final_score = max(state.get("fraud_score", 0.75), 0.86)
    elif llm_verdict == "APPROVE":
        final_tier, final_action = 3, "approve"
        final_score = min(state.get("fraud_score", 0.5), 0.39)
    else:
        final_tier, final_action = 2, "hold"
        final_score = state.get("fraud_score", 0.6)

    result = {
        "llm_verdict": llm_verdict,
        "llm_reasoning": llm_reasoning[:500],
        "llm_tool_calls": [],
        "llm_source": f"groq/llama-3.3-70b-versatile-batch",
        "llm_escalated": True,
        "final_tier": final_tier,
        "final_action": final_action,
        "final_score": round(final_score, 4),
    }

    emit_node_exit(txn_id, "llm_escalation", {
        "llm_verdict": llm_verdict,
        "tool_calls": 0,
        "final_action": final_action,
    })
    return result
"""

# Now replace the old function with the new one.
start_idx = content.find("def llm_escalation_node(state: OrchestratorState) -> dict:")
end_idx = content.find("# FALLBACK Node (watchdog trip)", start_idx)
if start_idx != -1 and end_idx != -1:
    end_idx = content.rfind("# ═══════════════════════════════════════════════════════════════════════════════", start_idx, end_idx)
    new_content = content[:start_idx] + new_node_code + "\n\n" + content[end_idx:]
    with open(file_path, "w", encoding="utf-8") as f:
        f.write(new_content)
    print("Patched successfully")
else:
    print("Could not find patch points")
