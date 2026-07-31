import React, { useEffect, useState } from 'react';
import { Gavel, Search, FileText } from 'lucide-react';
import { safeFetch } from '../config';

export default function CompliancePanel({ a5Url, a8Url, selectedTxn }) {
  const [query, setQuery] = useState('structuring transactions high-risk merchant');
  const [queryResult, setQueryResult] = useState(null);
  const [loadingQuery, setLoadingQuery] = useState(false);
  const [a5Stats, setA5Stats] = useState(null);

  const [sarForm, setSarForm] = useState({
    transaction_id: '',
    card_id: 'CARD_9921',
    customer_id: '',
    amount: 0,
    merchant: 'HighRiskMerchant_LLC',
    freeze_reason: 'HIGH_VELOCITY_SPIKE',
    velocity_1h: 12.0,
  });
  const [sarResult, setSarResult] = useState(null);
  const [loadingSar, setLoadingSar] = useState(false);
  const [a8Stats, setA8Stats] = useState(null);

  // Pre-fill SAR form from the currently selected real transaction, if any
  useEffect(() => {
    if (selectedTxn) {
      setSarForm((f) => ({
        ...f,
        transaction_id: selectedTxn.txnId || f.transaction_id,
        customer_id: selectedTxn.accountId || f.customer_id,
        amount: selectedTxn.amount ?? f.amount,
      }));
    }
  }, [selectedTxn]);

  const pollStats = async () => {
    const s5 = await safeFetch(`${a5Url.replace(/\/+$/, '')}/stats`);
    setA5Stats(s5);
    const s8 = await safeFetch(`${a8Url.replace(/\/+$/, '')}/stats`);
    setA8Stats(s8);
  };

  useEffect(() => {
    pollStats();
    const id = setInterval(pollStats, 5000);
    return () => clearInterval(id);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [a5Url, a8Url]);

  const runQuery = async () => {
    setLoadingQuery(true);
    setQueryResult(null);
    const data = await safeFetch(a5Url.replace(/\/+$/, ''), {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ query, top_k: 3 }),
    });
    setQueryResult(data);
    setLoadingQuery(false);
    pollStats();
  };

  const runSar = async () => {
    setLoadingSar(true);
    setSarResult(null);
    const data = await safeFetch(a8Url.replace(/\/+$/, ''), {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({
        ...sarForm,
        amount: parseFloat(sarForm.amount) || 0,
        velocity_1h: parseFloat(sarForm.velocity_1h) || 0,
        timestamp: new Date().toISOString(),
      }),
    });
    setSarResult(data);
    setLoadingSar(false);
    pollStats();
  };

  // Pathway wraps results as [{result: {...}}] via the rest_connector
  const unwrap = (d) => {
    if (!d) return d;
    if (Array.isArray(d) && d[0]) return d[0].result ?? d[0];
    return d.result ?? d;
  };
  const q = unwrap(queryResult);
  const sar = unwrap(sarResult);

  return (
    <div style={{ display: 'flex', flexDirection: 'column', gap: 16 }}>
      {/* A5 Compliance RAG */}
      <div className="panel-box">
        <div className="panel-header">
          <div className="panel-title">
            <Gavel size={14} style={{ display: 'inline', marginRight: 6 }} />
            A5 — Compliance RAG
          </div>
          <span className="panel-tag">
            {a5Stats && !a5Stats.error
              ? `${a5Stats.docs_loaded ?? 0} DOCS · ${a5Stats.total_queries ?? 0} QUERIES`
              : 'UNREACHABLE'}
          </span>
        </div>

        <div style={{ display: 'flex', gap: 10, marginBottom: 12 }}>
          <input
            type="text"
            className="mono"
            value={query}
            onChange={(e) => setQuery(e.target.value)}
            placeholder="Compliance question..."
            style={{ flex: 1, padding: '8px 10px', background: 'var(--panel2)', border: '1px solid var(--border)', color: 'var(--text)', borderRadius: 6 }}
          />
          <button className="btn" onClick={runQuery} disabled={loadingQuery}>
            <Search size={14} /> {loadingQuery ? 'Retrieving...' : 'Query Real Docs'}
          </button>
        </div>

        {queryResult && (
          queryResult.error ? (
            <div className="empty-note" style={{ color: 'var(--red)' }}>{queryResult.error}</div>
          ) : (
            <div>
              <div style={{ fontSize: 12, color: 'var(--muted)', marginBottom: 8 }}>
                Retrieved {q?.retrieved_count ?? 0} snippet(s)
              </div>
              {(q?.compliance_context || []).map((c, i) => (
                <div key={i} className="snippet-card">
                  <div className="snippet-score">Relevance: {c.relevance_score}</div>
                  <div>{c.snippet}</div>
                </div>
              ))}
            </div>
          )
        )}
      </div>

      {/* A8 SAR Drafter */}
      <div className="panel-box">
        <div className="panel-header">
          <div className="panel-title">
            <FileText size={14} style={{ display: 'inline', marginRight: 6 }} />
            A8 — SAR Narrative Drafter
          </div>
          <span className="panel-tag">
            {a8Stats && !a8Stats.error
              ? `${a8Stats.total_sars_drafted ?? 0} DRAFTED · LLM ${a8Stats.llm_configured ? 'CONFIGURED' : 'FALLBACK'}`
              : 'UNREACHABLE'}
          </span>
        </div>

        <div className="txn-grid-form" style={{ marginBottom: 12 }}>
          <div className="input-group">
            <label>Transaction ID</label>
            <input type="text" value={sarForm.transaction_id} onChange={(e) => setSarForm({ ...sarForm, transaction_id: e.target.value })} />
          </div>
          <div className="input-group">
            <label>Customer ID</label>
            <input type="text" value={sarForm.customer_id} onChange={(e) => setSarForm({ ...sarForm, customer_id: e.target.value })} />
          </div>
          <div className="input-group">
            <label>Amount ($)</label>
            <input type="number" value={sarForm.amount} onChange={(e) => setSarForm({ ...sarForm, amount: e.target.value })} />
          </div>
          <div className="input-group">
            <label>Merchant</label>
            <input type="text" value={sarForm.merchant} onChange={(e) => setSarForm({ ...sarForm, merchant: e.target.value })} />
          </div>
          <div className="input-group">
            <label>Freeze Reason</label>
            <input type="text" value={sarForm.freeze_reason} onChange={(e) => setSarForm({ ...sarForm, freeze_reason: e.target.value })} />
          </div>
          <div className="input-group">
            <label>Velocity (1h)</label>
            <input type="number" value={sarForm.velocity_1h} onChange={(e) => setSarForm({ ...sarForm, velocity_1h: e.target.value })} />
          </div>
        </div>

        <button className="btn" onClick={runSar} disabled={loadingSar || !sarForm.transaction_id}>
          <FileText size={14} /> {loadingSar ? 'Drafting via A5 + LLM...' : 'Draft Real SAR Narrative'}
        </button>

        {sarResult && (
          sarResult.error ? (
            <div className="empty-note" style={{ color: 'var(--red)', marginTop: 12 }}>{sarResult.error}</div>
          ) : (
            <pre className="code-output" style={{ marginTop: 12 }}>{sar?.sar_narrative || JSON.stringify(sar, null, 2)}</pre>
          )
        )}
      </div>
    </div>
  );
}
