import React, { useEffect, useState } from 'react';
import { api } from '../api/client.js';

function Badge({ value }) {
  const text = String(value || 'unknown');
  const good = ['available', 'OK', 'SUCCEEDED', 'no_approval_needed'].includes(text);
  const warn = ['unavailable', 'approval_required', 'blocked', 'FAILED', 'FAILED_TERMINAL'].some(marker => text.includes(marker));
  return (
    <span
      className="retrieval-badge"
      style={{
        background: good ? 'rgba(46, 204, 113, 0.18)' : warn ? 'rgba(255, 99, 99, 0.18)' : 'rgba(255,255,255,0.06)',
        color: good ? '#2ecc71' : warn ? '#ff6b6b' : 'var(--text-secondary)'
      }}
    >
      {text}
    </span>
  );
}

function Empty({ children }) {
  return <div style={{ color: 'var(--text-secondary)', padding: '12px 0' }}>{children}</div>;
}

export default function ToolsOpsCockpit() {
  const [overview, setOverview] = useState(null);
  const [providers, setProviders] = useState([]);
  const [personalStatus, setPersonalStatus] = useState(null);
  const [personalActions, setPersonalActions] = useState([]);
  const [personalAudit, setPersonalAudit] = useState([]);
  const [cronSchedules, setCronSchedules] = useState([]);
  const [cronRuns, setCronRuns] = useState([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState(null);

  const load = async () => {
    setLoading(true);
    setError(null);
    try {
      const [
        overviewData,
        providersData,
        personalStatusData,
        personalActionsData,
        personalAuditData,
        schedulesData,
        runsData
      ] = await Promise.all([
        api.get('/api/tools/observability/overview'),
        api.get('/api/tools/mcp/providers'),
        api.get('/api/tools/personal-os/status'),
        api.get('/api/tools/personal-os/actions'),
        api.get('/api/tools/personal-os/audit'),
        api.get('/api/tools/cron/schedules'),
        api.get('/api/tools/cron/runs?limit=20')
      ]);

      setOverview(overviewData);
      setProviders(providersData.providers || []);
      setPersonalStatus(personalStatusData);
      setPersonalActions(personalActionsData.actions || []);
      setPersonalAudit(personalAuditData.audit_events || []);
      setCronSchedules(schedulesData.schedules || []);
      setCronRuns(runsData.runs || []);
    } catch (e) {
      setError(e.message || 'Failed to load Tools Ops');
    } finally {
      setLoading(false);
    }
  };

  useEffect(() => { load(); }, []);

  const calls = overview?.tool_calls?.tool_calls || [];
  const results = overview?.tool_results?.tool_results || [];
  const blocked = overview?.blocked?.blocked_attempts || [];
  const policyEntries = overview?.policy?.entries || [];

  return (
    <div style={{ display: 'flex', flexDirection: 'column', gap: '20px' }}>
      <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center' }}>
        <h2 style={{ fontFamily: 'var(--font-heading)', margin: 0 }}>Tools Ops</h2>
        <button onClick={load} style={{ padding: '8px 16px', background: 'var(--primary-glow)', border: 'none', borderRadius: '6px', color: 'white', cursor: 'pointer' }}>Refresh</button>
      </div>

      {error && <div style={{ padding: '12px', background: 'rgba(255, 50, 50, 0.15)', borderRadius: '8px', color: '#ff6b6b' }}>Error: {error}</div>}
      {loading ? <Empty>Loading tools observability...</Empty> : (
        <>
          <div style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fit, minmax(180px, 1fr))', gap: '12px' }}>
            <div className="glass-card"><h4>Registry</h4><strong>{overview?.status?.registry?.total_bindable_tools || 0}</strong><div>Bindable tools</div></div>
            <div className="glass-card"><h4>MCP Providers</h4><strong>{overview?.status?.providers?.available_providers || 0}/{overview?.status?.providers?.total_providers || 0}</strong><div>Available</div></div>
            <div className="glass-card"><h4>Cron</h4><strong>{overview?.cron?.schedule_counts?.total || 0}</strong><div>Schedules</div></div>
            <div className="glass-card"><h4>Blocked</h4><strong>{blocked.length}</strong><div>Recent attempts</div></div>
          </div>

          <div className="glass-card">
            <h3>MCP Provider Status</h3>
            {providers.length === 0 ? <Empty>No provider status available.</Empty> : providers.map(provider => (
              <div key={provider.provider_id} style={{ borderTop: '1px solid var(--border-glass)', padding: '10px 0', display: 'flex', justifyContent: 'space-between', gap: '12px', flexWrap: 'wrap' }}>
                <div>
                  <strong>{provider.display_name}</strong>
                  <div style={{ fontSize: '12px', color: 'var(--text-secondary)' }}>{provider.provider_id} | {provider.transport_type} | credentials: {provider.credential_status}</div>
                  {provider.last_error && <div style={{ fontSize: '12px', color: '#ff6b6b' }}>Last error: {provider.last_error}</div>}
                </div>
                <div style={{ display: 'flex', gap: '8px', alignItems: 'center' }}>
                  <Badge value={provider.availability_status} />
                  <Badge value={provider.discovery_status} />
                  <span>{provider.tool_count || 0} tools</span>
                </div>
              </div>
            ))}
          </div>

          <div className="glass-card">
            <h3>Personal OS</h3>
            <div style={{ display: 'flex', gap: '10px', flexWrap: 'wrap' }}>
              <Badge value={personalStatus?.status} />
              <span>{personalActions.length} bounded actions</span>
              <span>{personalAudit.length} recent audit events</span>
            </div>
            <div style={{ marginTop: '10px', display: 'grid', gridTemplateColumns: 'repeat(auto-fit, minmax(180px, 1fr))', gap: '8px' }}>
              {personalActions.slice(0, 8).map(action => (
                <div key={action.tool_id} style={{ background: 'rgba(255,255,255,0.03)', padding: '8px', borderRadius: '6px' }}>
                  <strong>{action.legacy_name}</strong>
                  <div style={{ fontSize: '12px', color: 'var(--text-secondary)' }}>{action.category} | {action.approval_policy}</div>
                </div>
              ))}
            </div>
          </div>

          <div className="glass-card">
            <h3>Cron Scheduler</h3>
            {cronSchedules.length === 0 ? <Empty>No schedules registered.</Empty> : cronSchedules.slice(0, 8).map(schedule => (
              <div key={schedule.id} style={{ borderTop: '1px solid var(--border-glass)', padding: '10px 0' }}>
                <strong>{schedule.target_tool_id}</strong> <Badge value={schedule.status} /> <span>{schedule.schedule_type}</span>
                <div style={{ fontSize: '12px', color: 'var(--text-secondary)' }}>Timezone: {schedule.timezone} | Next: {schedule.next_run_at || '(none)'} | Last: {schedule.last_run_at || '(none)'} | Missed: {schedule.missed_run_policy}</div>
              </div>
            ))}
            <h4>Recent runs</h4>
            {cronRuns.length === 0 ? <Empty>No run attempts yet.</Empty> : cronRuns.slice(0, 6).map(run => (
              <div key={run.id} style={{ fontSize: '13px', padding: '4px 0' }}>{run.schedule_id} at {run.scheduled_for} <Badge value={run.status} /> Approval: {run.approval_request_id || '(none)'}</div>
            ))}
          </div>

          <div className="glass-card">
            <h3>Tool Calls, Results, and Blocked Attempts</h3>
            <div style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fit, minmax(240px, 1fr))', gap: '12px' }}>
              <div>
                <h4>Recent Calls</h4>
                {calls.length === 0 ? <Empty>No tool calls logged.</Empty> : calls.slice(0, 6).map(call => <div key={call.id}>{call.tool_name} <Badge value={call.status} /></div>)}
              </div>
              <div>
                <h4>Recent Results</h4>
                {results.length === 0 ? <Empty>No tool results logged.</Empty> : results.slice(0, 6).map(result => <div key={result.id}>{result.tool_name} <Badge value={result.status} /></div>)}
              </div>
              <div>
                <h4>Blocked</h4>
                {blocked.length === 0 ? <Empty>No blocked attempts logged.</Empty> : blocked.slice(0, 6).map(item => <div key={item.id}>{item.tool_name} <Badge value={item.action || item.risk_level} /></div>)}
              </div>
            </div>
          </div>

          <div className="glass-card">
            <h3>Policy Matrix</h3>
            {policyEntries.length === 0 ? <Empty>No policy metadata available.</Empty> : (
              <div style={{ display: 'grid', gap: '8px' }}>
                {policyEntries.slice(0, 16).map(entry => (
                  <div key={entry.tool_id} style={{ display: 'grid', gridTemplateColumns: '1.5fr 1fr 1fr 1fr', gap: '8px', alignItems: 'center', fontSize: '13px' }}>
                    <strong>{entry.legacy_name}</strong>
                    <span>{entry.provider}</span>
                    <Badge value={entry.risk_class} />
                    <Badge value={entry.policy_decision} />
                  </div>
                ))}
              </div>
            )}
          </div>
        </>
      )}
    </div>
  );
}

if (typeof window !== 'undefined') {
  window.ToolsOpsCockpit = ToolsOpsCockpit;
}
