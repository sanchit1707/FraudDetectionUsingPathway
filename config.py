import os

class Config:
    # 1. Paths to Data Assets
    # Points directly to the compact dataset we just built
    PAYSIM_PATH = "data/ieee_transactions.csv" 
    
    PROFILES_PATH = "data/customers.csv"
    SANCTIONS_PATH = "data/sanctions.csv"
    POLICY_DOCS_PATH = "data/policy_docs/"
    
    # 2. Performance Tuning & Simulators
    # Streams 5 transactions per second so you can watch the streaming data loop in real-time
    REPLAY_RATE = 10000
    
    # 3. Production Infrastructure Brokers
    KAFKA_HOST = "localhost:19092"
