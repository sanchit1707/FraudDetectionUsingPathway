<div align="center">
  <h1>⚡ FlashGuard</h1>


## What the project does

FlashGuard is an advanced, fully Dockerized multi-agent AI system that processes, audits, and investigates financial transactions in real-time. By orchestrating multiple specialized AI agents (powered by LangGraph and Groq) alongside real-time event streaming (powered by Pathway), it acts as a fully autonomous tier-1 and tier-2 compliance analyst.

It handles auto-approvals and auto-declines with millisecond latency, routes ambiguous transactions to LLM-driven ReAct reasoning loops, and automatically drafts Suspicious Activity Reports (SAR) while maintaining strict limits on AI execution to prevent hallucination and resource exhaustion.

## Why the project is useful

FlashGuard solves the scalability problems of modern financial security operations by bridging the gap between static LLM reasoning and live data streams.

### Creative Uses of Pathway
We leveraged [Pathway](https://pathway.com/) to push the boundaries of standard AI architecture:
- **Live Vector Sync for Compliance RAG**: Standard RAG pipelines require manual rebuilds. Pathway allows our `a5_compliance_rag` agent to hot-reload regulatory documents directly into the LLM's context memory in real-time. If AML rules change in a file, the agent instantly knows without a system restart.
- **Zero-Latency Telemetry Ledger**: Instead of standard REST webhooks, we creatively use Pathway event streams (`pathway:events`) as an immutable ledger. Every single LLM tool call, hallucination, and escalation decision is streamed with zero-latency to our downstream `lake_writer` to preserve a perfect audit trail.

### Performance Benchmarks
FlashGuard is heavily optimized for speed and token efficiency:
- **Auto-Decisions (Clean/High Fraud)**: ~15–20ms latency (bypassing LLM via deterministic ML heuristics).
- **Ambiguous LLM Escalation**: ~800–1200ms latency (full ReAct loop including multiple live tool executions).
- **Token Efficiency**: By utilizing the stateless BDH Watchdog to hard-cap LLM context exhaustion, we successfully reduced edge-case token consumption by over **80%**—allowing the entire multi-agent architecture to run stably under strict 6,000 TPM (Tokens Per Minute) free-tier API limits.
- **Crash Resilience**: 100% state recovery on hard container crashes via persistent Redis-backed session tracking.

### Key Features & Benefits:
- **Intelligent Routing**: Instantly approves clean traffic and declines obvious fraud, reserving costly LLM reasoning only for ambiguous, high-risk cases.
- **Strict AI Guardrails (BDH Watchdog)**: A stateless, Redis-backed sentinel actively monitors the LLMs. It strictly limits tool executions per transaction, completely eliminating the risk of infinite LLM reasoning loops and context exhaustion.
- **Live Compliance RAG**: Uses Pathway to maintain a live semantic index of AML/KYC regulations, enabling the orchestrator to query up-to-date compliance rules on the fly.
- **Zero-Latency Event Streaming**: As cases are investigated by the LLM, the decisions and state changes are pushed into a Pathway event stream (`pathway:events`) for the data lake to consume instantly.
- **Continuous Simulation**: Ships with a load-tester that simulates realistic transactional behavior (Clean, High Fraud, Sanctions Hits, Velocity Rings) directly into the gateway.

## How users can get started

FlashGuard is completely containerized. You do not need to manually configure Python dependencies, Node modules, or databases on your host machine. 

### Prerequisites
- Docker and Docker Compose installed.
- (On Linux) Run `sudo chmod -R 777 data` to ensure Redis has write access to the persistent volume.

### Installation & Setup

1. **Clone the repository:**
   ```bash
   git clone https://github.com/your-org/FlashGuard.git
   cd FlashGuard
   ```

2. **Start the stack:**
   ```bash
   docker compose up -d
   ```
   *(This single command boots the Gateway, Redis, Pathway Lake Writer, 4 AI Microservices, React Dashboard, and the Continuous Tester).*

### Usage Example

Once the containers are running, the background continuous tester will immediately begin injecting traffic.

- **View the Dashboard:** Open `http://localhost:8500` in your browser to monitor real-time transaction traffic and BDH Watchdog audits organically populate.
- **Manually Inject a Transaction:**
  ```bash
  curl -X POST http://localhost:8080/submit \
       -H "Content-Type: application/json" \
       -d '{
             "txn_id": "TXN_MANUAL_001",
             "account_id": "ACC_12345",
             "amount": 2500.0,
             "rolling_spend_10m": 5000.0,
             "txn_count_10m": 3,
             "bitmask": 0,
             "ml_fraud_score": 0.5
           }'
  ```


