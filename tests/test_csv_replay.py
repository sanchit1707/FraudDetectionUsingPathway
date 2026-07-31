"""
tests/test_csv_replay.py
--------------------------
Verifies the ACTUAL CSV replay pipeline is running — not the /submit
manual-testing path every other test in this suite uses.

Why this test exists (found while investigating a real symptom):
gateway/main.py's own comment on /submit says "manual transaction
submission (for testing)". stream_test.py, test_pipeline.py,
test_signals.py, test_llm_groq.py, and test_chaos.py all submit
synthetic feature dicts to /submit directly. None of them reads
data/ieee_transactions.csv or exercises pw.demo.replay_csv() inside
run_pathway_pipeline() (gateway/main.py, started as a background
thread in lifespan()). test_pipeline.py's "stream_events" check only
confirms pathway:events has entries from emit_node_enter/emit_node_exit
calls fired DURING /submit processing — those entries exist regardless
of whether the CSV replay thread is alive at all.

This means every existing green checkmark in tests/run_all_tests.py
can pass even if the CSV replay silently died on startup (e.g. from
an exception in run_pathway_pipeline() being swallowed by its own
try/except at the bottom of the function). This test specifically
targets that blind spot.

What this test checks:
  1. The gateway process actually has a live pathway_thread
     (indirect check — via a counter that only the CSV path increments)
  2. Rows from ieee_transactions.csv are visibly flowing into the
     pipeline within a reasonable window after gateway startup
  3. The replay eventually produces DIFFERENT txn_ids over time
     (proves it's genuinely streaming, not stuck replaying row 0
     forever due to a Config.REPLAY_RATE misconfiguration)

IMPORTANT — read this before trusting a PASS:
gateway/main.py currently exposes no endpoint that directly reports
"CSV rows ingested so far" or "current row offset in ieee_transactions
.csv". This test therefore uses /metrics and /stream/recent as
INDIRECT proxies and is only as good as what those endpoints expose.
If /metrics's transactions_processed only increments on /submit calls
(not on CSV-driven rows), this test will show a false negative even
if the CSV replay IS working — check metrics.py / gateway/main.py's
/metrics implementation to confirm what it actually counts before
trusting a FAIL here. This caveat is deliberately left visible rather
than silently assumed away.

Run:
    python tests/test_csv_replay.py
    # or inside docker, from a fresh `docker compose up`:
    docker compose exec test_runner python /app/test_csv_replay.py
"""
import json
import os
import sys
import time
import requests

GATEWAY_URL = os.getenv("GATEWAY_URL", "http://localhost:8080")

GREEN = "\033[92m"
RED = "\033[91m"
YELLOW = "\033[93m"
CYAN = "\033[96m"
RESET = "\033[0m"
BOLD = "\033[1m"

results = {}


def wait_for_gateway(timeout: int = 60) -> bool:
    print("  Waiting for Gateway...", end=" ", flush=True)
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


def get_baseline_snapshot() -> dict:
    """
    Takes an initial reading right after startup — this is the
    'before' state we compare against after waiting, to see if
    anything moved on its own without us calling /submit.
    """
    snapshot = {"metrics": None, "stream_txn_ids": set(), "error": None}
    try:
        m = requests.get(f"{GATEWAY_URL}/metrics", timeout=5).json()
        snapshot["metrics"] = m
    except Exception as e:
        snapshot["error"] = f"metrics unreachable: {e}"

    try:
        s = requests.get(f"{GATEWAY_URL}/stream/recent?n=50", timeout=5).json()
        snapshot["stream_txn_ids"] = {
            e.get("txn_id") for e in s.get("events", []) if e.get("txn_id")
        }
    except Exception as e:
        if snapshot["error"] is None:
            snapshot["error"] = f"stream/recent unreachable: {e}"

    return snapshot


def test_csv_replay_produces_new_events_without_manual_submit():
    """
    THE CORE TEST. Takes a snapshot, waits WITHOUT calling /submit at
    all, takes a second snapshot, and checks whether NEW txn_ids
    appeared — which can only happen if something other than a human
    calling /submit is pushing rows through the pipeline. That
    'something' should be pw.demo.replay_csv() driven by
    Config.REPLAY_RATE.
    """
    print(f"\n{BOLD}[CSV-1] CSV replay produces events with zero manual submissions{RESET}")

    baseline = get_baseline_snapshot()
    if baseline["error"]:
        print(f"  {RED}✗ FAIL{RESET} — could not read baseline: {baseline['error']}")
        results["csv_replay_active"] = False
        return False

    baseline_ids = baseline["stream_txn_ids"]
    print(f"  Baseline: {len(baseline_ids)} distinct txn_ids in recent stream")

    # Wait a window proportional to Config.REPLAY_RATE. Default REPLAY_RATE
    # in config.py is 10000 (rows/sec in Pathway's replay_csv semantics is
    # NOT wall-clock seconds — it's an input_rate parameter). Give this a
    # generous 20s real-world window; if the replay is running at all, new
    # rows should appear well within that.
    wait_seconds = 20
    print(f"  Waiting {wait_seconds}s with ZERO /submit calls...")
    time.sleep(wait_seconds)

    after = get_baseline_snapshot()
    if after["error"]:
        print(f"  {RED}✗ FAIL{RESET} — could not read after-wait snapshot: {after['error']}")
        results["csv_replay_active"] = False
        return False

    after_ids = after["stream_txn_ids"]
    new_ids = after_ids - baseline_ids

    print(f"  After wait: {len(after_ids)} distinct txn_ids, "
          f"{len(new_ids)} NEW since baseline")

    if new_ids:
        sample = list(new_ids)[:5]
        print(f"  Sample new txn_ids: {sample}")

    passed = len(new_ids) > 0
    results["csv_replay_active"] = passed

    if passed:
        print(f"  {GREEN}✓ PASS{RESET} — pipeline is producing events without manual /submit calls")
    else:
        print(f"  {RED}✗ FAIL{RESET} — no new events appeared in {wait_seconds}s with no /submit calls.")
        print(f"  {YELLOW}This is consistent with the CSV replay thread having died or")
        print(f"  never started. Check gateway container logs for a swallowed")
        print(f"  exception inside run_pathway_pipeline() (gateway/main.py).{RESET}")

    return passed


