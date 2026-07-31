# FlashGuard Live Dashboard

A single, dependency-free HTML file (`index.html`) that talks **directly** to your
running FlashGuard `docker-compose` stack over its real REST APIs. Nothing on this
page is mocked or hard-coded — every number, table row, and chart point comes from
a live `fetch()` call to your services:

| Panel | Endpoint it calls |
|---|---|
| Stat cards + verdict chart | `GET {gateway}/metrics` |
| Service health | `GET {gateway}/health`, `GET {gateway}/ready`, `GET {bdh}/health`, `GET {agent6}/health` |
| Live event stream | `GET {gateway}/stream/recent` (reads Redis Stream `pathway:events`) |
| Dead letter queue + retry | `GET {gateway}/dlq`, `POST {gateway}/dlq/retry?dlq_id=...` |
| BDH active sessions | `GET {bdh}/sessions` |
| Submit transaction | `POST {gateway}/submit` (runs the full Pathway L0→L4 → LangGraph → Agent 6 pipeline synchronously and shows the real verdict) |
| Agent 6 audit trail | `GET {agent6}/audit/{txn_id}` |

This mirrors the approach in Pathway's own guides — a lightweight web frontend
polling a REST/streaming backend — as described here:
- https://pathway.com/developers/user-guide/deployment/web-dashboard
- https://pathway.com/developers/templates/etl/realtime-log-monitoring

Your project already exposes exactly this kind of backend (FastAPI + Redis Streams
in `gateway/main.py`), so the dashboard is just a thin, honest client on top of it —
no separate Pathway REST connector or extra backend was needed or added.

## 1. Start your stack

From the project root (the folder with `docker-compose.yml`):

```bash
cp .env.example .env     # add your GROQ_API_KEY
docker compose up --build
```

Wait until `gateway`, `bdh_watchdog`, and `agent6` report healthy
(`docker compose ps`). By default they listen on:

- Gateway → `http://localhost:8080`
- BDH Watchdog → `http://localhost:8090`
- Agent 6 → `http://localhost:8000`

All three already have CORS wide open (`allow_origins=["*"]` in their FastAPI
apps), so a static page opened in your browser can call them directly — no proxy
needed.

## 2. Open the dashboard

Just double-click `index.html`, or serve it (either works identically since it
makes no calls back to its own origin):

```bash
cd dashboard
python3 -m http.server 8500
# then open http://localhost:8500
```

If your containers run on a remote host or different ports, edit the three URL
fields at the top-right of the dashboard header — they take effect on the next
poll (every 4 seconds), no reload required.

## 3. Using it

- **Submit Transaction** — POSTs to `/submit`; use "Fill sample" to load the exact
  payload from the project's own README, or enter your own values. The result
  card shows the real verdict (`ALLOW` / `FLAG` / `BLOCK`), fraud score, tier,
  whether it was escalated to the LLM, the LLM's reasoning (if escalated), and
  Agent 6's execution result.
- **Live Event Stream** — tails the `pathway:events` Redis Stream that
  `stream_emitter.py` / `gateway/main.py` write to, refreshed every 4 seconds.
- **Dead Letter Queue** — anything that failed `MAX_RETRIES` times in the alert
  consumer shows up here; click **Retry** to replay it through `/dlq/retry`.
- **BDH Active Sessions** — shows live LangGraph→BDH audit sessions (tool call
  counts, repeat counts) from the out-of-band watchdog.
- **Agent 6 Audit Trail** — look up any `txn_id` to see its full audit log from
  Agent 6's idempotent execution store.

## Notes / honesty check

- If a service is down or unreachable, the relevant panel shows an explicit
  "unreachable" message instead of fabricating data — it never falls back to
  fake numbers.
- The verdict-volume chart is a client-side rolling window (last ~30 polls) of
  the cumulative counters already returned by `/metrics`; it is not a separate
  data source.
- No API keys, secrets, or write access beyond what your gateway already exposes
  are embedded in this file.
