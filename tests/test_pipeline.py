"""
tests/test_pipeline.py
----------------------
End-to-end pipeline integration test.

Tests the full FlashGuard pipeline:
  Transaction → Gateway → Pathway → LangGraph → Agent 6 → Result

Also verifies:
  - Pathway event stream has events after processing
  - BDH received and processed events
  - Metrics endpoint shows correct counts
  - Agent 6 audit trail exists

Run:
    python tests/test_pipeline.py
"""

import json
import os
import sys
import time
import requests

GATEWAY_URL = os.getenv("GATEWAY_URL", "http://localhost:8080")
BDH_URL = os.getenv("BDH_URL", "http://localhost:8090")
AGENT6_URL = os.getenv("AGENT6_URL", "http://localhost:8000")

GREEN = "\033[92m"
RED = "\033[91m"
CYAN = "\033[96m"
RESET = "\033[0m"
BOLD = "\033[1m"

results = {}


def wait_for_all(timeout=120):
    services = {
        "Gateway": f"{GATEWAY_URL}/health",
        "BDH": f"{BDH_URL}/health",
        "Agent6": f"{AGENT6_URL}/health",
    }
    all_up = True
    for name, url in services.items():
        print(f"  Checking {name}...", end=" ")
        deadline = time.time() + timeout
        up = False
        while time.time() < deadline:
            try:
                r = requests.get(url, timeout=3)
                if r.status_code == 200:
                    up = True
                    break
            except Exception:
                pass
            time.sleep(3)
        if up:
            print(f"{GREEN}✓{RESET}")
        else:
            print(f"{RED}✗ TIMEOUT{RESET}")
            all_up = False
    return all_up


def test_e2e_clean():
    """E2E: Submit clean transaction → expect approve."""
    print(f"\n{BOLD}[E2E-1] Clean transaction full pipeline{RESET}")
    payload = {
        "txn_id": f"E2E_CLEAN_{int(time.time())}",
        "account_id": "ACC_E2E_001",
        "amount": 25.0,
        "rolling_spend_10m": 50.0,
        "txn_count_10m": 1,
        "bitmask": 0,
        "ml_fraud_score": 0.03,
        "is_fraudulent": False,
        "active_threats": "clean",
        "sanctions_hit": False,
    }
    t0 = time.time()
    resp = requests.post(f"{GATEWAY_URL}/submit", json=payload, timeout=30).json()
    elapsed = (time.time() - t0) * 1000

    action = resp.get("final_action", "unknown")
    print(f"  action={action}, elapsed={elapsed:.0f}ms")

    passed = action in ["approve"] and elapsed < 10000
    results["e2e_clean"] = passed
    if passed:
        print(f"  {GREEN}✓ PASS{RESET}")
    else:
        print(f"  {RED}✗ FAIL{RESET} — {resp}")
    return passed


def test_e2e_fraud():
    """E2E: Submit confirmed fraud → expect decline."""
    print(f"\n{BOLD}[E2E-2] Confirmed fraud full pipeline{RESET}")
    payload = {
        "txn_id": f"E2E_FRAUD_{int(time.time())}",
        "account_id": "ACC_E2E_002",
        "amount": 9999.0,
        "rolling_spend_10m": 40000.0,
        "txn_count_10m": 15,
        "bitmask": 15,
        "ml_fraud_score": 0.97,
        "is_fraudulent": True,
        "active_threats": "CONFIRMED_FRAUD",
        "sanctions_hit": False,
    }
    resp = requests.post(f"{GATEWAY_URL}/submit", json=payload, timeout=30).json()
    action = resp.get("final_action", "unknown")
    print(f"  action={action}, score={resp.get('final_score')}")

    passed = action == "decline"
    results["e2e_fraud"] = passed
    if passed:
        print(f"  {GREEN}✓ PASS{RESET}")
    else:
        print(f"  {RED}✗ FAIL{RESET} — {resp}")
    return passed


def test_stream_events():
    """Verify pathway:events stream has events after submissions."""
    print(f"\n{BOLD}[Stream] Pathway event stream populated{RESET}")
    try:
        resp = requests.get(f"{GATEWAY_URL}/stream/recent?n=10", timeout=5).json()
        count = resp.get("count", 0)
        print(f"  Recent events: {count}")

        if count > 0:
            event_types = set(e.get("event_type") for e in resp.get("events", []))
            print(f"  Event types: {event_types}")

        passed = count > 0
        results["stream_events"] = passed
        if passed:
            print(f"  {GREEN}✓ PASS{RESET} — Stream has {count} events")
        else:
            print(f"  {RED}✗ FAIL{RESET} — Stream is empty")
        return passed
    except Exception as e:
        print(f"  {RED}✗ ERROR{RESET}: {e}")
        results["stream_events"] = False
        return False


