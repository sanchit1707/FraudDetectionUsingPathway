import time
import pathway as pw
from river import linear_model, preprocessing, metrics
from _sidecar import start_sidecar

class FeedbackLoopState:
    def __init__(self):
        self.model = preprocessing.StandardScaler() | linear_model.LogisticRegression()
        self.metric_accuracy = metrics.Accuracy()
        self.metric_rocauc = metrics.ROCAUC()
        self.total_feedback_events = 0
        self.last_transaction_id = None
        self.last_predicted_label = None
        self.last_actual_label = None
        self.started_at = time.time()

state = FeedbackLoopState()

class FeedbackSchema(pw.Schema):
    transaction_id: str
    amount: float
    velocity_1h: float
    risk_score: float = pw.column_definition(default_value=0.0)
    actual_label: int = pw.column_definition(default_value=0)
    predicted_label: int = pw.column_definition(default_value=0)

@pw.udf
def process_feedback(transaction_id: str, amount: float, velocity_1h: float, risk_score: float, actual_label: int, predicted_label: int) -> dict:
    features = {
        "amount": amount,
        "velocity_1h": velocity_1h,
        "risk_score": risk_score
    }

    try:
        y_pred_proba = state.model.predict_proba_one(features)
        pred_label_online = 1 if y_pred_proba.get(True, 0.0) > 0.5 else 0
        state.metric_accuracy.update(actual_label, pred_label_online)
        state.metric_rocauc.update(actual_label, y_pred_proba.get(True, 0.0))
    except Exception:
        pred_label_online = predicted_label

    state.model.learn_one(features, bool(actual_label))
    state.total_feedback_events += 1
    state.last_transaction_id = transaction_id
    state.last_predicted_label = pred_label_online
    state.last_actual_label = actual_label

    return {
        "agent": "A10 Feedback Loop",
        "transaction_id": transaction_id,
        "actual_label": actual_label,
        "predicted_label_online": pred_label_online,
        "model_updated": True,
        "online_accuracy": round(float(state.metric_accuracy.get()), 4),
        "online_roc_auc": round(float(state.metric_rocauc.get()), 4) if state.metric_rocauc.get() is not None else 0.5,
        "total_events_processed": state.total_feedback_events,
        "status": "ONLINE_MODEL_UPDATED"
    }

def run_agent():
    webserver = pw.io.http.PathwayWebserver(host="0.0.0.0", port=8014)
    feedback_stream, writer = pw.io.http.rest_connector(
        webserver=webserver,
        route="/feedback",
        schema=FeedbackSchema,
        autocommit_duration_ms=50,
        delete_completed_queries=False
    )

    results = feedback_stream.select(
        result=process_feedback(
            pw.this.transaction_id,
            pw.this.amount,
            pw.this.velocity_1h,
            pw.this.risk_score,
            pw.this.actual_label,
            pw.this.predicted_label
        )
    )

    writer(results)

    def get_stats():
        return {
            "agent": "A10 Feedback Loop",
            "total_events_processed": state.total_feedback_events,
            "online_accuracy": round(float(state.metric_accuracy.get()), 4),
            "online_roc_auc": (
                round(float(state.metric_rocauc.get()), 4)
                if state.metric_rocauc.get() is not None else 0.5
            ),
            "last_transaction_id": state.last_transaction_id,
            "last_predicted_label": state.last_predicted_label,
            "last_actual_label": state.last_actual_label,
            "model": "river StandardScaler | LogisticRegression (online)",
            "uptime_seconds": round(time.time() - state.started_at, 1),
        }

    # Sidecar on 8515 gives the browser CORS + a GET status route while
    # proxying real /feedback POSTs through to this Pathway webserver on 8014.
    start_sidecar(8515, "http://localhost:8014/feedback", get_stats)

    print("Starting A10 Feedback Loop on port 8014 (/feedback), sidecar on 8515...")
    pw.run()

if __name__ == "__main__":
    run_agent()