import React from 'react';
import { Server, Key } from 'lucide-react';

const FIELDS = [
  { key: 'gwUrl', label: 'Gateway (L0-L4 + LangGraph)', placeholder: 'http://localhost:8080' },
  { key: 'bdhUrl', label: 'BDH Watchdog', placeholder: 'http://localhost:8090' },
  { key: 'agent6Url', label: 'Agent 6 (Execution)', placeholder: 'http://localhost:8000' },
  { key: 'a5Url', label: 'A5 Compliance RAG (sidecar)', placeholder: 'http://localhost:8531' },
  { key: 'a6bUrl', label: 'A6b Drift Detector (sidecar)', placeholder: 'http://localhost:8532' },
  { key: 'a8Url', label: 'A8 SAR Drafter (sidecar)', placeholder: 'http://localhost:8533' },
  { key: 'a10Url', label: 'A10 Feedback Loop (sidecar)', placeholder: 'http://localhost:8535' },
];

export default function SettingsPanel({ config, setConfigValue }) {
  return (
    <div className="panel-box">
      <div className="panel-header">
        <div className="panel-title">
          <Server size={14} style={{ display: 'inline', marginRight: 6 }} />
          Service Endpoints
        </div>
        <span className="panel-tag">PERSISTED LOCALLY</span>
      </div>

      <div className="settings-grid">
        {FIELDS.map((f) => (
          <div className="input-group" key={f.key}>
            <label>{f.label}</label>
            <input
              type="text"
              value={config[f.key]}
              onChange={(e) => setConfigValue(f.key, e.target.value)}
              placeholder={f.placeholder}
            />
          </div>
        ))}

        <div className="input-group">
          <label><Key size={10} style={{ display: 'inline', marginRight: 4 }} />Groq API Key (LLM)</label>
          <input
            type="password"
            value={config.groqKey}
            onChange={(e) => setConfigValue('groqKey', e.target.value)}
            placeholder="gsk_..."
          />
        </div>
      </div>

      <p style={{ fontSize: 12, color: 'var(--muted)', marginTop: 16, lineHeight: 1.6 }}>
        The A5 / A6b / A8 / A10 ports above point at the sidecar bridge each agent runs
        (see docker-compose.yml), which adds CORS + a real <code>/stats</code> endpoint
        on top of the agent's actual Pathway route. If you change the ports in
        docker-compose, update them here to match.
      </p>
    </div>
  );
}
