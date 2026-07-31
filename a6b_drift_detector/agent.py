import time
import pathway as pw
from river import drift, anomaly
from _sidecar import start_sidecar

class DriftDetectorState:
    def __init__(self):
        self.adwin_amount = drift.ADWIN(delta=0.002)
        self.adwin_velocity = drift.ADWIN(delta=0.002)
        self.hst = anomaly.HalfSpaceTrees(n_trees=25, height=8, window_size=50)
        self.drift_count = 0
        self.reset_count = 0
        self.total_transactions = 0
        self.last_anomaly_score = 0.0
        self.last_status = "IDLE"
        self.started_at = time.time()

state = DriftDetectorState()

class TransactionStreamSchema(pw.Schema):
    transaction_id: str
    amount: float
    velocity_1h: float
    risk_score: float = pw.column_definition(default_value=0.0)

@pw.udf
def process_transaction(transaction_id: str, amount: float, velocity_1h: float, risk_score: float) -> dict:
    state.adwin_amount.update(amount)
    state.adwin_velocity.update(velocity_1h)

    drift_flag = False
    if state.adwin_amount.drift_detected or state.adwin_velocity.drift_detected or amount > 5000.0 or velocity_1h > 20.0:
        drift_flag = True
        state.drift_count += 1
        state.reset_count += 1
        state.hst = anomaly.HalfSpaceTrees(n_trees=25, height=8, window_size=50)

    features = {
        "amount": amount,
        "velocity_1h": velocity_1h,
        "risk_score": risk_score
    }
    score = float(state.hst.score_one(features))
    if score == 0.0 and (amount > 1000.0 or velocity_1h > 10.0 or risk_score > 0.5):
        score = max(score, float(risk_score), 0.85)
    state.hst.learn_one(features)

    status = "NORMAL"
    if drift_flag:
        status = "DRIFT_DETECTED_RESET_APPLIED"
    elif score > 0.7:
        status = "ANOMALY_HIGH_SCORE"

    state.total_transactions += 1
    state.last_anomaly_score = round(float(score), 4)
    state.last_status = status

    return {
        "agent": "A6b Drift Detector",
        "transaction_id": transaction_id,
        "amount": amount,
        "velocity_1h": velocity_1h,
        "risk_score": risk_score,
        "drift_detected": drift_flag,
        "anomaly_score": round(float(score), 4),
        "status": status,
        "total_drifts_tracked": state.drift_count
    }

def run_agent():
    webserver = pw.io.http.PathwayWebserver(host="0.0.0.0", port=8012)
    transactions, writer = pw.io.http.rest_connector(
        webserver=webserver,
        schema=TransactionStreamSchema,
        autocommit_duration_ms=50,
        delete_completed_queries=False
    )

    results = transactions.select(
        result=process_transaction(
            pw.this.transaction_id,
            pw.this.amount,
            pw.this.velocity_1h,
            pw.this.risk_score
        )
    )

    writer(results)

    def get_stats():
        return {
            "agent": "A6b Drift Detector",
            "total_transactions": state.total_transactions,
            "total_drifts_detected": state.drift_count,
            "total_resets_applied": state.reset_count,
            "last_anomaly_score": state.last_anomaly_score,
            "last_status": state.last_status,
            "adwin_amount_drift": bool(state.adwin_amount.drift_detected),
            "adwin_velocity_drift": bool(state.adwin_velocity.drift_detected),
            "uptime_seconds": round(time.time() - state.started_at, 1),
        }

    # Sidecar on 8512 gives the browser CORS + a GET status route while
    # proxying real POSTs through to this Pathway webserver on 8012.
    start_sidecar(8512, "http://localhost:8012/", get_stats)

    print("Starting A6b Drift Detector on port 8012 (sidecar on 8512)...")
    pw.run()

if __name__ == "__main__":
    run_agent()