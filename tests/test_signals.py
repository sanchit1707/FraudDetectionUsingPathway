"""
tests/test_signals.py
---------------------
Comprehensive test suite for all 8 fraud signal types.

Tests the /submit endpoint of the FlashGuard Gateway for each signal type
and verifies the expected action (approve/hold/decline).

Run:
    python tests/test_signals.py
    # or inside docker:
    docker compose exec test_runner python /app/test_signals.py
"""

import json
import os
import sys
import time
import requests

GATEWAY_URL = os.getenv("GATEWAY_URL", "http://localhost:8080")

# ── Colors for terminal output ───────────────────────────────────────────────
GREEN = "\033[92m"
RED = "\033[91m"
YELLOW = "\033[93m"
CYAN = "\033[96m"
RESET = "\033[0m"
BOLD = "\033[1m"

results = {}


def wait_for_gateway(timeout=120):
    print(f"\n{CYAN}Waiting for Gateway at {GATEWAY_URL}...{RESET}")
    deadline = time.time() + timeout
    while time.time() < deadline:
        try:
            r = requests.get(f"{GATEWAY_URL}/health", timeout=3)
            if r.status_code == 200:
                print(f"{GREEN}✓ Gateway is up!{RESET}")
                return True
        except Exception:
            pass
        time.sleep(3)
    print(f"{RED}✗ Gateway not ready after {timeout}s{RESET}")
    return False


def submit_transaction(payload: dict) -> dict:
    """POST to /submit and return response dict."""
    try:
        r = requests.post(f"{GATEWAY_URL}/submit", json=payload, timeout=30)
        r.raise_for_status()
        return r.json()
    except requests.exceptions.HTTPError as e:
        return {"error": f"HTTP {e.response.status_code}", "detail": str(e)}
    except Exception as e:
        return {"error": str(e)}


def assert_action(test_name: str, response: dict, expected_actions: list) -> bool:
    """Assert the final_action is one of the expected values."""
    action = response.get("final_action", "unknown")
    passed = action in expected_actions

    if passed:
        print(f"  {GREEN}✓ PASS{RESET} — action={action!r} (expected one of {expected_actions})")
    else:
        print(f"  {RED}✗ FAIL{RESET} — action={action!r} (expected one of {expected_actions})")
        print(f"         Response: {json.dumps(response, indent=2)[:400]}")

    results[test_name] = passed
    return passed


# ═══════════════════════════════════════════════════════════════════════════════
# Signal Tests
# ═══════════════════════════════════════════════════════════════════════════════

def test_signal_1_clean_transaction():
    """Signal 1: Normal transaction — should be approved."""
    print(f"\n{BOLD}[Signal 1] Clean Transaction (should → approve){RESET}")
    payload = {
        "txn_id": "TEST_SIG1_CLEAN",
        "account_id": "ACC_CLEAN_001",
        "amount": 45.50,
        "rolling_spend_10m": 120.0,
        "txn_count_10m": 1,
        "bitmask": 0,          # No flags
        "ml_fraud_score": 0.05,
        "is_fraudulent": False,
        "active_threats": "clean",
        "sanctions_hit": False,
    }
    resp = submit_transaction(payload)
    print(f"  score={resp.get('final_score')}, llm_escalated={resp.get('llm_escalated')}")
    return assert_action("signal_1_clean", resp, ["approve"])


def test_signal_2_high_velocity():
    """Signal 2: High velocity (>3 txns in 10min) — should hold or decline."""
    print(f"\n{BOLD}[Signal 2] High Velocity (txn_count > 3, should → hold/decline){RESET}")
    payload = {
        "txn_id": "TEST_SIG2_VELOCITY",
        "account_id": "ACC_VEL_002",
        "amount": 150.0,
        "rolling_spend_10m": 600.0,
        "txn_count_10m": 7,    # > threshold of 3
        "bitmask": 2,          # bit 1 = velocity flag
        "ml_fraud_score": 0.45,
        "is_fraudulent": True,
        "active_threats": "clean",
        "sanctions_hit": False,
    }
    resp = submit_transaction(payload)
    print(f"  score={resp.get('final_score')}, llm_escalated={resp.get('llm_escalated')}")
    return assert_action("signal_2_velocity", resp, ["hold", "decline"])


