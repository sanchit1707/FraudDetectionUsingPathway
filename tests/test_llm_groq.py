"""
tests/test_llm_groq.py
----------------------
Targeted test: verifies that the LLM escalation node actually fires
and Groq responds correctly for an AMBIGUOUS transaction (score 0.40–0.75).

The standard e2e tests use clear-cut clean / fraud scores that skip LLM.
This test deliberately submits a borderline transaction to trigger the LLM path.

Run:
    python tests/test_llm_groq.py
"""

import json
import os
import sys
import time
import requests

GATEWAY_URL = os.getenv("GATEWAY_URL", "http://localhost:8080")

GREEN = "\033[92m"
RED   = "\033[91m"
CYAN  = "\033[96m"
RESET = "\033[0m"
BOLD  = "\033[1m"


def wait_for_gateway(timeout: int = 60) -> bool:
    print("  Waiting for Gateway...", end=" ")
    deadline = time.time() + timeout
    while time.time() < deadline:
        try:
            r = requests.get(f"{GATEWAY_URL}/health", timeout=3)
            if r.status_code == 200:
                print(f"{GREEN}✓{RESET}")
                return True
        except Exception:
            pass
        time.sleep(2)
    print(f"{RED}✗ TIMEOUT{RESET}")
    return False


def test_llm_groq_ambiguous():
    """
    Submit a borderline transaction (ml_fraud_score=0.55) that lands squarely
    in the 0.40–0.75 ambiguous band, forcing LLM escalation via Groq.

    Pass conditions:
      1. llm_escalated == True       → the LLM node actually ran
      2. llm_verdict is not None     → Groq replied with a verdict
      3. final_action in allowed set → pipeline completed with a real decision
    """
    print(f"\n{BOLD}[LLM-1] Ambiguous transaction — Groq llama-3.3-70b-versatile escalation{RESET}")

    payload = {
        "txn_id":            f"LLM_TEST_{int(time.time())}",
        "account_id":        "ACC_LLM_001",
        "amount":            120.0,          # low amount → scorer won't add heuristic boost
        "rolling_spend_10m": 200.0,
        "txn_count_10m":     2,
        "bitmask":           0,              # no flag bits → clean bitmask, raw ml_score stays
        "ml_fraud_score":    0.55,            # squarely inside 0.40–0.75 ambiguous band
        "is_fraudulent":     False,
        "active_threats":    "none",
        "sanctions_hit":     False,
    }

    print(f"  Submitting txn {payload['txn_id']} (ml_score={payload['ml_fraud_score']}) ...")
    t0 = time.time()
    try:
        resp = requests.post(
            f"{GATEWAY_URL}/submit",
            json=payload,
            timeout=60,          # LLM can take up to ~30s
        ).json()
    except Exception as exc:
        print(f"  {RED}✗ REQUEST FAILED — {exc}{RESET}")
        return False

    elapsed_ms = (time.time() - t0) * 1000
    print(f"  Elapsed: {elapsed_ms:.0f}ms")

    # ── Assertions ────────────────────────────────────────────────────────────
    llm_escalated = resp.get("llm_escalated", False)
    llm_verdict   = resp.get("llm_verdict")
    llm_reasoning = resp.get("llm_reasoning", "")
    final_action  = resp.get("final_action", "unknown")
    final_score   = resp.get("final_score", 0.0)
    tool_calls    = resp.get("llm_tool_calls", [])

    print(f"  llm_escalated : {llm_escalated}")
    print(f"  llm_verdict   : {llm_verdict}")
    print(f"  final_action  : {final_action}  (score={final_score})")
    print(f"  tool_calls    : {len(tool_calls)}")
    if llm_reasoning:
        print(f"  reasoning     : {llm_reasoning[:200]}")

    passed = (
        llm_escalated is True
        and llm_verdict in ("BLOCK", "HOLD", "APPROVE")
        and final_action in ("decline", "hold", "approve")
    )

    if passed:
        print(f"\n  {GREEN}✓ PASS — Groq llama-3.3-70b-versatile responded correctly!{RESET}")
    else:
        print(f"\n  {RED}✗ FAIL{RESET}")
        print(f"  Full response: {json.dumps(resp, indent=2)}")

    return passed


def test_groq_direct():
    """
    Direct HTTP sanity-check against Groq API (no Docker needed).
    Confirms the key + model are valid before the gateway test.
    """
    import urllib.request, urllib.error

    GROQ_API_KEY = os.getenv("GROQ_API_KEY", "")
    MODEL        = os.getenv("LLM_MODEL", "llama-3.3-70b-versatile")
    if not GROQ_API_KEY:
        print(f"  {YELLOW}⚠ SKIP — GROQ_API_KEY not set in environment{RESET}")
        return True

    print(f"\n{BOLD}[LLM-0] Direct Groq API ping — {MODEL}{RESET}")

    payload = json.dumps({
        "model":      MODEL,
        "messages":   [{"role": "user", "content": "Reply with exactly: OK"}],
        "max_tokens": 10,
    }).encode()

    req = urllib.request.Request(
        "https://api.groq.com/openai/v1/chat/completions",
        data=payload,
        headers={
            "Content-Type":  "application/json",
            "Authorization": f"Bearer {GROQ_API_KEY}",
            "User-Agent":    "FlashGuard/1.0 (fraud-detection; +https://github.com/flashguard)",
        },
        method="POST",
    )

    try:
        t0 = time.time()
        with urllib.request.urlopen(req, timeout=20) as r:
            data = json.loads(r.read())
        elapsed = (time.time() - t0) * 1000
        reply = data["choices"][0]["message"]["content"].strip()
        print(f"  Model reply : \"{reply}\"")
        print(f"  Latency     : {elapsed:.0f}ms")
        print(f"  {GREEN}✓ PASS — Groq API is reachable and the key is valid{RESET}")
        return True
    except urllib.error.HTTPError as e:
        body = e.read().decode()
        print(f"  {RED}✗ HTTP {e.code} — {body}{RESET}")
        return False
    except Exception as exc:
        print(f"  {RED}✗ ERROR — {exc}{RESET}")
        return False


def run():
    print(f"\n{'='*70}")
    print(f"{BOLD}{CYAN}FLASHGUARD — GROQ LLM INTEGRATION TEST{RESET}")
    print(f"{'='*70}")

    results = {}

    # 1. Direct API ping (no Docker)
    results["groq_direct_ping"] = test_groq_direct()

    # 2. Gateway LLM escalation (needs Docker)
    if not wait_for_gateway():
        print(f"{RED}Gateway unreachable — skipping in-pipeline LLM test{RESET}")
        results["llm_escalation_via_gateway"] = False
    else:
        results["llm_escalation_via_gateway"] = test_llm_groq_ambiguous()

    # ── Summary ───────────────────────────────────────────────────────────────
    print(f"\n{'='*70}")
    print(f"{BOLD}LLM TEST SUMMARY{RESET}")
    print(f"{'='*70}")

    passed = sum(1 for v in results.values() if v)
    total  = len(results)

    for name, ok in results.items():
        status = f"{GREEN}PASS ✓{RESET}" if ok else f"{RED}FAIL ✗{RESET}"
        print(f"  {name:<40}: {status}")

    print(f"\n{'='*70}")
    if passed == total:
        print(f"{GREEN}{BOLD}🚀 ALL {total} LLM TESTS PASSED!{RESET}")
    else:
        print(f"{CYAN}ℹ {passed}/{total} TESTS PASSED{RESET}")
    print(f"{'='*70}\n")

    return passed == total


if __name__ == "__main__":
    success = run()
    sys.exit(0 if success else 1)
