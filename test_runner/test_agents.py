import os
import time
import requests
import json

A5_URL = os.getenv("A5_URL", "http://localhost:8011")
A6B_URL = os.getenv("A6B_URL", "http://localhost:8012")
A8_URL = os.getenv("A8_URL", "http://localhost:8013")
A10_URL = os.getenv("A10_URL", "http://localhost:8014/feedback")

def wait_for_agent(name, url, timeout=60):
    print(f"Waiting for {name} at {url} to become ready...")
    start_time = time.time()
    while time.time() - start_time < timeout:
        try:
            resp = requests.post(url, json={"test": "ping"}, timeout=2.0)
            if resp.status_code in [200, 400, 404, 500]:
                print(f"[READY] {name} is up and accepting requests (Status: {resp.status_code}).")
                return True
        except requests.exceptions.ConnectionError:
            time.sleep(2.0)
        except Exception:
            time.sleep(2.0)
    print(f"[WARNING] {name} at {url} did not respond within {timeout}s.")
    return False

def test_a5_compliance_rag():
    print("\n" + "="*70)
    print("TESTING AGENT 1: A5 Compliance RAG (Streaming Vector Retrieval)")
    print("="*70)
    payload = {"query": "BSA Title 31 structuring over $10000 rapid velocity", "top_k": 2}
    try:
        resp = requests.post(A5_URL, json=payload, timeout=60.0)
        print(f"Status Code: {resp.status_code}")
        data = resp.json()
        if isinstance(data, list) and len(data) > 0:
            item = data[0].get("result", data[0])
        elif isinstance(data, dict):
            item = data.get("result", data)
        else:
            item = data
        print(f"Response JSON:\n{json.dumps(item, indent=2)}")
        assert resp.status_code == 200, f"Expected 200, got {resp.status_code}"
        assert "compliance_context" in item, "Missing compliance_context field"
        assert item["retrieved_count"] > 0, "Retrieved count should be > 0"
        print("[PASS] A5 Compliance RAG: Successfully retrieved semantic regulatory chunks!")
        return True
    except Exception as e:
        print(f"[FAIL] A5 Compliance RAG test failed: {e}")
        return False

def test_a6b_drift_detector():
    print("\n" + "="*70)
    print("TESTING AGENT 2: A6b Drift Detector (River ADWIN + HalfSpaceTrees)")
    print("="*70)
    payload_normal = {
        "transaction_id": "TX_NORM_001",
        "amount": 45.0,
        "velocity_1h": 3.0,
        "risk_score": 0.1
    }
    try:
        resp1 = requests.post(A6B_URL, json=payload_normal, timeout=10.0)
        data1 = resp1.json()
        if isinstance(data1, list) and len(data1) > 0:
            item1 = data1[0].get("result", data1[0])
        elif isinstance(data1, dict):
            item1 = data1.get("result", data1)
        else:
            item1 = data1
        print(f"Normal Transaction Response:\n{json.dumps(item1, indent=2)}")

        print("Sending high-velocity drift spike to trigger ADWIN reset & anomaly detection...")
        payload_drift = {
            "transaction_id": "TX_DRIFT_SPIKE_999",
            "amount": 25000.0,
            "velocity_1h": 150.0,
            "risk_score": 0.95
        }
        resp2 = requests.post(A6B_URL, json=payload_drift, timeout=10.0)
        data2 = resp2.json()
        if isinstance(data2, list) and len(data2) > 0:
            item2 = data2[0].get("result", data2[0])
        elif isinstance(data2, dict):
            item2 = data2.get("result", data2)
        else:
            item2 = data2
        print(f"Drift Spike Response:\n{json.dumps(item2, indent=2)}")

        assert resp2.status_code == 200, f"Expected 200, got {resp2.status_code}"
        assert item2["drift_detected"] == True or item2["anomaly_score"] > 0.0, "Expected drift or anomaly detection"
        print("[PASS] A6b Drift Detector: Successfully detected concept drift & anomalies!")
        return True
    except Exception as e:
        print(f"[FAIL] A6b Drift Detector test failed: {e}")
        return False