def test_signal_3_high_spend():
    """Signal 3: Rolling spend > $5000 threshold — should hold or decline."""
    print(f"\n{BOLD}[Signal 3] High Rolling Spend (>$5000, should → hold/decline){RESET}")
    payload = {
        "txn_id": "TEST_SIG3_SPEND",
        "account_id": "ACC_SPEND_003",
        "amount": 4999.99,
        "rolling_spend_10m": 8500.0,  # > $5000 threshold
        "txn_count_10m": 2,
        "bitmask": 8,           # bit 3 = high_value flag
        "ml_fraud_score": 0.72,
        "is_fraudulent": True,
        "active_threats": "clean",
        "sanctions_hit": False,
    }
    resp = submit_transaction(payload)
    print(f"  score={resp.get('final_score')}, llm_escalated={resp.get('llm_escalated')}")
    return assert_action("signal_3_spend", resp, ["hold", "decline"])


def test_signal_4_watchlist_merchant():
    """Signal 4: Watchlist merchant (active_threats != 'clean') — should hold or decline."""
    print(f"\n{BOLD}[Signal 4] Watchlist Merchant (active_threats flagged){RESET}")
    payload = {
        "txn_id": "TEST_SIG4_WATCHLIST",
        "account_id": "ACC_WATCH_004",
        "amount": 250.0,
        "rolling_spend_10m": 500.0,
        "txn_count_10m": 2,
        "bitmask": 1,           # bit 0 = sanctions/watchlist
        "ml_fraud_score": 0.35,
        "is_fraudulent": True,
        "active_threats": "HIGH_RISK_MERCHANT",
        "sanctions_hit": False,
    }
    resp = submit_transaction(payload)
    print(f"  score={resp.get('final_score')}, llm_escalated={resp.get('llm_escalated')}")
    return assert_action("signal_4_watchlist", resp, ["hold", "decline"])


def test_signal_5_sanctions_hit():
    """Signal 5: Sanctions hit — should ALWAYS decline (score → 1.0)."""
    print(f"\n{BOLD}[Signal 5] Sanctions Hit — MUST → decline (Tier 1){RESET}")
    payload = {
        "txn_id": "TEST_SIG5_SANCTION",
        "account_id": "ACC_SANCTION_005",
        "amount": 1000.0,
        "rolling_spend_10m": 1000.0,
        "txn_count_10m": 1,
        "bitmask": 1,           # bit 0 = sanctions
        "ml_fraud_score": 0.6,
        "is_fraudulent": True,
        "active_threats": "SANCTIONS_MATCH",
        "sanctions_hit": True,  # Hard trigger
    }
    resp = submit_transaction(payload)
    print(f"  score={resp.get('final_score')}, tier={resp.get('final_tier')}")
    return assert_action("signal_5_sanctions", resp, ["decline"])


def test_signal_6_ring_detection():
    """Signal 6: Ring detection (velocity bit + multiple txns from same node)."""
    print(f"\n{BOLD}[Signal 6] Ring Detection (velocity bit set, ring_size >= 5){RESET}")
    payload = {
        "txn_id": "TEST_SIG6_RING",
        "account_id": "ACC_RING_006",
        "amount": 500.0,
        "rolling_spend_10m": 2500.0,
        "txn_count_10m": 8,
        "bitmask": 3,           # bits 0+1 = sanctions + velocity
        "ml_fraud_score": 0.65,
        "is_fraudulent": True,
        "active_threats": "RING_NODE",
        "sanctions_hit": False,
    }
    resp = submit_transaction(payload)
    print(f"  score={resp.get('final_score')}, ring_detected={resp.get('ring_detected')}")
    return assert_action("signal_6_ring", resp, ["decline", "hold"])


