# CHANGES IN THIS PASS

This pass focused on: (1) actually wiring **A10 Feedback Loop** — and the other
previously-unused agents A5/A6b/A8 — into the dashboard with real data, (2)
removing hardcoded/fake fallback values that were being displayed as if they
were live, and (3) a visual + navigation redesign (dark teal "command center"
look, left icon sidebar) inspired by the provided Stitch mockups.

## Backend changes

- **New `_sidecar.py`** in `a5_compliance_rag/`, `a6b_drift_detector/`,
  `a8_sar_drafter/`, `a10_feedback_loop/`. These four agents are raw Pathway
  webservers with no CORS support and no GET status route, so the browser
  dashboard could never call them directly. The sidecar is a small
  stdlib-only (no new dependencies) background thread that:
  - answers `GET /stats` with the agent's **real** in-memory counters
    (online accuracy/ROC-AUC for A10, drift counts for A6b, query counts for
    A5, SAR counts for A8) — nothing invented.
  - proxies `POST` bodies through to the agent's real Pathway route and
    relays the real response back with CORS headers attached.
- Added real counters/state tracking inside each agent's processing UDF so
  the `/stats` numbers are genuinely live (`STATS` dict in A5/A8,
  `FeedbackLoopState`/`DriftDetectorState` fields in A10/A6b).
- `docker-compose.yml` + each `Dockerfile`: added the new sidecar ports
  (8531–8535, mapped from container ports 8511–8515).

## Frontend changes

- **New pages/panels**, one per previously-unused agent, added to a new
  left icon sidebar (`Sidebar.jsx`):
  - `OrchestratorPanel.jsx` — real LangGraph Node 1-4 state (Watchdog,
    parallel scoring, action gateway, LLM escalation) from the last
    transaction's real payload.
  - `WatchdogPanel.jsx` — BDH audit sessions, moved into its own page.
  - `CompliancePanel.jsx` — **A5** live RAG query box + **A8** SAR
    narrative drafting, both calling the real sidecar endpoints.
  - `DriftMonitorPanel.jsx` — **A6b**: submit a transaction, see real
    ADWIN/HalfSpaceTrees drift output and running stats.
  - `FeedbackLoopPanel.jsx` — **A10**: submit feedback, see the real
    online-learned accuracy/ROC-AUC update live (polled every 4s), with a
    real (not simulated) accuracy sparkline built from polled values.
  - `SettingsPanel.jsx` — every service URL in one place, persisted to
    `localStorage` (`config.js`).
- **Fixed fake-data bugs** that were shipping in the original dashboard:
  - `FraudGaugeChart.jsx` defaulted to a fake score (`0.826`), fake account
    (`ACC_1133`), and fake amount (`1314.41`) before any real transaction
    existed — now shows honest "—" placeholders.
  - `metrics.approved || 4` (and `|| 1`, `|| 3`) meant a **real zero** count
    was silently replaced by a fake fallback number, since `0` is falsy in
    JS — changed to `??` so real zeros display as zero.
  - `LiveStreamTable.jsx` fabricated `TXN_1000`, `ACC_1100`, `$1250.00`,
    `0.125` whenever a field was missing from a real event — now shows "—"
    instead of inventing plausible-looking data.
  - `PipelineFlow.jsx` had hardcoded fake per-stage throughput/latency
    labels (`4.2k req/s`, `72/s`, `12ms`, etc.) that never reflected
    anything real — replaced with the one real number available
    (total transactions processed) and honest static architecture labels.
  - `index.html` was actually a **stale production build output**
    (referencing hashed `dist/assets/*` files that no longer exist) instead
    of the Vite dev source — `npm run dev` would have failed outright. Fixed
    to the correct Vite entry pointing at `/src/main.jsx`.
  - The old SAR-drafting call in `Workbench.jsx` POSTed directly to A8's raw
    Pathway port (`:8023`), which would fail CORS in any real browser —
    moved to `CompliancePanel.jsx` using the new sidecar (real fix, not just
    a relocation).
- Retheme (`index.css`): dark near-black background, teal/mint accent
  (`#57f1db`), JetBrains Mono for data + Inter for UI text, matching the
  Stitch "FlashGuard Command Center" mockups — plus a new left icon-rail
  sidebar layout.
- Verified with an actual `npm install && npm run build` — it compiles
  and bundles clean (no errors).

## Honest limitations — please read before assuming this "just works"

- I could **not** spin up Docker/Redis/the full multi-container stack in
  the sandbox this was built in, so while every change above is either a
  verified frontend build or a syntax-checked Python edit, I have **not**
  watched real transactions flow through A5/A6b/A8/A10 end-to-end. Please
  run `docker-compose up --build` and sanity-check each new panel against
  your Groq API key / Redis instance.
- The Stitch mockups describe several more screens (e.g. a dedicated
  "fraud detection pipeline dashboard" screen) than there was time to
  fully port pixel-for-pixel — the redesign captures the color/type system
  and sidebar navigation pattern, mapped onto the panels above, rather than
  recreating every mockup screen exactly.
- If a sidecar port conflicts with something already running on your
  machine, change it in `docker-compose.yml`, the matching agent's
  `start_sidecar(...)` call, and `Settings` in the dashboard.
