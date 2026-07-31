import React, { useEffect, useRef, useState } from 'react';
import { RefreshCcw, Send, Activity } from 'lucide-react';
import { safeFetch } from '../config';

export default function FeedbackLoopPanel({ a10Url, selectedTxn }) {
  const [form, setForm] = useState({
    transaction_id: '',
    amount: 1000,
    velocity_1h: 5,
    risk_score: 0.5,
    actual_label: 0,
    predicted_label: 0,
  });
  const [result, setResult] = useState(null);
  const [loading, setLoading] = useState(false);
  const [stats, setStats] = useState(null);
  const [accuracyHistory, setAccuracyHistory] = useState([]); // real values only, appended over time
  const historyRef = useRef([]);

  useEffect(() => {
    if (selectedTxn) {
      setForm((f) => ({
        ...f,
        transaction_id: selectedTxn.txnId || f.transaction_id,
        amount: selectedTxn.amount ?? f.amount,
        risk_score: selectedTxn.score ?? f.risk_score,
        predicted_label:
          (selectedTxn.action || '').toUpperCase().includes('BLOCK') ? 1 : 0,
      }));
    }
  }, [selectedTxn]);

  const pollStats = async () => {
    const s = await safeFetch(`${a10Url.replace(/\/+$/, '')}/stats`);
    setStats(s);
    if (s && !s.error && typeof s.online_accuracy === 'number') {
      const next = [...historyRef.current, s.online_accuracy].slice(-40);
      historyRef.current = next;
      setAccuracyHistory(next);
    }
  };

  useEffect(() => {
    pollStats();
    const id = setInterval(pollStats, 4000);
    return () => clearInterval(id);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [a10Url]);

  const submit = async () => {
    setLoading(true);
    setResult(null);
    const data = await safeFetch(a10Url.replace(/\/+$/, ''), {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({
        transaction_id: form.transaction_id || `FB_${Date.now()}`,
        amount: parseFloat(form.amount) || 0,
        velocity_1h: parseFloat(form.velocity_1h) || 0,
        risk_score: parseFloat(form.risk_score) || 0,
        actual_label: parseInt(form.actual_label) || 0,
        predicted_label: parseInt(form.predicted_label) || 0,
      }),
    });
    setResult(data);
    setLoading(false);
    pollStats();
  };

  const unwrap = (d) => {
    if (!d) return d;
    if (Array.isArray(d) && d[0]) return d[0].result ?? d[0];
    return d.result ?? d;
  };
  const r = unwrap(result);

  // Simple real-data sparkline: polyline built from accuracyHistory
  const sparkPoints = accuracyHistory
    .map((v, i) => {
      const x = (i / Math.max(1, accuracyHistory.length - 1)) * 100;
      const y = 100 - v * 100;
      return `${x},${y}`;
    })
    .join(' ');

  return (
    <div style={{ display: 'flex', flexDirection: 'column', gap: 16 }}>
      <div className="panel-box">
        <div className="panel-header">
          <div className="panel-title">
            <RefreshCcw size={14} style={{ display: 'inline', marginRight: 6 }} />
            A10 — Online Feedback Loop (river: StandardScaler | LogisticRegression)
          </div>
          <span className="panel-tag">
            {stats && !stats.error ? `${stats.total_events_processed ?? 0} EVENTS LEARNED` : 'UNREACHABLE'}
          </span>
        </div>

        <div className="stats-mini-grid">
          <div><span>Online accuracy</span><strong className="mono" style={{ color: 'var(--green)' }}>{stats?.online_accuracy ?? '—'}</strong></div>
          <div><span>Online ROC-AUC</span><strong className="mono" style={{ color: 'var(--accent)' }}>{stats?.online_roc_auc ?? '—'}</strong></div>
          <div><span>Last txn learned</span><strong className="mono">{stats?.last_transaction_id ?? '—'}</strong></div>
          <div><span>Last predicted / actual</span><strong className="mono">{stats?.last_predicted_label ?? '—'} / {stats?.last_actual_label ?? '—'}</strong></div>
          <div><span>Uptime</span><strong className="mono">{stats?.uptime_seconds ?? '—'}s</strong></div>
        </div>

        {accuracyHistory.length > 1 && (
          <div className="spark-wrap">
            <div className="panel-tag" style={{ marginBottom: 6 }}>LIVE ONLINE ACCURACY (real, polled every 4s)</div>
            <svg viewBox="0 0 100 100" preserveAspectRatio="none" className="spark-svg">
              <polyline points={sparkPoints} fill="none" stroke="var(--green)" strokeWidth="2" vectorEffect="non-scaling-stroke" />
            </svg>
          </div>
        )}

        <div className="txn-grid-form" style={{ marginTop: 16, marginBottom: 12 }}>
          <div className="input-group">
            <label>Transaction ID</label>
            <input type="text" value={form.transaction_id} onChange={(e) => setForm({ ...form, transaction_id: e.target.value })} placeholder="auto-generated if empty" />
          </div>
          <div className="input-group">
            <label>Amount ($)</label>
            <input type="number" value={form.amount} onChange={(e) => setForm({ ...form, amount: e.target.value })} />
          </div>
          <div className="input-group">
            <label>Velocity (1h)</label>
            <input type="number" value={form.velocity_1h} onChange={(e) => setForm({ ...form, velocity_1h: e.target.value })} />
          </div>
          <div className="input-group">
            <label>Risk Score</label>
            <input type="number" step="0.01" value={form.risk_score} onChange={(e) => setForm({ ...form, risk_score: e.target.value })} />
          </div>
          <div className="input-group">
            <label>Actual Label (ground truth)</label>
            <select value={form.actual_label} onChange={(e) => setForm({ ...form, actual_label: e.target.value })}>
              <option value={0}>0 — Legitimate</option>
              <option value={1}>1 — Fraud</option>
            </select>
          </div>
          <div className="input-group">
            <label>Predicted Label (pipeline's call)</label>
            <select value={form.predicted_label} onChange={(e) => setForm({ ...form, predicted_label: e.target.value })}>
              <option value={0}>0 — Legitimate</option>
              <option value={1}>1 — Fraud</option>
            </select>
          </div>
        </div>

        <button className="btn" onClick={submit} disabled={loading}>
          <Send size={14} /> {loading ? 'Learning online...' : 'Submit Real Feedback'}
        </button>

        {result && (
          result.error ? (
            <div className="empty-note" style={{ color: 'var(--red)', marginTop: 12 }}>{result.error}</div>
          ) : (
            <pre className="code-output" style={{ marginTop: 12 }}>{JSON.stringify(r, null, 2)}</pre>
          )
        )}
      </div>

      <div className="panel-box">
        <div className="panel-header">
          <div className="panel-title"><Activity size={14} style={{ display: 'inline', marginRight: 6 }} /> How this closes the loop</div>
        </div>
        <p style={{ fontSize: 13, color: 'var(--muted)', lineHeight: 1.6 }}>
          Every feedback event trains the online logistic-regression model one step
          (`model.learn_one`) and updates its running accuracy / ROC-AUC in real time —
          the numbers above are read directly from that live model's state via A10's
          `/stats` endpoint, not simulated.
        </p>
      </div>
    </div>
  );
}
