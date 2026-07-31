import React from 'react';
import { Eye, ShieldAlert } from 'lucide-react';

const RULES = [
  'Hallucination check',
  'Schema validation',
  'State-drift detection',
  'Loop guard',
  'Idempotency check',
];

export default function WatchdogPanel({ bdhSessions = {}, bdhUrl }) {
  const sessionEntries = Object.entries(bdhSessions || {}).filter(
    ([k]) => k !== 'error'
  );
  const hasError = bdhSessions && bdhSessions.error;

  return (
    <div style={{ display: 'flex', flexDirection: 'column', gap: 16 }}>
      <div className="panel-box">
        <div className="panel-header">
          <div className="panel-title">
            <Eye size={14} style={{ display: 'inline', marginRight: 6 }} />
            BDH Watchdog — Out-of-Band Audit
          </div>
          <span className="panel-tag">{bdhUrl}</span>
        </div>

        <div className="rule-chip-row">
          {RULES.map((r) => (
            <span key={r} className="rule-chip">{r}</span>
          ))}
        </div>

        {hasError ? (
          <div className="empty-note" style={{ color: 'var(--red)' }}>
            <ShieldAlert size={14} style={{ display: 'inline', marginRight: 6 }} />
            Could not reach BDH Watchdog at {bdhUrl}: {bdhSessions.error}
          </div>
        ) : sessionEntries.length === 0 ? (
          <div className="empty-note">
            No active sessions reported yet. BDH audits every LLM tool call
            made by Node 4 — sessions appear here once a transaction escalates.
          </div>
        ) : (
          <pre className="code-output">{JSON.stringify(bdhSessions, null, 2)}</pre>
        )}
      </div>
    </div>
  );
}
