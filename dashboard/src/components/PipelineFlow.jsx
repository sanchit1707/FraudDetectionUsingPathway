import React from 'react';
import { LogIn, Database, Layers, GitBranch, Cpu, ShieldCheck } from 'lucide-react';

// Static architecture description (what each stage does — this doesn't change)
// paired with real, live numbers pulled from gateway /metrics where available.
// Stages with no real per-stage metric show a plain description instead of an
// invented number (the original hardcoded "4.2k req/s" style values are gone).
export default function PipelineFlow({ metrics = {} }) {
  const processed = metrics.transactions_processed ?? 0;

  const stages = [
    { id: 'L0', title: 'L0: INGEST', subtitle: 'CSV / REST stream', icon: <LogIn size={16} />, color: 'var(--accent)' },
    { id: 'L1', title: 'L1: ENRICH', subtitle: 'Geo & user profile join', icon: <Database size={16} />, color: 'var(--cyan)' },
    { id: 'L2', title: 'L2: BITMASK', subtitle: '10m sliding window', icon: <Layers size={16} />, color: 'var(--purple)' },
    { id: 'L3', title: 'L3: RULES', subtitle: 'Velocity & pattern', icon: <GitBranch size={16} />, color: 'var(--amber)' },
    { id: 'L4', title: 'L4: XGB + HST', subtitle: 'ML fraud scorer', icon: <Cpu size={16} />, color: 'var(--green)' },
    { id: 'SCORE', title: 'FRAUD SCORE', subtitle: `${processed.toLocaleString()} scored total`, icon: <ShieldCheck size={16} />, color: 'var(--red)' },
  ];

  return (
    <div className="pipeline-card">
      <div className="pipeline-header">
        <div className="pipeline-title">
          <span className="dot-glow" style={{ color: 'var(--green)' }}></span>
          Pathway L0 → L4 Pipeline Execution Topology
        </div>
        <span className="panel-tag">REAL-TIME PATHWAY STREAMING ENGINE</span>
      </div>

      <div className="pipeline-flow">
        {stages.map((stage, idx) => (
          <React.Fragment key={stage.id}>
            <div className="stage-node">
              <div className="stage-top">
                <div className="stage-icon" style={{ color: stage.color, background: `${stage.color}15` }}>
                  {stage.icon}
                </div>
                <span className="stage-name">{stage.id}</span>
              </div>
              <div style={{ fontSize: '12px', fontWeight: 700, marginTop: 4 }}>
                {stage.title}
              </div>
              <div className="stage-meta" style={{ color: stage.color }}>
                {stage.subtitle}
              </div>
            </div>
            {idx < stages.length - 1 && <div className="stage-connector"></div>}
          </React.Fragment>
        ))}
      </div>
    </div>
  );
}
