import React, { useEffect, useState } from 'react';
import { LineChart, Send } from 'lucide-react';
import { safeFetch } from '../config';

export default function DriftMonitorPanel({ a6bUrl, selectedTxn }) {
  const [form, setForm] = useState({
    transaction_id: '',
    amount: 1000,
    velocity_1h: 5,
    risk_score: 0.3,
  });
  const [result, setResult] = useState(null);
  const [loading, setLoading] = useState(false);
  const [stats, setStats] = useState(null);

  useEffect(() => {
    if (selectedTxn) {
      setForm((f) => ({
        ...f,
        transaction_id: selectedTxn.txnId || f.transaction_id,
        amount: selectedTxn.amount ?? f.amount,
        risk_score: selectedTxn.score ?? f.risk_score,
      }));
    }
  }, [selectedTxn]);

  const pollStats = async () => {
    const s = await safeFetch(`${a6bUrl.replace(/\/+$/, '')}/stats`);
    setStats(s);
  };

  useEffect(() => {
    pollStats();
    const id = setInterval(pollStats, 4000);
    return () => clearInterval(id);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [a6bUrl]);

  const submit = async () => {
    setLoading(true);
    setResult(null);
    const data = await safeFetch(a6bUrl.replace(/\/+$/, ''), {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({
        transaction_id: form.transaction_id || `DRIFT_${Date.now()}`,
        amount: parseFloat(form.amount) || 0,
        velocity_1h: parseFloat(form.velocity_1h) || 0,
        risk_score: parseFloat(form.risk_score) || 0,
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

  return (
    <div style={{ display: 'flex', flexDirection: 'column', gap: 16 }}>
      <div className="panel-box">
        <div className="panel-header">
          <div className="panel-title">
            <LineChart size={14} style={{ display: 'inline', marginRight: 6 }} />
            A6b — Drift Detector (ADWIN + HalfSpaceTrees)
          </div>
          <span className="panel-tag">
            {stats && !stats.error
              ? `${stats.total_transactions ?? 0} SEEN · ${stats.total_drifts_detected ?? 0} DRIFTS`
              : 'UNREACHABLE'}
          </span>
        </div>

        <div className="stats-mini-grid">
          <div><span>Last status</span><strong className="mono">{stats?.last_status ?? '—'}</strong></div>
          <div><span>Last anomaly score</span><strong className="mono">{stats?.last_anomaly_score ?? '—'}</strong></div>
          <div><span>ADWIN amount drift</span><strong className="mono">{String(stats?.adwin_amount_drift ?? false)}</strong></div>
          <div><span>ADWIN velocity drift</span><strong className="mono">{String(stats?.adwin_velocity_drift ?? false)}</strong></div>
          <div><span>Resets applied</span><strong className="mono">{stats?.total_resets_applied ?? 0}</strong></div>
          <div><span>Uptime</span><strong className="mono">{stats?.uptime_seconds ?? '—'}s</strong></div>
        </div>

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
        </div>

        <button className="btn" onClick={submit} disabled={loading}>
          <Send size={14} /> {loading ? 'Scoring via ADWIN + HST...' : 'Feed Real Transaction'}
        </button>

        {result && (
          result.error ? (
            <div className="empty-note" style={{ color: 'var(--red)', marginTop: 12 }}>{result.error}</div>
          ) : (
            <pre className="code-output" style={{ marginTop: 12 }}>{JSON.stringify(r, null, 2)}</pre>
          )
        )}
      </div>
    </div>
  );
}
