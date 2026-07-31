import React from 'react';
import { Eye, Split, GitMerge, BrainCircuit } from 'lucide-react';

function NodeCard({ icon: Icon, title, subtitle, done, children }) {
  return (
    <div className={`orch-node ${done ? 'done' : ''}`}>
      <div className="orch-node-head">
        <div className="orch-node-icon"><Icon size={16} /></div>
        <div>
          <div className="orch-node-title">{title}</div>
          <div className="orch-node-sub">{subtitle}</div>
        </div>
      </div>
      <div className="orch-node-body">{children}</div>
    </div>
  );
}

export default function OrchestratorPanel({ selectedTxn }) {
  const p = selectedTxn?.payload || {};
  const hasData = Boolean(selectedTxn);

  const checkpoint = p.checkpoint_node || null;
  const nodeReached = (name) => {
    const order = ['watchdog', 'scoring', 'action_gateway', 'llm_escalation'];
    if (!checkpoint) return false;
    const idx = order.indexOf(checkpoint);
    return idx >= order.indexOf(name);
  };

  return (
    <div className="panel-box" style={{ display: 'flex', flexDirection: 'column', gap: 16 }}>
      <div className="panel-header">
        <div className="panel-title">LangGraph Orchestrator — Node 1-4 Execution</div>
        <span className="panel-tag">
          {hasData ? `TXN ${selectedTxn.txnId}` : 'NO TRANSACTION SELECTED'}
        </span>
      </div>

      {!hasData && (
        <div className="empty-note">
          Submit or select a transaction from Live Stream to see its real node-by-node
          orchestrator trace here — nothing is shown until real pipeline output exists.
        </div>
      )}

      {hasData && (
        <div className="orch-grid">
          <NodeCard
            icon={Eye}
            title="Node 1 — Watchdog"
            subtitle="Redis loop-counter guard"
            done={nodeReached('watchdog') || p.loop_count !== undefined}
          >
            <div>Loop count: <strong className="mono">{p.loop_count ?? '—'}</strong></div>
            <div>Killed: <strong className="mono">{String(p.killed ?? false)}</strong></div>
            {p.error && <div style={{ color: 'var(--red)' }}>Error: {p.error}</div>}
          </NodeCard>

          <NodeCard
            icon={Split}
            title="Node 2 — Parallel Scoring"
            subtitle="A2 Sanctions · A3 Ring · A4 ML Score"
            done={p.fraud_score !== undefined}
          >
            <div>Fraud score: <strong className="mono">{p.fraud_score ?? p.final_score ?? '—'}</strong></div>
            <div>Sanctions hit: <strong className="mono">{String(p.sanctions_hit ?? false)}</strong>{p.sanctions_conf != null && ` (${p.sanctions_conf})`}</div>
            <div>Ring detected: <strong className="mono">{String(p.ring_detected ?? false)}</strong>{p.ring_size != null && ` · size ${p.ring_size}`}</div>
            {Array.isArray(p.fraud_reasons) && p.fraud_reasons.length > 0 && (
              <div style={{ marginTop: 4 }}>Reasons: {p.fraud_reasons.join(', ')}</div>
            )}
          </NodeCard>

          <NodeCard
            icon={GitMerge}
            title="Node 3 — Action Gateway"
            subtitle="Merge signals → tier / action"
            done={p.final_action !== undefined || selectedTxn.action}
          >
            <div>Final tier: <strong className="mono">{p.final_tier ?? '—'}</strong></div>
            <div>Final action: <strong className={`tier-badge ${(selectedTxn.action || '').toUpperCase()}`}>{selectedTxn.action || '—'}</strong></div>
          </NodeCard>

          <NodeCard
            icon={BrainCircuit}
            title="Node 4 — LLM Escalation"
            subtitle="Groq + 4 MCP tools, BDH-guarded"
            done={Boolean(p.llm_escalated)}
          >
            <div>Escalated: <strong className="mono">{String(p.llm_escalated ?? false)}</strong></div>
            {p.llm_escalated ? (
              <>
                <div>Source: <strong className="mono">{p.llm_source ?? '—'}</strong></div>
                <div>LLM verdict: <strong className="mono">{p.llm_verdict ?? '—'}</strong></div>
                {p.llm_reasoning && (
                  <div style={{ marginTop: 6, color: 'var(--muted)', fontSize: 12 }}>
                    {p.llm_reasoning}
                  </div>
                )}
                {Array.isArray(p.llm_tool_calls) && p.llm_tool_calls.length > 0 && (
                  <div style={{ marginTop: 6 }}>Tool calls: {p.llm_tool_calls.length}</div>
                )}
              </>
            ) : (
              <div style={{ color: 'var(--muted)', fontSize: 12 }}>
                Only runs for ambiguous scores in the 0.40–0.75 band.
              </div>
            )}
          </NodeCard>
        </div>
      )}
    </div>
  );
}
