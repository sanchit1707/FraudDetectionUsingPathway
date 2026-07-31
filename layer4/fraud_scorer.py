import pathway as pw
import pickle
import pandas as pd

class LiveFraudScorer:
    """
    A Stateful class to hold our pre-trained ML models in memory 
    and continuously update the online model.
    """
    def __init__(self):
        print("🧠 Loading pre-trained ML models into Agent memory...")
        with open('models/xgb_model.pkl', 'rb') as f:
            self.xgb_model = pickle.load(f)
            
        with open('models/hst_model.pkl', 'rb') as f:
            self.hst_model = pickle.load(f)

    def score_and_learn(self, amount: float, rolling_spend_10m: float, txn_count_10m: float) -> float:
        
        features_dict = {
            'amount': float(amount),
            'rolling_spend_10m': float(rolling_spend_10m),
            'txn_count_10m': float(txn_count_10m)
        }
        
        hst_score = self.hst_model.score_one(features_dict)
        
        xgb_df = pd.DataFrame([features_dict])

        xgb_score = float(self.xgb_model.predict_proba(xgb_df)[0][1])

        final_score = (hst_score + xgb_score) / 2.0

        self.hst_model.learn_one(features_dict)
        
        return final_score


# Initialize the stateful class once so the engine holds it in RAM
scorer_instance = LiveFraudScorer()

# Wrap it in a Pathway UDF so the streaming graph can execute it
@pw.udf
def calculate_ensemble_score(amount: float, rolling_spend_10m: float, txn_count_10m: float) -> float:
    return scorer_instance.score_and_learn(amount, rolling_spend_10m, txn_count_10m)

def apply_fraud_scoring(state_stream: pw.Table) -> pw.Table:

    scored_stream = state_stream.with_columns(
        ml_fraud_score=calculate_ensemble_score(
            pw.this.amount,
            pw.this.rolling_spend_10m,
            pw.this.txn_count_10m
        )
    )
    return scored_stream