def test_csv_rows_are_actually_from_ieee_dataset():
    """
    Weaker secondary signal: checks whether any recent stream event's
    account_id/txn_id pattern looks CSV-sourced rather than
    /submit-sourced. Your /submit test payloads consistently use
    account_id values like 'ACC_E2E_001' or 'ACC_1234' (see
    test_pipeline.py, stream_test.py, test_signals.py) — real
    ieee_transactions.csv rows will have a different AccountID format
    from that dataset's own schema. This is a heuristic, not a proof —
    treat a FAIL here as a signal to investigate, not a hard verdict.
    """
    print(f"\n{BOLD}[CSV-2] Recent events include non-synthetic-test account IDs{RESET}")
    try:
        s = requests.get(f"{GATEWAY_URL}/stream/recent?n=50", timeout=5).json()
        events = s.get("events", [])
    except Exception as e:
        print(f"  {RED}✗ ERROR{RESET}: {e}")
        results["csv_rows_present"] = False
        return False

    KNOWN_TEST_PREFIXES = ("ACC_E2E_", "ACC_STREAM_", "ACC_1", "ACC_2",
                            "ACC_3", "ACC_4", "ACC_5", "ACC_6", "ACC_7",
                            "ACC_8", "ACC_9")
    account_ids = [e.get("account_id", "") for e in events if e.get("account_id")]

    non_test_ids = [
        a for a in account_ids
        if a and not any(a.startswith(p) for p in KNOWN_TEST_PREFIXES)
    ]

    print(f"  Total account_ids seen: {len(account_ids)}")
    print(f"  Account IDs NOT matching known synthetic-test prefixes: {len(non_test_ids)}")
    if non_test_ids:
        print(f"  Sample: {non_test_ids[:5]}")

    passed = len(non_test_ids) > 0
    results["csv_rows_present"] = passed

    if passed:
        print(f"  {GREEN}✓ PASS{RESET} (heuristic) — likely seeing CSV-sourced accounts")
    else:
        print(f"  {YELLOW}⚠ INCONCLUSIVE{RESET} — all visible accounts match known test "
              f"prefixes. This does NOT prove the CSV isn't streaming (window may just "
              f"be too small), but combine with CSV-1's result for the real verdict.")

    return passed


def run_csv_replay_tests():
    print(f"\n{'='*70}")
    print(f"{BOLD}{CYAN}FLASHGUARD — CSV REPLAY VERIFICATION{RESET}")
    print(f"{'='*70}")
    print(f"  This test suite specifically targets a blind spot in the existing")
    print(f"  suite: every other test drives the pipeline via manual POST /submit")
    print(f"  calls, so none of them can detect a silently-dead CSV replay thread.")

    if not wait_for_gateway():
        print(f"{RED}Gateway unreachable — cannot proceed{RESET}")
        return False

    time.sleep(2)

    test_csv_replay_produces_new_events_without_manual_submit()
    test_csv_rows_are_actually_from_ieee_dataset()

    print(f"\n{'='*70}")
    print(f"{BOLD}CSV REPLAY TEST SUMMARY{RESET}")
    print(f"{'='*70}")

    passed = sum(1 for v in results.values() if v)
    total = len(results)
    for name, ok in results.items():
        status = f"{GREEN}PASS ✓{RESET}" if ok else f"{RED}FAIL ✗{RESET}"
        print(f"  {name:<40}: {status}")

    print(f"\n{'='*70}")
    if results.get("csv_replay_active") is False:
        print(f"{RED}{BOLD}⚠ CSV REPLAY APPEARS INACTIVE — check gateway container logs{RESET}")
        print(f"  Suggested next step: docker compose logs gateway | grep -i pathway")
    elif passed == total:
        print(f"{GREEN}{BOLD}✓ CSV replay pipeline confirmed active{RESET}")
    else:
        print(f"{CYAN}ℹ {passed}/{total} checks passed — see individual results above{RESET}")
    print(f"{'='*70}\n")

    # csv_replay_active is the load-bearing result; the heuristic test is
    # supplementary and shouldn't fail the whole suite on its own.
    return results.get("csv_replay_active", False)


if __name__ == "__main__":
    success = run_csv_replay_tests()
    sys.exit(0 if success else 1)