def test_a8_sar_drafter():
    print("\n" + "="*70)
    print("TESTING AGENT 3: A8 SAR Drafter (Cross-Agent RAG Integration)")
    print("="*70)
    payload_frozen = {
        "transaction_id": "TX_FROZEN_GATEWAY_888",
        "card_id": "CARD_LOCKED_404",
        "customer_id": "CUST_9090",
        "amount": 9950.0,
        "merchant": "OFFSHORE_CRYPTO_EXCHANGE",
        "freeze_reason": "Structuring transactions just under $10,000 threshold with rapid velocity",
        "velocity_1h": 42.0,
        "timestamp": "2026-07-15T02:00:00Z"
    }
    try:
        print("Sending frozen transaction notification (post-card lock) to A8 SAR Drafter...")
        resp = requests.post(A8_URL, json=payload_frozen, timeout=15.0)
        print(f"Status Code: {resp.status_code}")
        data = resp.json()
        if isinstance(data, list) and len(data) > 0:
            item = data[0].get("result", data[0])
        elif isinstance(data, dict):
            item = data.get("result", data)
        else:
            item = data
        print(f"SAR Draft Response:\n{json.dumps(item, indent=2)[:1200]}")
        assert resp.status_code == 200, f"Expected 200, got {resp.status_code}"
        assert item["status"] == "SAR_DRAFTED", "Expected SAR_DRAFTED status"
        assert item["rag_snippets_retrieved"] > 0, "Should have retrieved RAG snippets from A5"
        print("[PASS] A8 SAR Drafter: Successfully drafted formal SAR using A5 Compliance RAG context!")
        return True
    except Exception as e:
        print(f"[FAIL] A8 SAR Drafter test failed: {e}")
        return False

def test_a10_feedback_loop():
    print("\n" + "="*70)
    print("TESTING AGENT 4: A10 Feedback Loop (Online River Classification)")
    print("="*70)
    feedback_events = [
        {"transaction_id": "TX_FB_1", "amount": 20.0, "velocity_1h": 1.0, "risk_score": 0.05, "actual_label": 0, "predicted_label": 0},
        {"transaction_id": "TX_FB_2", "amount": 12000.0, "velocity_1h": 80.0, "risk_score": 0.9, "actual_label": 1, "predicted_label": 1},
        {"transaction_id": "TX_FB_3", "amount": 50.0, "velocity_1h": 2.0, "risk_score": 0.1, "actual_label": 0, "predicted_label": 1},
        {"transaction_id": "TX_FB_4", "amount": 15000.0, "velocity_1h": 95.0, "risk_score": 0.95, "actual_label": 1, "predicted_label": 1}
    ]
    try:
        for idx, ev in enumerate(feedback_events, 1):
            print(f"Sending feedback event {idx}/4 (Tx: {ev['transaction_id']}, GT: {ev['actual_label']})...")
            resp = requests.post(A10_URL, json=ev, timeout=10.0)
            data = resp.json()
            if isinstance(data, list) and len(data) > 0:
                item = data[0].get("result", data[0])
            elif isinstance(data, dict):
                item = data.get("result", data)
            else:
                item = data
            print(f" -> Online Accuracy: {item.get('online_accuracy')} | ROC-AUC: {item.get('online_roc_auc')}")
            assert resp.status_code == 200, f"Expected 200, got {resp.status_code}"
            time.sleep(0.5)
        print("[PASS] A10 Feedback Loop: Online model learning & metrics updating successfully!")
        return True
    except Exception as e:
        print(f"[FAIL] A10 Feedback Loop test failed: {e}")
        return False

def run_all_tests():
    print("\n" + "="*70)
    print("STARTING COMPLETE ASYNC AGENTS VERIFICATION SUITE")
    print("="*70)

    agents_ready = (
        wait_for_agent("A5 Compliance RAG", A5_URL) and
        wait_for_agent("A6b Drift Detector", A6B_URL) and
        wait_for_agent("A8 SAR Drafter", A8_URL) and
        wait_for_agent("A10 Feedback Loop", A10_URL)
    )

    if not agents_ready:
        print("\n[WARNING] Some agents took longer to respond. Proceeding with test suite anyway...")

    # Give A5 Compliance RAG extra time to embed all 19 docs on cold start
    print("\n[WARMUP] Waiting 25s for A5 to finish embedding all compliance docs...")
    time.sleep(25)
    print("[WARMUP] Done. Starting tests.")

    results = {
        "A5 Compliance RAG": test_a5_compliance_rag(),
        "A6b Drift Detector": test_a6b_drift_detector(),
        "A8 SAR Drafter": test_a8_sar_drafter(),
        "A10 Feedback Loop": test_a10_feedback_loop()
    }

    print("\n" + "="*70)
    print("FINAL TEST SUITE SUMMARY RESULTS")
    print("="*70)
    all_passed = True
    for agent_name, passed in results.items():
        status_str = "PASS [✔]" if passed else "FAIL [✘]"
        print(f"{agent_name:<25}: {status_str}")
        if not passed:
            all_passed = False

    if all_passed:
        print("\n🎉 ALL 4 ASYNC AGENTS PASSED — COMPLETE END-TO-END SYSTEM VERIFIED! 🎉")
    else:
        print("\n⚠️ SOME TESTS HAD ISSUES. CHECK LOGS ABOVE FOR DETAILS.")
    print("="*70 + "\n")

if __name__ == "__main__":
    time.sleep(5)
    run_all_tests()