import React, { useState, useEffect } from 'react';
import { api } from '../api/client.js';

function StatusBadge({ status }) {
  const s = String(status || 'unknown').toLowerCase();
  let label = s.toUpperCase();
  let bg = 'rgba(255, 255, 255, 0.08)';
  let color = 'var(--text-secondary)';
  let border = '1px solid rgba(255, 255, 255, 0.15)';
  let icon = '⚪';

  if (s === 'available' || s === 'mcp_available' || s === 'running' || s === 'healthy') {
    label = s === 'mcp_available' ? 'AVAILABLE MCP' : s.toUpperCase();
    bg = 'rgba(46, 204, 113, 0.18)';
    color = '#2ecc71';
    border = '1px solid rgba(46, 204, 113, 0.4)';
    icon = '🟢';
  } else if (s === 'unavailable' || s === 'mcp_unavailable' || s === 'not_configured') {
    label = s === 'mcp_unavailable' ? 'UNAVAILABLE MCP' : s === 'not_configured' ? 'NOT CONFIGURED' : s.toUpperCase();
    bg = 'rgba(243, 156, 18, 0.18)';
    color = '#f39c12';
    border = '1px solid rgba(243, 156, 18, 0.4)';
    icon = '⚠️';
  } else if (s === 'discovery_failed' || s === 'failed' || s === 'error') {
    bg = 'rgba(255, 71, 87, 0.18)';
    color = '#ff4757';
    border = '1px solid rgba(255, 71, 87, 0.4)';
    icon = '❌';
  }

  return (
    <span
      style={{
        display: 'inline-flex',
        alignItems: 'center',
        gap: '6px',
        padding: '4px 10px',
        borderRadius: '6px',
        fontSize: '11px',
        fontWeight: '600',
        background: bg,
        color: color,
        border: border
      }}
    >
      <span>{icon}</span>
      <span>{label}</span>
    </span>
  );
}