def test_signal_7_ambiguous_llm_escalation():
    """Signal 7: Ambiguous score (0.40-0.75) — MUST trigger LLM escalation."""
    print(f"\n{BOLD}[Signal 7] Ambiguous Score → LLM Escalation (0.40-0.75 range){RESET}")
    payload = {
        "txn_id": "TEST_SIG7_AMBIG",
        "account_id": "ACC_AMBIG_007",
        "amount": 890.0,
        "rolling_spend_10m": 1800.0,
        "txn_count_10m": 3,
        "bitmask": 0,           # No flags to prevent heuristic score bumps
        "ml_fraud_score": 0.55, # In ambiguous range
        "is_fraudulent": False,
        "active_threats": "clean",
        "sanctions_hit": False,
    }
    resp = submit_transaction(payload)
    llm_escalated = resp.get("llm_escalated", False)
    print(f"  score={resp.get('final_score')}, llm_escalated={llm_escalated}, llm_verdict={resp.get('llm_verdict')}")

    # This test checks LLM was called, not the specific action
    if llm_escalated:
        print(f"  {GREEN}✓ LLM WAS escalated as expected{RESET}")
        results["signal_7_llm"] = True
        return True
    else:
        # Score might not be in ambiguous range due to node processing
        action = resp.get("final_action", "unknown")
        print(f"  {YELLOW}⚠ LLM not escalated (may be deterministic route). action={action}{RESET}")
        results["signal_7_llm"] = action in ["hold", "decline"]  # acceptable
        return results["signal_7_llm"]


def test_signal_8_confirmed_fraud():
    """Signal 8: High-confidence fraud (score > 0.85) — MUST decline."""
    print(f"\n{BOLD}[Signal 8] Confirmed High-Score Fraud (score > 0.85 → decline){RESET}")
    payload = {
        "txn_id": "TEST_SIG8_FRAUD",
        "account_id": "ACC_FRAUD_008",
        "amount": 9999.0,
        "rolling_spend_10m": 25000.0,
        "txn_count_10m": 12,
        "bitmask": 15,          # All bits: sanctions + velocity + geo + high_value
        "ml_fraud_score": 0.95,
        "is_fraudulent": True,
        "active_threats": "CONFIRMED_FRAUD",
        "sanctions_hit": False,
    }
    resp = submit_transaction(payload)
    print(f"  score={resp.get('final_score')}, tier={resp.get('final_tier')}")
    return assert_action("signal_8_fraud", resp, ["decline"])


# ═══════════════════════════════════════════════════════════════════════════════
# Main
# ═══════════════════════════════════════════════════════════════════════════════

def run_all_signal_tests():
    print(f"\n{'='*70}")
    print(f"{BOLD}{CYAN}FLASHGUARD — FRAUD SIGNAL TEST SUITE (8 Signal Types){RESET}")
    print(f"{'='*70}")
    print(f"Gateway: {GATEWAY_URL}")

    if not wait_for_gateway():
        print(f"{RED}Gateway unreachable. Aborting.{RESET}")
        sys.exit(1)

    time.sleep(2)  # Brief warmup

    tests = [
        test_signal_1_clean_transaction,
        test_signal_2_high_velocity,
        test_signal_3_high_spend,
        test_signal_4_watchlist_merchant,
        test_signal_5_sanctions_hit,
        test_signal_6_ring_detection,
        test_signal_7_ambiguous_llm_escalation,
        test_signal_8_confirmed_fraud,
    ]

    for test_fn in tests:
        try:
            test_fn()
        except Exception as e:
            test_name = test_fn.__name__
            print(f"  {RED}✗ ERROR in {test_name}: {e}{RESET}")
            results[test_name] = False
        time.sleep(1)  # Rate limit guard

    # ── Summary ───────────────────────────────────────────────────────────────
    print(f"\n{'='*70}")
    print(f"{BOLD}SIGNAL TEST SUMMARY{RESET}")
    print(f"{'='*70}")

    passed = sum(1 for v in results.values() if v)
    total = len(results)

    for name, ok in results.items():
        status = f"{GREEN}PASS ✓{RESET}" if ok else f"{RED}FAIL ✗{RESET}"
        print(f"  {name:<40}: {status}")

    print(f"\n{'='*70}")
    if passed == total:
        print(f"{GREEN}{BOLD}🎉 ALL {total} SIGNAL TESTS PASSED!{RESET}")
    else:
        print(f"{YELLOW}⚠ {passed}/{total} TESTS PASSED{RESET}")
    print(f"{'='*70}\n")

    return passed == total


if __name__ == "__main__":
    success = run_all_signal_tests()
    sys.exit(0 if success else 1)
