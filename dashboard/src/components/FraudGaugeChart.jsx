import React from 'react';
import { Chart as ChartJS, ArcElement, Tooltip, Legend } from 'chart.js';
import { Doughnut } from 'react-chartjs-2';

ChartJS.register(ArcElement, Tooltip, Legend);

export default function FraudGaugeChart({ selectedTxn, metrics = {} }) {
  const hasTxn = Boolean(selectedTxn);
  const score = hasTxn ? (selectedTxn.score ?? 0) : null;
  const account = hasTxn ? selectedTxn.accountId : null;
  const amount = hasTxn ? selectedTxn.amount : null;
  const threats = selectedTxn?.payload?.active_threats || null;
  const action = hasTxn ? (selectedTxn.action || null) : null;
  const displayScore = score ?? 0;

  // SVG Gauge Calculations
  const radius = 75;
  const strokeWidth = 14;
  const cx = 100;
  const cy = 95;

  // Calculate needle angle (score 0 = -180deg, 1 = 0deg)
  const angleDeg = -180 + displayScore * 180;
  const angleRad = (angleDeg * Math.PI) / 180;
  const needleLen = 55;
  const needleX = cx + needleLen * Math.cos(angleRad);
  const needleY = cy + needleLen * Math.sin(angleRad);

  const getScoreColor = (val) => {
    if (val >= 0.75) return 'var(--red)';
    if (val >= 0.40) return 'var(--amber)';
    return 'var(--green)';
  };

  // Donut chart data for Action Distribution — use ?? so real zeros
  // are never silently replaced by a fake fallback number.
  const approved = metrics.approved ?? 0;
  const held = metrics.held ?? 0;
  const blocked = metrics.blocked ?? 0;

  const donutData = {
    labels: ['Approved', 'Held / Review', 'Blocked'],
    datasets: [
      {
        data: [approved, held, blocked],
        backgroundColor: ['#3ecf8e', '#f5a623', '#f5566a'],
        borderColor: '#12161f',
        borderWidth: 2,
      },
    ],
  };

  const donutOptions = {
    responsive: true,
    maintainAspectRatio: false,
    plugins: {
      legend: {
        position: 'right',
        labels: {
          color: '#e6e9f0',
          font: { family: 'Inter', size: 11 },
          boxWidth: 12,
        },
      },
    },
    cutout: '70%',
  };

  return (
    <div style={{ display: 'flex', flexDirection: 'column', gap: '20px' }}>
      {/* Latest Fraud Score Gauge Panel */}
      <div className="panel-box">
        <div className="panel-header">
          <div className="panel-title">LATEST FRAUD SCORE</div>
          <span className="panel-tag">XGB + HST ENSEMBLE</span>
        </div>

        <div className="gauge-box">
          <div className="gauge-svg-wrap">
            <svg viewBox="0 0 200 110" width="100%" height="100%">
              {/* Background Arc Tracks */}
              {/* Green Arc (Safe) */}
              <path
                d="M 25,95 A 75 75 0 0 1 75,27"
                fill="none"
                stroke="#3ecf8e"
                strokeWidth={strokeWidth}
                strokeLinecap="round"
                opacity="0.85"
              />
              {/* Amber Arc (Review) */}
              <path
                d="M 78,25 A 75 75 0 0 1 122,25"
                fill="none"
                stroke="#f5a623"
                strokeWidth={strokeWidth}
                opacity="0.85"
              />
              {/* Red Arc (High Risk) */}
              <path
                d="M 125,27 A 75 75 0 0 1 175,95"
                fill="none"
                stroke="#f5566a"
                strokeWidth={strokeWidth}
                strokeLinecap="round"
                opacity="0.85"
              />

              {/* Center Needle Indicator */}
              <line
                x1={cx}
                y1={cy}
                x2={needleX}
                y2={needleY}
                stroke={hasTxn ? getScoreColor(displayScore) : 'var(--muted)'}
                strokeWidth="3.5"
                strokeLinecap="round"
              />
              <circle cx={cx} cy={cy} r="6" fill={hasTxn ? getScoreColor(displayScore) : 'var(--muted)'} />
              <circle cx={cx} cy={cy} r="3" fill="#12161f" />
            </svg>

            <div className="gauge-val-text">
              <div className="gauge-val-number" style={{ color: hasTxn ? getScoreColor(displayScore) : 'var(--muted)' }}>
                {hasTxn ? displayScore.toFixed(3) : '—'}
              </div>
              <div className="gauge-val-sub">FRAUD SCORE</div>
              <div style={{ fontSize: '10px', color: 'var(--muted)', marginTop: 2 }}>
                Escalation band 0.40–0.75
              </div>
            </div>
          </div>
        </div>

        <div className="gauge-details">
          <div>
            <span>Account:</span> <strong className="mono">{account ?? '—'}</strong>
          </div>
          <div>
            <span>Amount:</span> <strong className="mono">{amount != null ? `$${amount}` : '—'}</strong>
          </div>
          <div>
            <span>Threats:</span> <strong className="mono">{threats ?? '—'}</strong>
          </div>
          <div>
            <span>Action:</span>{' '}
            <strong
              style={{
                color:
                  action === 'decline' || action === 'BLOCK'
                    ? 'var(--red)'
                    : action === 'hold' || action === 'FLAG'
                    ? 'var(--amber)'
                    : action
                    ? 'var(--green)'
                    : 'var(--muted)',
              }}
            >
              {action ? action.toUpperCase() : 'NO TRANSACTION YET'}
            </strong>
          </div>
        </div>
      </div>

      {/* Action Distribution Donut Chart Panel */}
      <div className="panel-box">
        <div className="panel-header">
          <div className="panel-title">ACTION DISTRIBUTION</div>
          <span className="panel-tag">LIVE VERDICTS</span>
        </div>
        <div style={{ height: '140px', position: 'relative' }}>
          <Doughnut data={donutData} options={donutOptions} />
        </div>
      </div>
    </div>
  );
}
