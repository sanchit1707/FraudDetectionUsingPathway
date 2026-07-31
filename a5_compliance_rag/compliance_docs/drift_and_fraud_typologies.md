# Concept Drift and Emerging Fraud Typologies in Streaming Transactions

## 1. Statistical Concept Drift in Fraud Patterns
Fraud typologies continuously evolve over time, leading to concept drift where historical transaction distributions no longer match current real-time data. When A6b Drift Detector identifies statistical drift using ADWIN over transaction amounts or velocity scores, it signals a significant shift in cardholder or fraudster behavior.

## 2. Response to Model Drift
When statistical drift is detected by pure statistical monitors (ADWIN), underlying anomaly detection models such as River Half-Space Trees (HST) must be reset or re-calibrated. An escalation occurring right after a drift reset requires additional scrutiny in the SAR narrative, noting that the transaction occurred during a period of active behavioral distribution shift.
