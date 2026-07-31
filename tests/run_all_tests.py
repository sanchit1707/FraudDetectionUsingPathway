#!/usr/bin/env python3
"""
tests/run_all_tests.py
----------------------
Master test runner — runs all FlashGuard test suites in order.

Usage:
    python tests/run_all_tests.py
    # or inside docker:
    docker compose exec test_runner python run_all_tests.py

Environment:
    GATEWAY_URL   (default: http://localhost:8080)
    BDH_URL       (default: http://localhost:8090)
    AGENT6_URL    (default: http://localhost:8000)
    A5_URL        (default: http://localhost:8011)
    A6B_URL       (default: http://localhost:8012)
    A8_URL        (default: http://localhost:8013)
    A10_URL       (default: http://localhost:8014/feedback)
"""

import os
import sys
import time

# Add tests directory to path
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

GREEN = "\033[92m"
RED = "\033[91m"
CYAN = "\033[96m"
YELLOW = "\033[93m"
RESET = "\033[0m"
BOLD = "\033[1m"


def banner(title: str):
    print(f"\n{'█'*70}")
    print(f"█{'':^68}█")
    print(f"█{title:^68}█")
    print(f"█{'':^68}█")
    print(f"{'█'*70}")


def run_suite(module_name: str, run_fn_name: str) -> bool:
    """Import a test module and run its main function."""
    import importlib
    try:
        mod = importlib.import_module(module_name)
        run_fn = getattr(mod, run_fn_name)
        return run_fn()
    except Exception as e:
        print(f"{RED}✗ Suite {module_name} crashed: {e}{RESET}")
        import traceback
        traceback.print_exc()
        return False


if __name__ == "__main__":
    banner("FLASHGUARD COMPLETE TEST SUITE")
    print(f"{'='*70}")
    print(f"  Gateway:    {os.getenv('GATEWAY_URL', 'http://localhost:8080')}")
    print(f"  BDH:        {os.getenv('BDH_URL', 'http://localhost:8090')}")
    print(f"  Agent6:     {os.getenv('AGENT6_URL', 'http://localhost:8000')}")
    print(f"{'='*70}")

    suites = [
        ("test_bdh", "run_all_bdh_tests", "BDH Watchdog (5 Rules)"),
        ("test_signals", "run_all_signal_tests", "Fraud Signals (8 Types)"),
        ("test_pipeline", "run_pipeline_tests", "End-to-End Pipeline"),
        ("test_chaos", "run_chaos_tests", "Chaos Engineering"),
    ]

    suite_results = {}
    total_start = time.time()

    for module, fn, label in suites:
        print(f"\n{CYAN}{'─'*70}{RESET}")
        print(f"{CYAN}Running: {label}{RESET}")
        print(f"{CYAN}{'─'*70}{RESET}")
        passed = run_suite(module, fn)
        suite_results[label] = passed
        time.sleep(2)

    # ── Final Summary ─────────────────────────────────────────────────────────
    elapsed = time.time() - total_start
    banner("MASTER TEST RESULTS")

    all_passed = True
    for label, passed in suite_results.items():
        status = f"{GREEN}PASS ✓{RESET}" if passed else f"{RED}FAIL ✗{RESET}"
        all_passed = all_passed and passed
        print(f"  {label:<35}: {status}")

    print(f"\n  Total time: {elapsed:.1f}s")
    print(f"{'='*70}")

    if all_passed:
        print(f"\n{GREEN}{BOLD}🏆 ALL TEST SUITES PASSED! FlashGuard is fully operational.{RESET}")
    else:
        print(f"\n{YELLOW}⚠ Some suites had failures. See individual output above.{RESET}")
    print()

    sys.exit(0 if all_passed else 1)
