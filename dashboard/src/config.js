// Central place for every service URL the dashboard talks to.
// Every value is real, user-editable, and persisted to localStorage —
// nothing here is mocked; if a service isn't reachable, callers show
// the failure instead of substituting fake data.

const DEFAULTS = {
  gwUrl: 'http://localhost:8080',        // Gateway (Pathway L0-L4 + LangGraph)
  bdhUrl: 'http://localhost:8090',       // BDH Watchdog
  agent6Url: 'http://localhost:8000',    // Agent 6 execution/audit
  a5Url: 'http://localhost:8531',        // A5 Compliance RAG (sidecar)
  a6bUrl: 'http://localhost:8532',       // A6b Drift Detector (sidecar)
  a8Url: 'http://localhost:8533',        // A8 SAR Drafter (sidecar)
  a10Url: 'http://localhost:8535',       // A10 Feedback Loop (sidecar)
  groqKey: '',
};

export function loadConfig() {
  const cfg = {};
  for (const key of Object.keys(DEFAULTS)) {
    cfg[key] = localStorage.getItem(`fg_${key}`) ?? DEFAULTS[key];
  }
  return cfg;
}

export function saveConfigValue(key, value) {
  localStorage.setItem(`fg_${key}`, value);
}

export const CONFIG_DEFAULTS = DEFAULTS;

// Shared safe-fetch helper: never throws, never fabricates a result.
export async function safeFetch(url, options = {}, timeoutMs = 6000) {
  try {
    const res = await fetch(url, { ...options, signal: AbortSignal.timeout(timeoutMs) });
    const text = await res.text();
    let data;
    try {
      data = text ? JSON.parse(text) : {};
    } catch {
      data = { raw: text };
    }
    if (!res.ok) {
      return { error: `HTTP ${res.status}`, detail: data };
    }
    return data;
  } catch (err) {
    return { error: err.message || String(err) };
  }
}
