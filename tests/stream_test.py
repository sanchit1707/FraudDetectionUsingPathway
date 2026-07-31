"""
tests/stream_test.py
--------------------
Continuously pumps a realistic mix of transactions through the FlashGuard
pipeline and prints live coloured results to the terminal.

Usage:
    python tests/stream_test.py                  # default: 1 txn every 2s
    python tests/stream_test.py --tps 0.5        # 1 txn every 2s  (slow)
    python tests/stream_test.py --tps 2          # 2 txns per second (fast)
    python tests/stream_test.py --count 20       # stop after 20 transactions
    python tests/stream_test.py --logs           # also tail gateway docker logs
    python tests/stream_test.py --tps 1 --logs  # combined

Press Ctrl+C to stop at any time.
"""

import argparse
import json
import random
import sys
import time
import urllib.error
import urllib.request

# ── Terminal colours (no external deps) ──────────────────────────────────────
RESET  = "\033[0m"
BOLD   = "\033[1m"
DIM    = "\033[2m"
GREEN  = "\033[92m"
RED    = "\033[91m"
YELLOW = "\033[93m"
CYAN   = "\033[96m"
BLUE   = "\033[94m"
MAGENTA= "\033[95m"
WHITE  = "\033[97m"

GATEWAY = "http://localhost:8080"

# ── Transaction templates ─────────────────────────────────────────────────────
# Each entry: (label, weight, payload_factory)
TXN_TEMPLATES = [
    # ── CLEAN transactions (low risk) ──────────────────────────────────────
    ("CLEAN",  30, lambda: {
        "amount":            round(random.uniform(5, 250), 2),
        "rolling_spend_10m": round(random.uniform(10, 400), 2),
        "txn_count_10m":     random.randint(1, 3),
        "bitmask":           0,
        "ml_fraud_score":    round(random.uniform(0.01, 0.15), 3),
        "is_fraudulent":     False,
        "active_threats":    "none",
        "sanctions_hit":     False,
    }),

    # ── SUSPICIOUS / AMBIGUOUS (triggers LLM) ──────────────────────────────
    ("AMBIGUOUS", 25, lambda: {
        "amount":            round(random.uniform(300, 900), 2),
        "rolling_spend_10m": round(random.uniform(500, 2000), 2),
        "txn_count_10m":     random.randint(3, 7),
        "bitmask":           0,
        "ml_fraud_score":    round(random.uniform(0.42, 0.72), 3),
        "is_fraudulent":     False,
        "active_threats":    random.choice(["velocity_spike", "geo_anomaly", "none"]),
        "sanctions_hit":     False,
    }),

    # ── HIGH VELOCITY (near-fraud) ──────────────────────────────────────────
    ("VELOCITY", 15, lambda: {
        "amount":            round(random.uniform(100, 500), 2),
        "rolling_spend_10m": round(random.uniform(2000, 5000), 2),
        "txn_count_10m":     random.randint(8, 20),
        "bitmask":           2,          # velocity flag bit
        "ml_fraud_score":    round(random.uniform(0.55, 0.78), 3),
        "is_fraudulent":     False,
        "active_threats":    "velocity_spike",
        "sanctions_hit":     False,
    }),

    # ── CONFIRMED FRAUD ─────────────────────────────────────────────────────
    ("FRAUD", 15, lambda: {
        "amount":            round(random.uniform(500, 5000), 2),
        "rolling_spend_10m": round(random.uniform(3000, 9000), 2),
        "txn_count_10m":     random.randint(5, 15),
        "bitmask":           7,          # multiple flag bits
        "ml_fraud_score":    round(random.uniform(0.82, 0.99), 3),
        "is_fraudulent":     True,
        "active_threats":    "confirmed_fraud",
        "sanctions_hit":     False,
    }),

    # ── SANCTIONS HIT ───────────────────────────────────────────────────────
    ("SANCTIONS", 5, lambda: {
        "amount":            round(random.uniform(200, 3000), 2),
        "rolling_spend_10m": round(random.uniform(200, 1000), 2),
        "txn_count_10m":     random.randint(1, 4),
        "bitmask":           8,
        "ml_fraud_score":    round(random.uniform(0.3, 0.9), 3),
        "is_fraudulent":     False,
        "active_threats":    "sanctions",
        "sanctions_hit":     True,
    }),

    # ── STRUCTURING (smurfing — just below $10k threshold) ──────────────────
    ("STRUCTURING", 10, lambda: {
        "amount":            round(random.uniform(9100, 9900), 2),
        "rolling_spend_10m": round(random.uniform(9000, 18000), 2),
        "txn_count_10m":     random.randint(2, 5),
        "bitmask":           4,
        "ml_fraud_score":    round(random.uniform(0.45, 0.75), 3),
        "is_fraudulent":     False,
        "active_threats":    "structuring",
        "sanctions_hit":     False,
    }),
]