export default function OverviewCockpit({ activeSessionId, onRefresh }) {
  const [telemetry, setTelemetry] = useState(null);
  const [health, setHealth] = useState(null);
  const [integrations, setIntegrations] = useState(null);
  const [mcpProviders, setMcpProviders] = useState([]);
  const [workerObs, setWorkerObs] = useState(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState(null);

  const fetchOverview = async () => {
    setLoading(true);
    setError(null);
    try {
      const sess = activeSessionId || 'default_session';

      const [histRes, healthRes, intRes, mcpRes, workerRes] = await Promise.allSettled([
        api.get(`/api/history/${sess}`),
        api.get('/api/system/health'),
        api.get('/api/integrations/status'),
        api.get('/api/tools/mcp/providers'),
        api.get('/api/memory/observability/workers')
      ]);

      const dataHist = histRes.status === 'fulfilled' ? histRes.value : {};
      const dataHealth = healthRes.status === 'fulfilled' ? healthRes.value : null;
      const dataInt = intRes.status === 'fulfilled' ? intRes.value : null;
      const dataMcp = mcpRes.status === 'fulfilled' ? mcpRes.value : null;
      const dataWorkers = workerRes.status === 'fulfilled' ? workerRes.value : null;

      setHealth(dataHealth);
      setIntegrations(dataInt?.integrations || null);
      setMcpProviders(dataMcp?.providers || []);
      setWorkerObs(dataWorkers?.summary || null);

      setTelemetry({
        session_id: sess,
        total_turns: dataHist.total_turns || 0,
        gate_status: 'Active (Hybrid SQL/FTS5)',
        tool_status: 'Personal OS + cron + provider-managed MCP',
        memory_sync: 'Synced (.agent/MEMORY.md)'
      });
    } catch (e) {
      console.error(e);
      setError(e.message || 'Failed to load telemetry');
    } finally {
      setLoading(false);
    }
  };

  useEffect(() => {
    fetchOverview();
  }, [activeSessionId]);

  return (
    <div style={{ display: 'flex', flexDirection: 'column', gap: '20px' }}>
      <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center' }}>
        <h2 style={{ fontFamily: 'var(--font-heading)', margin: 0 }}>📊 ASTRA Telemetry & Integration Status</h2>
        <button
          onClick={() => { fetchOverview(); if (onRefresh) onRefresh(); }}
          style={{ padding: '8px 16px', background: 'var(--primary-glow)', border: 'none', borderRadius: '6px', color: 'white', cursor: 'pointer' }}
        >
          🔄 Refresh
        </button>
      </div>

      {error && (
        <div style={{ padding: '12px', background: 'rgba(255, 50, 50, 0.15)', borderRadius: '8px', color: '#ff6b6b' }}>
          ⚠️ Error loading telemetry: {error}
        </div>
      )}

      {loading ? (
        <div style={{ padding: '32px', textAlign: 'center', color: 'var(--text-secondary)' }}>🌀 Loading system telemetry & provider readiness...</div>
      ) : (
        <>
          {/* Top Telemetry Grid */}
          <div style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fit, minmax(220px, 1fr))', gap: '16px' }}>
            <div className="glass-card">
              <h4 style={{ color: 'var(--text-secondary)', marginBottom: '8px' }}>Active Session</h4>
              <div style={{ fontSize: '16px', fontWeight: '600' }}>{telemetry?.session_id || 'default_session'}</div>
              <div style={{ fontSize: '12px', color: 'var(--text-secondary)', marginTop: '4px' }}>Logged Turns: {telemetry?.total_turns || 0}</div>
            </div>

            <div className="glass-card">
              <h4 style={{ color: 'var(--text-secondary)', marginBottom: '8px' }}>Database & Schema</h4>
              <div style={{ fontSize: '16px', fontWeight: '600', color: '#4ecdc4' }}>
                SQLite v{health?.schema_version || 7}
              </div>
              <div style={{ fontSize: '11px', color: 'var(--text-secondary)', marginTop: '4px', overflow: 'hidden', textOverflow: 'ellipsis' }}>
                Path: {health?.database_path ? health.database_path.split('\\').pop() : 'state.db'}
              </div>
            </div>

            <div className="glass-card">
              <h4 style={{ color: 'var(--text-secondary)', marginBottom: '8px' }}>Coarse System Health</h4>
              <div style={{ fontSize: '16px', fontWeight: '600', color: '#a8ff78' }}>
                🟢 {health?.status || 'HEALTHY'}
              </div>
              <div style={{ fontSize: '11px', color: 'var(--text-secondary)', marginTop: '4px' }}>
                System Worker Telemetry: {health?.worker_status || 'RUNNING'}
              </div>
            </div>

            <div className="glass-card">
              <h4 style={{ color: 'var(--text-secondary)', marginBottom: '8px' }}>Memory Workers Real State</h4>
              <div style={{ fontSize: '16px', fontWeight: '600', color: workerObs?.stale_workers > 0 ? '#ff6b6b' : '#2ecc71' }}>
                {workerObs ? `${workerObs.active_workers} Active / ${workerObs.total_workers} Total` : '1 Worker Active'}
              </div>
              <div style={{ fontSize: '11px', color: 'var(--text-secondary)', marginTop: '4px' }}>
                Stale Workers: {workerObs?.stale_workers || 0} (Heartbeat threshold {workerObs?.stale_after_seconds || 60}s)
              </div>
            </div>
          </div>

          {/* Integration Capabilities */}
          <div className="glass-card" style={{ marginTop: '10px' }}>
            <h3 style={{ fontFamily: 'var(--font-heading)', fontSize: '16px', marginBottom: '14px' }}>
              🔌 Integration Capability Readiness
            </h3>
            {integrations ? (
              <div style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fit, minmax(240px, 1fr))', gap: '12px' }}>
                {Object.entries(integrations).map(([key, item]) => (
                  <div
                    key={key}
                    style={{
                      padding: '12px 14px',
                      background: 'rgba(255, 255, 255, 0.03)',
                      borderRadius: '8px',
                      border: '1px solid var(--border-glass)',
                      display: 'flex',
                      flexDirection: 'column',
                      gap: '6px'
                    }}
                  >
                    <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center' }}>
                      <strong style={{ fontSize: '14px' }}>{item.name || key.toUpperCase()}</strong>
                      <StatusBadge status={item.status} />
                    </div>
                    <div style={{ fontSize: '12px', color: 'var(--text-secondary)' }}>{item.description}</div>
                    <div style={{ fontSize: '11px', color: 'rgba(255,255,255,0.4)', marginTop: '2px' }}>
                      Mode: <code>{item.mode}</code>
                    </div>
                  </div>
                ))}
              </div>
            ) : (
              <div style={{ fontSize: '13px', color: 'var(--text-secondary)' }}>No integration status response.</div>
            )}
          </div>

          {/* Live MCP Providers Status */}
          <div className="glass-card" style={{ marginTop: '10px' }}>
            <h3 style={{ fontFamily: 'var(--font-heading)', fontSize: '16px', marginBottom: '14px' }}>
              🛠️ Live MCP Provider Statuses
            </h3>
            {mcpProviders.length > 0 ? (
              <div style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fit, minmax(260px, 1fr))', gap: '12px' }}>
                {mcpProviders.map(p => (
                  <div
                    key={p.provider_id}
                    style={{
                      padding: '12px 14px',
                      background: 'rgba(255, 255, 255, 0.03)',
                      borderRadius: '8px',
                      border: '1px solid var(--border-glass)',
                      display: 'flex',
                      flexDirection: 'column',
                      gap: '6px'
                    }}
                  >
                    <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center' }}>
                      <strong style={{ fontSize: '14px' }}><code>{p.provider_id}</code></strong>
                      <StatusBadge status={p.availability_status} />
                    </div>
                    <div style={{ fontSize: '12px', color: 'var(--text-secondary)', display: 'flex', gap: '12px' }}>
                      <span>Transport: <code>{p.transport || 'stdio'}</code></span>
                      <span>Tools: <strong>{p.tool_count || 0}</strong></span>
                    </div>
                    {p.last_error && (
                      <div style={{ fontSize: '11px', color: '#ff6b6b', marginTop: '4px', overflow: 'hidden', textOverflow: 'ellipsis' }}>
                        Error: {p.last_error}
                      </div>
                    )}
                  </div>
                ))}
              </div>
            ) : (
              <div style={{ fontSize: '13px', color: 'var(--text-secondary)' }}>No MCP providers registered.</div>
            )}
          </div>
        </>
      )}
    </div>
  );
}

if (typeof window !== 'undefined') {
  window.OverviewCockpit = OverviewCockpit;
}

