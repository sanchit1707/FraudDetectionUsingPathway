import React, { useState } from 'react';
import { Send, AlertOctagon, Search, Sparkles } from 'lucide-react';

export default function Workbench({
  gwUrl,
  groqKey,
  onTxnSubmitted,
  dlqEntries = [],
  onRetryDlq,
  agent6Url = 'http://localhost:8000',
}) {
  const [activeTab, setActiveTab] = useState('submit');

  // Form State
  const [form, setForm] = useState({
    txn_id: 'TEST_' + Math.floor(Math.random() * 100000),
    account_id: 'ACC_001',
    amount: 9999.0,
    rolling_spend_10m: 25000.0,
    txn_count_10m: 12,
    bitmask: 15,
    ml_fraud_score: '0.95',
    active_threats: 'CONFIRMED_FRAUD',
    is_fraudulent: true,
    sanctions_hit: false,
  });

  const [submitting, setSubmitting] = useState(false);
  const [submitResult, setSubmitResult] = useState(null);

  // Audit Lookup state
  const [auditTxnId, setAuditTxnId] = useState('');
  const [auditResults, setAuditResults] = useState(null);
  const [loadingAudit, setLoadingAudit] = useState(false);

  const fillSample = () => {
    setForm({
      txn_id: 'TEST_' + Math.floor(Math.random() * 100000),
      account_id: 'ACC_' + Math.floor(Math.random() * 900 + 100),
      amount: (Math.random() * 8000 + 500).toFixed(2),
      rolling_spend_10m: 15000.0,
      txn_count_10m: 8,
      bitmask: 7,
      ml_fraud_score: (Math.random() * 0.5 + 0.4).toFixed(3), // Ambiguous band to trigger Groq LLM
      active_threats: 'HIGH_VELOCITY_SPIKE',
      is_fraudulent: true,
      sanctions_hit: false,
    });
  };

  const handleFormSubmit = async (e) => {
    e.preventDefault();
    setSubmitting(true);
    setSubmitResult(null);

    const payload = {
      txn_id: form.txn_id,
      account_id: form.account_id,
      amount: parseFloat(form.amount),
      rolling_spend_10m: parseFloat(form.rolling_spend_10m || 0),
      txn_count_10m: parseInt(form.txn_count_10m || 1),
      bitmask: parseInt(form.bitmask || 0),
      active_threats: form.active_threats || 'clean',
      is_fraudulent: form.is_fraudulent,
      sanctions_hit: form.sanctions_hit,
    };
    if (form.ml_fraud_score !== '') {
      payload.ml_fraud_score = parseFloat(form.ml_fraud_score);
    }
    if (groqKey.trim()) {
      payload.groq_api_key = groqKey.trim();
    }

    try {
      const res = await fetch(`${gwUrl}/submit`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(payload),
      });
      const data = await res.json();
      setSubmitResult(data);
      if (onTxnSubmitted) onTxnSubmitted(data);
    } catch (err) {
      setSubmitResult({ error: err.message });
    } finally {
      setSubmitting(false);
    }
  };

  const handleAuditLookup = async () => {
    if (!auditTxnId.trim()) return;
    setLoadingAudit(true);
    setAuditResults(null);
    try {
      const res = await fetch(`${agent6Url.replace(/\/+$/, '')}/audit/${encodeURIComponent(auditTxnId.trim())}`);
      const data = await res.json();
      setAuditResults(data);
    } catch (err) {
      setAuditResults({ error: err.message });
    } finally {
      setLoadingAudit(false);
    }
  };

  return (
    <div className="workbench-panel">
      <div className="tabs-bar">
        <button
          className={`tab-btn ${activeTab === 'submit' ? 'active' : ''}`}
          onClick={() => setActiveTab('submit')}
        >
          <Send size={15} /> Submit Transaction
        </button>
        <button
          className={`tab-btn ${activeTab === 'dlq' ? 'active' : ''}`}
          onClick={() => setActiveTab('dlq')}
        >
          <AlertOctagon size={15} /> DLQ ({dlqEntries.length})
        </button>
        <button
          className={`tab-btn ${activeTab === 'audit' ? 'active' : ''}`}
          onClick={() => setActiveTab('audit')}
        >
          <Search size={15} /> Agent 6 Audit Search
        </button>
      </div>

      {/* Tab 1: Submit Transaction */}
      {activeTab === 'submit' && (
        <div>
          <form className="txn-grid-form" onSubmit={handleFormSubmit}>
            <div className="input-group">
              <label>Transaction ID</label>
              <input
                type="text"
                value={form.txn_id}
                onChange={(e) => setForm({ ...form, txn_id: e.target.value })}
                required
              />
            </div>
            <div className="input-group">
              <label>Account ID</label>
              <input
                type="text"
                value={form.account_id}
                onChange={(e) => setForm({ ...form, account_id: e.target.value })}
                required
              />
            </div>
            <div className="input-group">
              <label>Amount ($)</label>
              <input
                type="number"
                step="0.01"
                value={form.amount}
                onChange={(e) => setForm({ ...form, amount: e.target.value })}
                required
              />
            </div>
            <div className="input-group">
              <label>Rolling Spend (10m)</label>
              <input
                type="number"
                step="0.01"
                value={form.rolling_spend_10m}
                onChange={(e) => setForm({ ...form, rolling_spend_10m: e.target.value })}
              />
            </div>
            <div className="input-group">
              <label>Txn Count (10m)</label>
              <input
                type="number"
                value={form.txn_count_10m}
                onChange={(e) => setForm({ ...form, txn_count_10m: e.target.value })}
              />
            </div>
            <div className="input-group">
              <label>Bitmask Flags</label>
              <input
                type="number"
                value={form.bitmask}
                onChange={(e) => setForm({ ...form, bitmask: e.target.value })}
              />
            </div>
            <div className="input-group">
              <label>ML Fraud Score (Optional)</label>
              <input
                type="number"
                step="0.001"
                value={form.ml_fraud_score}
                onChange={(e) => setForm({ ...form, ml_fraud_score: e.target.value })}
                placeholder="Auto"
              />
            </div>
            <div className="input-group">
              <label>Active Threat Code</label>
              <input
                type="text"
                value={form.active_threats}
                onChange={(e) => setForm({ ...form, active_threats: e.target.value })}
              />
            </div>

            <div className="full-col checkbox-group">
              <label>
                <input
                  type="checkbox"
                  checked={form.is_fraudulent}
                  onChange={(e) => setForm({ ...form, is_fraudulent: e.target.checked })}
                />
                Known Fraudulent
              </label>
              <label>
                <input
                  type="checkbox"
                  checked={form.sanctions_hit}
                  onChange={(e) => setForm({ ...form, sanctions_hit: e.target.checked })}
                />
                Sanctions Hit
              </label>
            </div>

            <div className="full-col" style={{ display: 'flex', gap: 10, marginTop: 6 }}>
              <button className="btn" type="submit" disabled={submitting}>
                <Send size={14} /> {submitting ? 'Running Pipeline...' : 'Run Through Pipeline'}
              </button>
              <button className="btn ghost" type="button" onClick={fillSample}>
                <Sparkles size={14} /> Fill Sample (Ambiguous LLM Band)
              </button>
            </div>
          </form>

          {submitResult && (
            <div style={{ marginTop: 16 }}>
              {submitResult.error ? (
                <div style={{ padding: 12, borderRadius: 8, background: 'rgba(245,86,106,0.15)', color: 'var(--red)', border: '1px solid var(--red)' }}>
                  Request Error: {submitResult.error}
                </div>
              ) : (
                <pre className="code-output">
                  {JSON.stringify(submitResult, null, 2)}
                </pre>
              )}
            </div>
          )}
        </div>
      )}

      {/* Tab 2: DLQ */}
      {activeTab === 'dlq' && (
        <div style={{ display: 'flex', flexDirection: 'column', gap: 16 }}>
          <div>
            <div className="panel-title" style={{ fontSize: 12, marginBottom: 8 }}>
              DEAD LETTER QUEUE (DLQ) — FAILED RETRIES
            </div>
            {dlqEntries.length === 0 ? (
              <div style={{ color: 'var(--muted)', fontSize: 12, padding: 12, background: 'var(--panel2)', borderRadius: 6 }}>
                DLQ is clean — 0 failed messages.
              </div>
            ) : (
              <div className="table-wrap">
                <table className="live-table">
                  <thead>
                    <tr>
                      <th>DLQ_ID</th>
                      <th>ERROR</th>
                      <th>ACTION</th>
                    </tr>
                  </thead>
                  <tbody>
                    {dlqEntries.map((e, idx) => (
                      <tr key={idx}>
                        <td className="mono">{e.dlq_id}</td>
                        <td>{e.error}</td>
                        <td>
                          <button className="btn ghost" style={{ padding: '3px 8px', fontSize: 11 }} onClick={() => onRetryDlq && onRetryDlq(e.dlq_id)}>
                            Retry Replay
                          </button>
                        </td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
            )}
          </div>
        </div>
      )}

      {/* Tab 3: Agent 6 Audit Search */}
      {activeTab === 'audit' && (
        <div style={{ display: 'flex', flexDirection: 'column', gap: 14 }}>
          <div style={{ display: 'flex', gap: 10, alignItems: 'center' }}>
            <input
              type="text"
              value={auditTxnId}
              onChange={(e) => setAuditTxnId(e.target.value)}
              placeholder="Enter Txn ID (e.g. TEST_001)"
              className="mono"
              style={{ width: '240px', padding: '6px 10px', background: 'var(--panel2)', border: '1px solid var(--border)', color: 'var(--text)', borderRadius: 6 }}
            />
            <button className="btn" onClick={handleAuditLookup} disabled={loadingAudit}>
              <Search size={14} /> {loadingAudit ? 'Searching...' : 'Lookup Audit Trail'}
            </button>
          </div>

          {auditResults && (
            <pre className="code-output">
              {JSON.stringify(auditResults, null, 2)}
            </pre>
          )}
        </div>
      )}
    </div>
  );
}
