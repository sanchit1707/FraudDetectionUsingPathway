import pandas as pd
import xgboost as xgb
from river import anomaly, compose, preprocessing
import pickle
import os
import time

def prepare_historical_data(csv_path: str) -> pd.DataFrame:
    """
    Simulates Layer 3 State Engine using Pandas to generate historical 
    rolling windows for ML training.
    """
    print(f"📥 Loading historical data from {csv_path}...")
    df = pd.read_csv(csv_path)
    
    df = df.rename(columns={'TransactionAmount': 'amount', 'IsFraud': 'label'})
    df['TransactionDate'] = pd.to_datetime(df['TransactionDate'])
    
    print("🧮 Calculating 10-minute rolling windows for training features...")

    df = df.sort_values(by=['AccountID', 'TransactionDate'])

    df_indexed = df.set_index('TransactionDate')
    
    grouped_rolling = df_indexed.groupby('AccountID')['amount'].rolling('10min')
    
    rolling_sum = grouped_rolling.sum().reset_index(name='rolling_spend_10m')
    rolling_count = grouped_rolling.count().reset_index(name='txn_count_10m')
    
    rolling_stats = pd.merge(rolling_sum, rolling_count, on=['AccountID', 'TransactionDate'])
    
    df = df.merge(rolling_stats, on=['AccountID', 'TransactionDate'])
    return df[['amount', 'rolling_spend_10m', 'txn_count_10m', 'label']].dropna()

def train_and_save_models():
    # 1. Prepare Data
    df = prepare_historical_data('data/fraud_transactions.csv')
    
    features = ['amount', 'rolling_spend_10m', 'txn_count_10m']
    X = df[features]
    y = df['label']
    
    print(f"📊 Training on {len(df)} historical transactions...")

    # 2. Train XGBoost (The Batch Heavyweight)

    print("🌳 Training XGBoost Model...")
    start_time = time.time()
    
    xgb_model = xgb.XGBClassifier(
        n_estimators=100, 
        max_depth=4, 
        learning_rate=0.1, 
        random_state=42,
        eval_metric='logloss'
    )
    xgb_model.fit(X, y)
    
    print(f"✅ XGBoost trained in {time.time() - start_time:.2f} seconds.")

    # 3. Train River HST (The Online Adapter)
    print("🌊 Warm-starting River HalfSpaceTrees...")
    start_time = time.time()
    
    hst_model = compose.Pipeline(
        preprocessing.StandardScaler(),
        anomaly.HalfSpaceTrees(
            n_trees=25,
            height=15,
            window_size=250,
            seed=42
        )
    )

    for x_dict in X.to_dict(orient='records'):
        hst_model.learn_one(x_dict)
        
    print(f"✅ River HST warm-started in {time.time() - start_time:.2f} seconds.")

    # 4. Save Models to Disk
    print("💾 Saving models to ./models directory...")
    os.makedirs('models', exist_ok=True)
    
    with open('models/xgb_model.pkl', 'wb') as f:
        pickle.dump(xgb_model, f)
        
    with open('models/hst_model.pkl', 'wb') as f:
        pickle.dump(hst_model, f)
        
    print("🚀 Phase 1 Complete! Models are ready for the live pipeline.")

if __name__ == "__main__":
    train_and_save_models()
