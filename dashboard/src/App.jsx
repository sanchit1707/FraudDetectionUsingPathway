import React, { useState, useEffect, useCallback, useRef } from 'react';
import Sidebar from './components/Sidebar';
import Header from './components/Header';
import PipelineFlow from './components/PipelineFlow';
import StatCards from './components/StatCards';
import LiveStreamTable from './components/LiveStreamTable';
import FraudGaugeChart from './components/FraudGaugeChart';
import Workbench from './components/Workbench';
import OrchestratorPanel from './components/OrchestratorPanel';
import WatchdogPanel from './components/WatchdogPanel';
import CompliancePanel from './components/CompliancePanel';
import DriftMonitorPanel from './components/DriftMonitorPanel';
import FeedbackLoopPanel from './components/FeedbackLoopPanel';
import SettingsPanel from './components/SettingsPanel';
import { loadConfig, saveConfigValue, safeFetch } from './config';

export default function App() {
  const [config, setConfig] = useState(() => loadConfig());
  const [autoRefresh, setAutoRefresh] = useState(true);
  const [activeView, setActiveView] = useState('dashboard');

  const [metrics, setMetrics] = useState({});
  const [streamEvents, setStreamEvents] = useState([]);
  const [dlqEntries, setDlqEntries] = useState([]);
  const [bdhSessions, setBdhSessions] = useState({});
  const [masterStatus, setMasterStatus] = useState(true);
  const [selectedTxn, setSelectedTxn] = useState(null);
  const [throughput, setThroughput] = useState(0); // real, derived from delta over time

  const prevCountRef = useRef(null);
  const prevTimeRef = useRef(null);

  const setConfigValue = (key, value) => {
    setConfig((c) => ({ ...c, [key]: value }));
    saveConfigValue(key, value);
  };

  const pollAll = useCallback(async () => {
    const gwUrl = config.gwUrl.replace(/\/+$/, '');

    // Poll Metrics (real gateway counters)
    const metricsData = await safeFetch(`${gwUrl}/metrics`);
    if (!metricsData.error) {
      setMetrics(metricsData);
      setMasterStatus(true);

      // Derive real throughput from the change in transactions_processed
      // over wall-clock time between polls — never fabricated.
      const now = Date.now();
      const count = metricsData.transactions_processed ?? 0;
      if (prevCountRef.current != null && prevTimeRef.current != null) {
        const dCount = count - prevCountRef.current;
        const dSec = (now - prevTimeRef.current) / 1000;
        if (dSec > 0 && dCount >= 0) {
          setThroughput(Math.round((dCount / dSec) * 10) / 10);
        }
      }
      prevCountRef.current = count;
      prevTimeRef.current = now;
    } else {
      setMasterStatus(false);
    }

    // Poll Recent Stream Events (real)
    const streamData = await safeFetch(`${gwUrl}/stream/recent?n=200`);
    if (streamData.events && Array.isArray(streamData.events)) {
      const pipelineEvents = streamData.events.filter(e => e.event_type === 'pipeline_result').slice(0, 30);
      setStreamEvents(pipelineEvents);
      if (!selectedTxn && pipelineEvents.length > 0) {
        const latest = pipelineEvents[0];
        const payload = latest.payload || {};
        setSelectedTxn({
          txnId: latest.txn_id || payload.txn_id,
          accountId: payload.cust_token || payload.account_id,
          amount: payload.amount ?? payload.features?.amount,
          score: payload.final_score ?? payload.fraud_score,
          action: payload.final_action || payload.verdict,
          payload,
        });
      }
    }

    // Poll DLQ (real)
    const dlqData = await safeFetch(`${gwUrl}/dlq?n=20`);
    if (dlqData.entries) {
      setDlqEntries(dlqData.entries);
    }

    // Poll BDH Sessions (real)
    const bdhData = await safeFetch(`${config.bdhUrl.replace(/\/+$/, '')}/sessions`);
    setBdhSessions(bdhData);
  }, [config.gwUrl, config.bdhUrl, selectedTxn]);

  useEffect(() => {
    pollAll();
    const interval = setInterval(() => {
      if (autoRefresh) pollAll();
    }, 3500);
    return () => clearInterval(interval);
  }, [pollAll, autoRefresh]);

  const handleRetryDlq = async (dlqId) => {
    const gwUrl = config.gwUrl.replace(/\/+$/, '');
    await safeFetch(`${gwUrl}/dlq/retry?dlq_id=${encodeURIComponent(dlqId)}`, { method: 'POST' });
    pollAll();
  };

  const handleTxnSubmitted = (result) => {
    if (result && result.txn_id) {
      setSelectedTxn({
        txnId: result.txn_id,
        accountId: result.account_id,
        amount: result.amount,
        score: result.final_score,
        action: result.verdict || result.final_action,
        payload: result,
      });
    }
    pollAll();
  };

  return (
    <div className="app-shell">
      <Sidebar activeView={activeView} onNavigate={setActiveView} />

      <div className="app-main">
        <Header
          throughput={throughput}
          autoRefresh={autoRefresh}
          setAutoRefresh={setAutoRefresh}
          onRefreshNow={pollAll}
          masterStatus={masterStatus}
        />

        <main className="dashboard-body">
          {activeView === 'dashboard' && (
            <>
              <PipelineFlow metrics={metrics} />
              <StatCards metrics={metrics} />
              <div className="content-grid">
                <LiveStreamTable
                  events={streamEvents}
                  onSelectTxn={(txn) => setSelectedTxn(txn)}
                />
                <FraudGaugeChart selectedTxn={selectedTxn} metrics={metrics} />
              </div>
              <Workbench
                gwUrl={config.gwUrl}
                groqKey={config.groqKey}
                onTxnSubmitted={handleTxnSubmitted}
                dlqEntries={dlqEntries}
                onRetryDlq={handleRetryDlq}
                agent6Url={config.agent6Url}
              />
            </>
          )}

          {activeView === 'live-stream' && (
            <div className="content-grid single">
              <LiveStreamTable
                events={streamEvents}
                onSelectTxn={(txn) => setSelectedTxn(txn)}
                expanded
              />
            </div>
          )}

          {activeView === 'orchestrator' && (
            <OrchestratorPanel selectedTxn={selectedTxn} />
          )}

          {activeView === 'watchdog' && (
            <WatchdogPanel bdhSessions={bdhSessions} bdhUrl={config.bdhUrl} />
          )}

          {activeView === 'compliance' && (
            <CompliancePanel a5Url={config.a5Url} a8Url={config.a8Url} selectedTxn={selectedTxn} />
          )}

          {activeView === 'drift' && (
            <DriftMonitorPanel a6bUrl={config.a6bUrl} selectedTxn={selectedTxn} />
          )}

          {activeView === 'feedback' && (
            <FeedbackLoopPanel a10Url={config.a10Url} selectedTxn={selectedTxn} />
          )}

          {activeView === 'settings' && (
            <SettingsPanel config={config} setConfigValue={setConfigValue} />
          )}
        </main>
      </div>
    </div>
  );
}
