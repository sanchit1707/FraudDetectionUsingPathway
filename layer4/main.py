
"""
main.py
-------

CLI entry point for Agent 6.
"""

from datetime import datetime

from container import container
from models import ExecutionRequest, Policy, Verdict


def prompt_verdict() -> Verdict:
    mapping = {
        "ALLOW": Verdict.ALLOW,
        "REVIEW": Verdict.REVIEW,
        "FLAG": Verdict.FLAG,
        "BLOCK": Verdict.BLOCK,
    }

    while True:
        value = input(
            "Verdict [ALLOW/REVIEW/FLAG/BLOCK]: "
        ).strip().upper()

        if value in mapping:
            return mapping[value]

        print("Invalid verdict.\n")


def main():

    print("=" * 60)
    print("FlashGuard - Agent 6 Execution Orchestrator")
    print("=" * 60)

    txn = input("Transaction ID : ").strip() or "TXN-DEMO-001"
    account = input("Account ID     : ").strip() or "ACC-001"
    customer = input("Customer ID    : ").strip() or "CUS-001"

    verdict = prompt_verdict()

    confidence = float(
        input("Confidence (0-1): ").strip() or "0.95"
    )

    risk = float(
        input("Risk Score (0-1): ").strip() or "0.91"
    )

    tier = int(
        input("Tier (1-4): ").strip() or "1"
    )

    request = ExecutionRequest(
        transaction_id=txn,
        account_id=account,
        customer_id=customer,
        verdict=verdict,
        confidence=confidence,
        risk_score=risk,
        tier=tier,
        policy=Policy(
            id="policy-default",
            version="v1.0",
            name="DefaultPolicy",
        ),
        gateway_trace="gateway-demo",
        timestamp=datetime.utcnow(),
    )

    result = container.executor.execute(request)

    print("\nExecution Result")
    print("-" * 40)
    print("Execution ID :", result.execution_id)
    print("Transaction  :", result.transaction_id)
    print("State        :", result.state.value)
    print("Success      :", result.success)
    print("Latency (ms) :", result.latency_ms)

    print("\nActions")
    print("-" * 40)

    for action in result.action_results:
        print(
            f"{action.action_type.value:<25}"
            f"{action.status.value:<10}"
            f"{action.latency_ms:>8.2f} ms"
        )

    print("\nMetrics Snapshot")
    print("-" * 40)
    print(container.metrics.snapshot())


if __name__ == "__main__":
    main()
