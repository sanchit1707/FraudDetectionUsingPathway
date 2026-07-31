import React from 'react';
import { Activity } from 'lucide-react';

export default function LiveStreamTable({ events = [], onSelectTxn }) {
  const getBadgeClass = (score, action) => {
    if (action === 'decline' || score >= 0.75) return 'HIGH_RISK';
    if (action === 'hold' || (score >= 0.40 && score < 0.75)) return 'REVIEW';
    return 'SAFE';
  };

  const formatCurrency = (amt) => {
    if (!amt && amt !== 0) return '—';
    return new Intl.NumberFormat('en-US', { style: 'currency', currency: 'USD' }).format(amt);
  };

  return (
    <div className="panel-box" style={{ flex: 1 }}>
      <div className="panel-header">
        <div className="panel-title">
          <span className="dot-glow" style={{ color: 'var(--accent)' }}></span>
          LIVE INGEST STREAM
        </div>
        <span className="panel-tag">BUFFER: {events.length} RECORDS</span>
      </div>

      <div className="table-wrap">
        <table className="live-table">
          <thead>
            <tr>
              <th>TXN_ID</th>
              <th>ACCOUNT_ID</th>
              <th>AMOUNT</th>
              <th>SCORE</th>
              <th>TIER</th>
            </tr>
          </thead>
          <tbody>
            {events.length === 0 ? (
              <tr>
                <td colSpan={5} style={{ textAlign: 'center', padding: '30px', color: 'var(--muted)' }}>
                  No recent events in stream. Submit a transaction or start Pathway replay generator.
                </td>
              </tr>
            ) : (
              events.map((ev, idx) => {
                const payload = ev.payload || {};
                const txnId = ev.txn_id || payload.txn_id || null;
                const accountId = payload.cust_token || payload.account_id || null;
                const amount = payload.amount ?? payload.features?.amount ?? null;
                const score = payload.final_score ?? payload.fraud_score ?? null;
                const action = payload.final_action || payload.verdict || null;
                const badgeType = score != null ? getBadgeClass(score, action) : null;

                return (
                  <tr
                    key={idx}
                    onClick={() => onSelectTxn && onSelectTxn({ txnId, accountId, amount, score, action, payload })}
                    style={{ cursor: 'pointer' }}
                  >
                    <td className="mono" style={{ fontWeight: 600, color: 'var(--accent)' }}>
                      {txnId ?? '—'}
                    </td>
                    <td className="mono">{accountId ?? '—'}</td>
                    <td className="mono" style={{ fontWeight: 600 }}>
                      {amount != null ? formatCurrency(amount) : '—'}
                    </td>
                    <td className="mono" style={{ fontWeight: 700 }}>
                      {typeof score === 'number' ? score.toFixed(3) : '—'}
                    </td>
                    <td>
                      {badgeType ? (
                        <span className={`tier-badge ${badgeType}`}>
                          <span
                            className="dot-glow"
                            style={{
                              color: badgeType === 'SAFE' ? 'var(--green)' : badgeType === 'HIGH_RISK' ? 'var(--red)' : 'var(--amber)',
                            }}
                          ></span>
                          {badgeType === 'SAFE' ? 'SAFE' : badgeType === 'HIGH_RISK' ? 'HIGH RISK' : 'REVIEW'}
                        </span>
                      ) : (
                        <span style={{ color: 'var(--muted)' }}>—</span>
                      )}
                    </td>
                  </tr>
                );
              })
            )}
          </tbody>
        </table>
      </div>
    </div>
  );
}
