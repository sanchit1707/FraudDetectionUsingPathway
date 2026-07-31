import React from 'react';
import { Activity, ShieldAlert, AlertTriangle, Cpu, Clock, AlertCircle } from 'lucide-react';

export default function StatCards({ metrics = {} }) {
  const cards = [
    {
      label: 'TOTAL MONITORED',
      value: metrics.transactions_processed ?? 0,
      colorClass: 'blue',
      icon: <Activity size={20} style={{ color: 'var(--accent)' }} />,
    },
    {
      label: 'UNDER REVIEW',
      value: metrics.held ?? 0,
      colorClass: 'amber',
      icon: <AlertTriangle size={20} style={{ color: 'var(--amber)' }} />,
    },
    {
      label: 'HIGH RISK BLOCKED',
      value: metrics.blocked ?? 0,
      colorClass: 'red',
      icon: <ShieldAlert size={20} style={{ color: 'var(--red)' }} />,
    },
    {
      label: 'LLM ESCALATIONS',
      value: metrics.escalated_to_llm ?? 0,
      colorClass: 'purple',
      icon: <Cpu size={20} style={{ color: 'var(--purple)' }} />,
    },
    {
      label: 'APPROVED',
      value: metrics.approved ?? 0,
      colorClass: 'green',
      icon: <Activity size={20} style={{ color: 'var(--green)' }} />,
    },
    {
      label: 'DLQ / ERRORS',
      value: metrics.dlq_count ?? metrics.errors ?? 0,
      colorClass: metrics.dlq_count ? 'amber' : '',
      icon: <AlertCircle size={20} style={{ color: metrics.dlq_count ? 'var(--amber)' : 'var(--muted)' }} />,
    },
  ];

  return (
    <div className="stats-grid">
      {cards.map((card, idx) => (
        <div className="stat-card" key={idx}>
          <div className="stat-info">
            <div className="label">{card.label}</div>
            <div className={`value ${card.colorClass}`}>
              {card.value.toLocaleString()}
            </div>
          </div>
          <div className="stat-icon-wrap">{card.icon}</div>
        </div>
      ))}
    </div>
  );
}
