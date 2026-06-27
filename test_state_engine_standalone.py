import pathway as pw
import logging

from layer1.prefetcher import build_enriched_stream
from layer2.state_window_engine import build_state_window_stream
from layer3.decision_engine import evaluate_fraud_rules 
from layer4.fraud_scorer import apply_fraud_scoring

def test_step_by_step_pipeline():
    logging.getLogger("pathway").setLevel(logging.WARNING)
    print("🛰️  Compiling Pipeline Graph Step-by-Step...")
    
    # L1: Ingestion
    enriched = build_enriched_stream(mode="demo")
    
    # L2: Stateful Aggregation
    state_analytics = build_state_window_stream(enriched)
    
    # L3: Deterministic Rules 
    alerts_stream = evaluate_fraud_rules(windowed_analytics=state_analytics)
    
    # L4: Machine Learning Ensemble
    final_scored_stream = apply_fraud_scoring(state_stream=alerts_stream)
    
    print("🚀 Booting engine core loop. Streaming transaction evaluations...")
    print("=" * 100)
    
    pw.debug.compute_and_print(final_scored_stream)
    pw.run()

if __name__ == "__main__":
    test_step_by_step_pipeline()