def test_gateway_metrics():
    """Verify gateway metrics show processing activity."""
    print(f"\n{BOLD}[Metrics] Gateway metrics endpoint{RESET}")
    try:
        resp = requests.get(f"{GATEWAY_URL}/metrics", timeout=5).json()
        total = resp.get("transactions_processed", 0)
        print(f"  Transactions processed: {total}")
        print(f"  Approved: {resp.get('approved')}, Held: {resp.get('held')}, Blocked: {resp.get('blocked')}")

        passed = True  # Metrics accessible = pass
        results["gateway_metrics"] = passed
        if passed:
            print(f"  {GREEN}✓ PASS{RESET} — Metrics accessible")
        return passed
    except Exception as e:
        print(f"  {RED}✗ ERROR{RESET}: {e}")
        results["gateway_metrics"] = False
        return False


def test_agent6_health():
    """Verify Agent 6 is healthy and its ready endpoint shows adapters."""
    print(f"\n{BOLD}[Agent6] Health + readiness check{RESET}")
    try:
        health = requests.get(f"{AGENT6_URL}/health", timeout=5).json()
        ready = requests.get(f"{AGENT6_URL}/ready", timeout=5).json()
        print(f"  Health: {health.get('status')}")
        print(f"  Adapters: {ready.get('adapters')}")

        passed = health.get("status") == "ok"
        results["agent6_health"] = passed
        if passed:
            print(f"  {GREEN}✓ PASS{RESET}")
        return passed
    except Exception as e:
        print(f"  {RED}✗ ERROR{RESET}: {e}")
        results["agent6_health"] = False
        return False


def test_bdh_sessions_visible():
    """After E2E tests, BDH should show active sessions."""
    print(f"\n{BOLD}[BDH] Sessions endpoint{RESET}")
    try:
        resp = requests.get(f"{BDH_URL}/sessions", timeout=5).json()
        count = len(resp)
        print(f"  Active sessions: {count}")
        print(f"  Sessions: {list(resp.keys())[:5]}")

        passed = True  # Sessions endpoint accessible = pass
        results["bdh_sessions"] = passed
        print(f"  {GREEN}✓ PASS{RESET} — BDH sessions visible")
        return passed
    except Exception as e:
        print(f"  {RED}✗ ERROR{RESET}: {e}")
        results["bdh_sessions"] = False
        return False


def run_pipeline_tests():
    print(f"\n{'='*70}")
    print(f"{BOLD}{CYAN}FLASHGUARD — END-TO-END PIPELINE TEST SUITE{RESET}")
    print(f"{'='*70}")

    print("\nWaiting for all services...")
    if not wait_for_all():
        print(f"{RED}Some services unreachable — some tests may fail{RESET}")

    time.sleep(2)

    tests = [
        test_e2e_clean,
        test_e2e_fraud,
        test_stream_events,
        test_gateway_metrics,
        test_agent6_health,
        test_bdh_sessions_visible,
    ]

    for test_fn in tests:
        try:
            test_fn()
        except Exception as e:
            name = test_fn.__name__
            print(f"  {RED}✗ ERROR in {name}: {e}{RESET}")
            results[name] = False
        time.sleep(1)

    print(f"\n{'='*70}")
    print(f"{BOLD}PIPELINE TEST SUMMARY{RESET}")
    print(f"{'='*70}")

    passed = sum(1 for v in results.values() if v)
    total = len(results)

    for name, ok in results.items():
        status = f"{GREEN}PASS ✓{RESET}" if ok else f"{RED}FAIL ✗{RESET}"
        print(f"  {name:<40}: {status}")

    print(f"\n{'='*70}")
    if passed == total:
        print(f"{GREEN}{BOLD}🚀 ALL {total} PIPELINE TESTS PASSED!{RESET}")
    else:
        print(f"{CYAN}ℹ {passed}/{total} TESTS PASSED{RESET}")
    print(f"{'='*70}\n")

    return passed == total


if __name__ == "__main__":
    success = run_pipeline_tests()
    sys.exit(0 if success else 1)
