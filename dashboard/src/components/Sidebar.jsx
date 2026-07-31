import React from 'react';
import {
  LayoutDashboard,
  Radio,
  GitBranch,
  Eye,
  Gavel,
  LineChart,
  RefreshCcw,
  Settings,
  ShieldHalf,
} from 'lucide-react';

const NAV_ITEMS = [
  { id: 'dashboard', label: 'Dashboard', icon: LayoutDashboard },
  { id: 'live-stream', label: 'Live Stream', icon: Radio },
  { id: 'orchestrator', label: 'Orchestrator', icon: GitBranch },
  { id: 'watchdog', label: 'Watchdog (BDH)', icon: Eye },
  { id: 'compliance', label: 'Compliance (A5 / A8)', icon: Gavel },
  { id: 'drift', label: 'Drift Monitor (A6b)', icon: LineChart },
  { id: 'feedback', label: 'Feedback Loop (A10)', icon: RefreshCcw },
];

export default function Sidebar({ activeView, onNavigate }) {
  return (
    <aside className="app-sidebar">
      <div className="sidebar-logo">
        <ShieldHalf size={22} />
      </div>
      <nav className="sidebar-nav">
        {NAV_ITEMS.map((item) => {
          const Icon = item.icon;
          const active = activeView === item.id;
          return (
            <button
              key={item.id}
              className={`sidebar-link ${active ? 'active' : ''}`}
              onClick={() => onNavigate(item.id)}
              title={item.label}
            >
              <Icon size={19} />
              <span className="sidebar-tooltip">{item.label}</span>
            </button>
          );
        })}
      </nav>
      <div className="sidebar-bottom">
        <button
          className={`sidebar-link ${activeView === 'settings' ? 'active' : ''}`}
          onClick={() => onNavigate('settings')}
          title="Settings"
        >
          <Settings size={19} />
          <span className="sidebar-tooltip">Settings</span>
        </button>
      </div>
    </aside>
  );
}
