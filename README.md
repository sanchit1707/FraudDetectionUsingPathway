# FlashGuard — Pathway-Powered Agentic Gateway

> **IITISoC 2026 Submission** | Real-time fraud detection with LLM escalation, out-of-band BDH watchdog, and incremental Pathway streaming.

## Architecture

```
┌──────────────────── GATEWAY (Docker) ─────────────────────────────┐
│  Pathway Pipeline (L0→L4)                                          │
│  L0: CSV replay (ieee_transactions.csv)                            │
│  L1: Enrich + geo-feature (profile join)                           │
│  L2: Bitmask + 10-min sliding window                               │
│  L3: Rule engine (velocity/spend/watchlist thresholds)             │
│  L4: XGBoost + HalfSpaceTrees ensemble → fraud_score              │
│                                                                     │
│  LangGraph Orchestrator (Nodes 1-4):                               │
│  Node 1: Watchdog (Redis loop counter)                             │
│  Node 2: Parallel scoring (A2/A3/A4)                              │
│  Node 3: Action Gateway (merge → tier/action)                      │
│  Node 4: ⭐ LLM Escalation (Groq + 4 MCP tools, BDH-guarded)     │
│          ONLY for ambiguous scores 0.40-0.75                       │
│                                                                     │
│  Agent 6: Idempotent execution (LOCK_CARD/FREEZE/NOTIFY)          │
└───────────────────────────────────────────────────────────────────┘
          │  Redis Stream: pathway:events
          ▼
┌──────── BDH WATCHDOG (Separate Docker) ───────────────────────────┐
│  Standalone FastAPI microservice                                    │
│  Consumes pathway:events out-of-band via XREAD consumer group      │
│  POST /audit: pre-flight 5-rule check on every LLM tool call       │
│  Rules: Hallucination | Schema | State Drift | Loop | Idempotency  │
└───────────────────────────────────────────────────────────────────┘
```

## Quick Start

### 1. Copy environment variables
```bash
cp .env.example .env
# Edit .env and add your GROQ_API_KEY (free at https://console.groq.com)
```

### 2. Build and start
```bash
docker compose up --build
```

### 3. Submit a test transaction
```bash
curl -X POST http://localhost:8080/submit \
  -H "Content-Type: application/json" \
  -d '{
    "txn_id": "TEST_001",
    "account_id": "ACC_001",
    "amount": 9999.0,
    "rolling_spend_10m": 25000.0,
    "txn_count_10m": 12,
    "bitmask": 15,
    "ml_fraud_score": 0.95,
    "is_fraudulent": true,
    "active_threats": "CONFIRMED_FRAUD",
    "sanctions_hit": false
  }'
```

## Service Endpoints

| Service | Port | Key Endpoint |
|---------|------|-------------|
| Gateway | 8080 | `POST /submit`, `GET /metrics`, `GET /stream/recent` |
| BDH Watchdog | 8090 | `POST /audit`, `GET /sessions` |
| Agent 6 | 8000 | `POST /execute`, `GET /audit/{txn_id}` |
| A5 Compliance RAG | 8011 | `POST /` (query) |
| A6b Drift Detector | 8012 | `POST /` (transaction) |
| A8 SAR Drafter | 8013 | `POST /` (frozen txn) |
| A10 Feedback Loop | 8014 | `POST /feedback` |

## Running Tests

```bash
# All fraud signal types (8 signals)
docker compose exec test_runner python /tests/test_signals.py

# All BDH watchdog rules (5 rules)
docker compose exec test_runner python /tests/test_bdh.py

# End-to-end pipeline
docker compose exec test_runner python /tests/test_pipeline.py

# Chaos engineering
docker compose exec test_runner python /tests/test_chaos.py

# Legacy async agents test
docker compose exec test_runner python test_agents.py
```

## Key Design Decisions

### Why Pathway in Docker only?
Pathway requires Linux kernel features (io_uring). On Windows, it must run inside Docker. The `pathwaycom/pathway:latest` base image provides a pre-configured environment.

### LLM Provider
- **Groq (default)**: Free tier, ~30 req/min, llama-3.1-8b-instant
- **Graceful degradation**: If no `GROQ_API_KEY`, Node 4 uses deterministic rules
- Rate limiting: 0.5s sleep between tool calls, exponential backoff on 429

### BDH Separation
BDH runs as its own Docker container (`bdh_watchdog`) with no direct import dependency on the gateway. Communication is via HTTP (`POST /audit`) and Redis Stream consumption (out-of-band).

### State Checkpointing
`orcestrator/checkpointer.py` saves state to Redis after each LangGraph node. On container restart, `load_checkpoint()` resumes from last completed node (not from scratch).

## Rubric Coverage

| Item | Status | How |
|------|--------|-----|
| Sec 2.1 Fault Tolerance | ✅ | Redis checkpointing in `checkpointer.py` |
| Sec 2.1 Throughput | ✅ | Pathway L2 backpressure + Redis Stream |
| Sec 3.1 Provider-Agnostic | ✅ | `adapter/balancer.py` + Groq/OpenAI/Ollama |
| Sec 3.2 State Stream | ✅ | `stream_emitter.py` → `pathway:events` Redis Stream |
| Sec 3.2 BDH Out-of-Band | ✅ | `bdh_service/` separate container |
| Sec 3.2 Loop Detection | ✅ | 5-rule audit in BDH |
| Sec 5 Containerization | ✅ | `docker-compose.yml` with all services |
| Sec 4 Product Direction | ✅ | High-Frequency Financial Monitor |
| LLM Decision Power | ✅ | Node 4 calls 4 tools, overrides action_gateway |