LABELS   = [t[0] for t in TXN_TEMPLATES]
WEIGHTS  = [t[1] for t in TXN_TEMPLATES]
BUILDERS = [t[2] for t in TXN_TEMPLATES]

# ── Counters ──────────────────────────────────────────────────────────────────
stats = {
    "sent": 0, "approved": 0, "held": 0, "declined": 0,
    "llm_escalated": 0, "errors": 0, "total_ms": 0,
}


def pick_txn():
    """Randomly pick a transaction template respecting weights."""
    idx = random.choices(range(len(TXN_TEMPLATES)), weights=WEIGHTS, k=1)[0]
    label   = LABELS[idx]
    payload = BUILDERS[idx]()
    acct    = f"ACC_{random.randint(1000, 9999)}"
    txn_id  = f"STREAM_{label}_{int(time.time()*1000)}"
    return txn_id, acct, label, payload


def submit(txn_id: str, account_id: str, payload: dict) -> dict:
    body = json.dumps({
        "txn_id":            txn_id,
        "account_id":        account_id,
        **payload,
    }).encode()
    req = urllib.request.Request(
        f"{GATEWAY}/submit",
        data=body,
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    with urllib.request.urlopen(req, timeout=30) as resp:
        return json.loads(resp.read())


def action_colour(action: str) -> str:
    return {
        "approve": GREEN,
        "hold":    YELLOW,
        "decline": RED,
    }.get(action, WHITE)


def print_header():
    print(f"\n{BOLD}{CYAN}{'═'*72}{RESET}")
    print(f"{BOLD}{CYAN}  ⚡ FLASHGUARD — LIVE TRANSACTION STREAM{RESET}")
    print(f"{BOLD}{CYAN}{'═'*72}{RESET}")
    print(f"  {DIM}Gateway : {GATEWAY}{RESET}")
    print(f"  {DIM}Press Ctrl+C to stop{RESET}")
    print(f"{CYAN}{'─'*72}{RESET}\n")


def print_result(n: int, txn_id: str, label: str, payload: dict, result: dict, elapsed: float):
    action  = result.get("final_action", "?")
    score   = result.get("final_score",  0)
    llm     = result.get("llm_escalated", False)
    acol    = action_colour(action)
    llm_tag = f"{MAGENTA}[LLM↑]{RESET}" if llm else f"{DIM}[det]{RESET}"
    label_col = {
        "CLEAN":       GREEN,
        "AMBIGUOUS":   YELLOW,
        "VELOCITY":    YELLOW,
        "FRAUD":       RED,
        "SANCTIONS":   RED,
        "STRUCTURING": MAGENTA,
    }.get(label, WHITE)

    print(
        f"  {DIM}#{n:<4}{RESET}"
        f"{label_col}{label:<12}{RESET}"
        f"  {CYAN}${payload['amount']:>8.2f}{RESET}"
        f"  score={BOLD}{score:.3f}{RESET}"
        f"  {acol}{BOLD}{action.upper():<8}{RESET}"
        f"  {llm_tag}"
        f"  {DIM}{elapsed:>5.0f}ms{RESET}"
    )
    if llm:
        reasoning = result.get("llm_reasoning", "")
        if reasoning:
            short = reasoning[:90] + ("…" if len(reasoning) > 90 else "")
            print(f"         {DIM}└─ LLM: {short}{RESET}")


def print_summary():
    sent = stats["sent"] or 1
    print(f"\n{CYAN}{'─'*72}{RESET}")
    print(f"{BOLD}  STREAM SUMMARY{RESET}")
    print(f"  Transactions : {stats['sent']}")
    print(f"  {GREEN}Approved     : {stats['approved']:>4}  ({100*stats['approved']//sent:>2}%){RESET}")
    print(f"  {YELLOW}Held         : {stats['held']:>4}  ({100*stats['held']//sent:>2}%){RESET}")
    print(f"  {RED}Declined     : {stats['declined']:>4}  ({100*stats['declined']//sent:>2}%){RESET}")
    print(f"  {MAGENTA}LLM Escalated: {stats['llm_escalated']:>4}  ({100*stats['llm_escalated']//sent:>2}%){RESET}")
    print(f"  {DIM}Errors       : {stats['errors']}{RESET}")
    avg = stats["total_ms"] // sent
    print(f"  Avg latency  : {avg}ms")
    print(f"{CYAN}{'═'*72}{RESET}\n")


def wait_for_gateway(timeout: int = 30):
    print(f"  {DIM}Waiting for Gateway", end="", flush=True)
    deadline = time.time() + timeout
    while time.time() < deadline:
        try:
            urllib.request.urlopen(f"{GATEWAY}/health", timeout=2)
            print(f"  {GREEN}✓{RESET}")
            return True
        except Exception:
            print(".", end="", flush=True)
            time.sleep(1)
    print(f"  {RED}✗ Gateway not reachable{RESET}")
    return False


def main():
    parser = argparse.ArgumentParser(description="FlashGuard live stream test")
    parser.add_argument("--tps",   type=float, default=0.5,
                        help="Transactions per second (default 0.5 = 1 every 2s)")
    parser.add_argument("--count", type=int,   default=0,
                        help="Stop after N transactions (0 = infinite)")
    parser.add_argument("--logs",  action="store_true",
                        help="Also tail gateway Docker logs in background")
    args = parser.parse_args()

    interval = 1.0 / args.tps

    print_header()
    if not wait_for_gateway():
        sys.exit(1)

    # Optionally tail docker logs in a background thread
    if args.logs:
        import subprocess, threading
        def _tail():
            proc = subprocess.Popen(
                ["docker", "logs", "flashguard_gateway", "-f", "--tail", "0"],
                stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
                text=True, encoding="utf-8", errors="replace",
            )
            for line in proc.stdout:
                line = line.rstrip()
                # Only print backend log lines, not HTTP access lines
                if "[Gateway]" in line:
                    print(f"  {DIM}│ {line}{RESET}")
        t = threading.Thread(target=_tail, daemon=True)
        t.start()
        print(f"  {DIM}Gateway logs: tailing in background{RESET}\n")

    print(f"  {DIM}Rate: {args.tps} txn/s  |  interval: {interval:.1f}s{RESET}")
    if args.count:
        print(f"  {DIM}Will send {args.count} transactions then stop{RESET}")
    print(f"\n  {'#':<5} {'TYPE':<12} {'AMOUNT':>9}  {'SCORE':<10} {'ACTION':<8}  {'SRC':<7}  {'LAT':>6}")
    print(f"  {'─'*65}")

    try:
        n = 0
        while True:
            n += 1
            if args.count and n > args.count:
                break

            txn_id, acct, label, payload = pick_txn()
            t0 = time.monotonic()
            try:
                result  = submit(txn_id, acct, payload)
                elapsed = (time.monotonic() - t0) * 1000
                action  = result.get("final_action", "unknown")

                stats["sent"]    += 1
                stats["total_ms"] += int(elapsed)
                if action == "approve":  stats["approved"] += 1
                elif action == "hold":   stats["held"]     += 1
                elif action == "decline":stats["declined"] += 1
                if result.get("llm_escalated"): stats["llm_escalated"] += 1

                print_result(n, txn_id, label, payload, result, elapsed)

            except urllib.error.URLError as exc:
                elapsed = (time.monotonic() - t0) * 1000
                stats["errors"] += 1
                print(f"  {DIM}#{n:<4}{RESET}{RED}ERROR{RESET}  {exc.reason}  {DIM}{elapsed:.0f}ms{RESET}")
            except Exception as exc:
                stats["errors"] += 1
                print(f"  {DIM}#{n:<4}{RESET}{RED}ERROR{RESET}  {exc}")

            # sleep for the remainder of the interval
            spent = time.monotonic() - t0
            sleep_for = max(0, interval - spent)
            if sleep_for > 0:
                time.sleep(sleep_for)

    except KeyboardInterrupt:
        pass

    print_summary()


if __name__ == "__main__":
    main()
