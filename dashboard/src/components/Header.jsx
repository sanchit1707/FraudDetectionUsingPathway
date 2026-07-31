import React from 'react';
import { Play, Pause, RefreshCw } from 'lucide-react';

export default function Header({
  throughput = 0,
  autoRefresh,
  setAutoRefresh,
  onRefreshNow,
  masterStatus,
}) {
  return (
    <header>
      <div className="header-brand">
        <div className="brand-pills">
          <span className="status-pill healthy">
            <span className="dot-glow" style={{ color: masterStatus ? 'var(--green)' : 'var(--red)' }}></span>
            PIPELINE {masterStatus ? 'HEALTHY' : 'DEGRADED'}
          </span>
          <span className="status-pill active">
            THROUGHPUT: {throughput.toLocaleString()} TXNS/SEC
          </span>
          <span className="status-pill active">
            <span className="dot-glow" style={{ color: 'var(--accent)' }}></span>
            {masterStatus ? 'WS: ACTIVE' : 'WS: DOWN'}
          </span>
          <span className="status-pill prod">DOCKER · PROD</span>
        </div>
      </div>

      <div className="conn-bar">
        <button
          className={`btn ${autoRefresh ? 'ghost' : ''}`}
          onClick={() => setAutoRefresh(!autoRefresh)}
          title={autoRefresh ? 'Pause Polling' : 'Resume Polling'}
        >
          {autoRefresh ? <Pause size={14} /> : <Play size={14} />}
          {autoRefresh ? 'Pause' : 'Resume'}
        </button>
        <button className="btn ghost" onClick={onRefreshNow} title="Refresh Now">
          <RefreshCw size={14} />
        </button>
      </div>
    </header>
  );
}
