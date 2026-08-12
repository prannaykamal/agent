import React, { useEffect, useState } from 'react';
import { api } from '../api/client.js';

function Badge({ value }) {
  const text = String(value || 'unknown');
  const good = ['available', 'OK', 'SUCCEEDED', 'no_approval_needed', 'configured', 'discovered'].includes(text.toLowerCase());
  const warn = ['unavailable', 'approval_required', 'blocked', 'FAILED', 'FAILED_TERMINAL', 'not_configured', 'discovery_failed'].some(marker => text.toLowerCase().includes(marker));
  
  return (
    <span
      className="retrieval-badge"
      style={{
        background: good ? 'rgba(46, 204, 113, 0.18)' : warn ? 'rgba(255, 99, 99, 0.18)' : 'rgba(255,255,255,0.06)',
        color: good ? '#2ecc71' : warn ? '#ff6b6b' : 'var(--text-secondary)',
        padding: '3px 8px',
        borderRadius: '4px',
        fontSize: '11px',
        fontWeight: '600'
      }}
    >
      {text}
    </span>
  );
}

function Empty({ children }) {
  return <div style={{ color: 'var(--text-secondary)', padding: '12px 0', fontStyle: 'italic' }}>{children}</div>;
}

export default function ToolsOpsCockpit() {
  const [toolsStatus, setToolsStatus] = useState(null);
  const [overview, setOverview] = useState(null);
  const [providers, setProviders] = useState([]);
  const [externalProviders, setExternalProviders] = useState([]);
  const [personalStatus, setPersonalStatus] = useState(null);
  const [personalActions, setPersonalActions] = useState([]);
  const [personalAudit, setPersonalAudit] = useState([]);
  const [cronSchedules, setCronSchedules] = useState([]);
  const [cronRuns, setCronRuns] = useState([]);

  // Detail & Refresh states
  const [selectedProviderDetail, setSelectedProviderDetail] = useState(null);
  const [refreshingProviderId, setRefreshingProviderId] = useState(null);
  const [notice, setNotice] = useState(null);

  // Standalone observability state
  const [activeSubTab, setActiveSubTab] = useState('overview'); // 'overview' | 'calls' | 'results' | 'audit' | 'blocked'
  const [callsList, setCallsList] = useState([]);
  const [resultsList, setResultsList] = useState([]);
  const [auditList, setAuditList] = useState([]);
  const [blockedList, setBlockedList] = useState([]);

  const [loading, setLoading] = useState(true);
  const [error, setError] = useState(null);

  const load = async () => {
    setLoading(true);
    setError(null);
    try {
      const [
        statusData,
        overviewData,
        providersData,
        externalProvidersData,
        personalStatusData,
        personalActionsData,
        personalAuditData,
        schedulesData,
        runsData
      ] = await Promise.all([
        api.get('/api/tools/status'),
        api.get('/api/tools/observability/overview'),
        api.get('/api/tools/mcp/providers'),
        api.get('/api/tools/external/providers'),
        api.get('/api/tools/personal-os/status'),
        api.get('/api/tools/personal-os/actions'),
        api.get('/api/tools/personal-os/audit'),
        api.get('/api/tools/cron/schedules'),
        api.get('/api/tools/cron/runs?limit=20')
      ]);

      setToolsStatus(statusData);
      setOverview(overviewData);
      setProviders((providersData.providers || []).map(p => ({ ...p, provider_layer: 'mcp' })));
      setExternalProviders((externalProvidersData.providers || []).map(p => ({ ...p, provider_layer: 'external_api' })));
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

  const loadStandaloneObservability = async (tab) => {
    setActiveSubTab(tab);
    setError(null);
    try {
      if (tab === 'calls') {
        const data = await api.get('/api/tools/observability/calls?limit=50');
        setCallsList(data.tool_calls || []);
      } else if (tab === 'results') {
        const data = await api.get('/api/tools/observability/results?limit=50');
        setResultsList(data.tool_results || []);
      } else if (tab === 'audit') {
        const data = await api.get('/api/tools/observability/audit?limit=50');
        setAuditList(data.audit_events || []);
      } else if (tab === 'blocked') {
        const data = await api.get('/api/tools/observability/blocked?limit=50');
        setBlockedList(data.blocked_attempts || []);
      }
    } catch (e) {
      setError(`Failed to fetch ${tab}: ${e.message}`);
    }
  };

  const handleInspectProvider = async (providerId, providerLayer = 'mcp') => {
    setError(null);
    try {
      const endpoint = providerLayer === 'external_api'
        ? `/api/tools/external/providers/${providerId}`
        : `/api/tools/mcp/providers/${providerId}`;
      const data = await api.get(endpoint);
      setSelectedProviderDetail({ ...data, provider_layer: providerLayer });
    } catch (e) {
      setError(`Failed to inspect provider '${providerId}': ${e.message}`);
    }
  };

  const handleSafeDiscoverRefresh = async (providerId) => {
    if (providerId === 'whatsapp_api' || providerId === 'telegram_bot_api') {
      setNotice(`'${providerId}' is a direct API provider; MCP discovery is not applicable.`);
      return;
    }
    setRefreshingProviderId(providerId);
    setError(null);
    setNotice(null);
    try {
      const data = await api.post(`/api/tools/mcp/providers/${providerId}/discover`);
      setNotice(`Metadata discovery refreshed for '${providerId}'. Status: ${data.availability_status}`);
      if (selectedProviderDetail && selectedProviderDetail.provider_id === providerId) {
        setSelectedProviderDetail(data);
      }
      load();
    } catch (e) {
      setError(`Discovery refresh failed for '${providerId}': ${e.message}`);
    } finally {
      setRefreshingProviderId(null);
    }
  };

  const allProviders = [...providers, ...externalProviders];
  const calls = overview?.tool_calls?.tool_calls || [];
  const results = overview?.tool_results?.tool_results || [];
  const blocked = overview?.blocked?.blocked_attempts || [];
  const policyEntries = overview?.policy?.entries || [];

  return (
    <div style={{ display: 'flex', flexDirection: 'column', gap: '20px' }}>
      {/* Header */}
      <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center' }}>
        <div>
          <h2 style={{ fontFamily: 'var(--font-heading)', margin: 0 }}>🧰 Tools Ops & MCP Discovery</h2>
          <span style={{ fontSize: '12px', color: 'var(--text-secondary)' }}>
            System Status: <strong>{toolsStatus?.status || 'OK'}</strong> | Provider Registry & Policy Engine
          </span>
        </div>
        <button onClick={load} style={{ padding: '8px 16px', background: 'var(--primary-glow)', border: 'none', borderRadius: '6px', color: 'white', cursor: 'pointer' }}>
          🔄 Refresh
        </button>
      </div>

      {notice && (
        <div style={{ padding: '10px 16px', background: 'rgba(46, 204, 113, 0.15)', border: '1px solid rgba(46, 204, 113, 0.3)', borderRadius: '8px', color: '#2ecc71', fontSize: '13px' }}>
          ℹ️ {notice}
        </div>
      )}

      {error && (
        <div style={{ padding: '12px', background: 'rgba(255, 50, 50, 0.15)', borderRadius: '8px', color: '#ff6b6b', fontSize: '13px' }}>
          ⚠️ {error}
        </div>
      )}

      {loading ? <Empty>🌀 Loading tools observability & provider registry...</Empty> : (
        <>
          {/* Top Status Cards Summary */}
          <div style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fit, minmax(180px, 1fr))', gap: '12px' }}>
            <div className="glass-card">
              <h4 style={{ color: 'var(--text-secondary)', marginBottom: '4px' }}>Bindable Tools</h4>
              <strong style={{ fontSize: '18px' }}>{toolsStatus?.registry?.total_bindable_tools || 0}</strong>
              <div style={{ fontSize: '11px', color: 'var(--text-secondary)', marginTop: '2px' }}>
                OS: {toolsStatus?.registry?.group_counts?.personal_os || 0} | MCP: {toolsStatus?.registry?.group_counts?.mcp || 0} | API: {toolsStatus?.registry?.group_counts?.external_api || 0}
              </div>
            </div>

            <div className="glass-card">
              <h4 style={{ color: 'var(--text-secondary)', marginBottom: '4px' }}>Providers</h4>
              <strong style={{ fontSize: '18px', color: '#2ecc71' }}>
                {toolsStatus?.providers?.available_providers || 0}/{toolsStatus?.providers?.total_providers || 0}
              </strong>
              <div style={{ fontSize: '11px', color: 'var(--text-secondary)', marginTop: '2px' }}>Available</div>
            </div>

            <div className="glass-card">
              <h4 style={{ color: 'var(--text-secondary)', marginBottom: '4px' }}>Policy Classifications</h4>
              <strong style={{ fontSize: '18px', color: '#3498db' }}>{policyEntries.length}</strong>
              <div style={{ fontSize: '11px', color: 'var(--text-secondary)', marginTop: '2px' }}>Classified Rules</div>
            </div>

            <div className="glass-card">
              <h4 style={{ color: 'var(--text-secondary)', marginBottom: '4px' }}>Removed Tools</h4>
              <strong style={{ fontSize: '18px', color: '#ff6b6b' }}>{toolsStatus?.removed_tools?.total || 0}</strong>
              <div style={{ fontSize: '11px', color: 'var(--text-secondary)', marginTop: '2px' }}>
                Active Blocked: {toolsStatus?.removed_tools?.active || 0}
              </div>
            </div>
          </div>

          {/* MCP Provider Detail Inspection Panel */}
          {selectedProviderDetail && (
            <div className="glass-card" style={{ border: '1px solid var(--primary-glow)', background: 'rgba(0,0,0,0.4)', position: 'relative' }}>
              <button
                onClick={() => setSelectedProviderDetail(null)}
                style={{ position: 'absolute', top: '12px', right: '12px', background: 'none', border: 'none', color: 'var(--text-secondary)', cursor: 'pointer', fontSize: '16px' }}
              >
                ✖
              </button>
              <h3 style={{ margin: '0 0 10px 0', fontFamily: 'var(--font-heading)', fontSize: '16px', display: 'flex', alignItems: 'center', gap: '10px' }}>
                <span>🔍 Provider Inspection: <code>{selectedProviderDetail.provider_id}</code></span>
                <Badge value={selectedProviderDetail.availability_status} />
              </h3>

              <div style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fit, minmax(200px, 1fr))', gap: '10px', fontSize: '13px', marginBottom: '12px' }}>
                <div>Display Name: <strong>{selectedProviderDetail.display_name || selectedProviderDetail.provider_id}</strong></div>
                <div>Transport: <code>{selectedProviderDetail.transport_type || selectedProviderDetail.transport || 'stdio'}</code></div>
                <div>Credential Status: <Badge value={selectedProviderDetail.credential_status} /></div>
                <div>Discovery Status: <Badge value={selectedProviderDetail.discovery_status} /></div>
                <div>Enabled: <strong>{selectedProviderDetail.enabled ? 'Yes' : 'No'}</strong></div>
                <div>Tool Count: <strong>{selectedProviderDetail.tool_count || 0}</strong></div>
                <div>Last Discovered: <strong>{selectedProviderDetail.last_discovered_at || 'Never'}</strong></div>
              </div>

              {selectedProviderDetail.last_error && (
                <div style={{ padding: '8px 12px', background: 'rgba(255,71,87,0.15)', borderRadius: '6px', color: '#ff6b6b', fontSize: '12px', marginBottom: '12px' }}>
                  <strong>Last Error:</strong> {selectedProviderDetail.last_error}
                </div>
              )}

              {selectedProviderDetail.tools && selectedProviderDetail.tools.length > 0 && (
                <div>
                  <strong style={{ fontSize: '13px', color: 'var(--text-secondary)' }}>Discovered Tools ({selectedProviderDetail.tools.length}):</strong>
                  <div style={{ marginTop: '6px', display: 'grid', gridTemplateColumns: 'repeat(auto-fit, minmax(220px, 1fr))', gap: '8px' }}>
                    {selectedProviderDetail.tools.map(t => (
                      <div key={t.tool_id} style={{ padding: '6px 10px', background: 'rgba(255,255,255,0.03)', borderRadius: '4px', fontSize: '12px' }}>
                        <code>{t.tool_id}</code>
                        <span style={{ fontSize: '11px', color: 'var(--text-secondary)', display: 'block' }}>Provider Managed: {t.provider_managed ? 'Yes' : 'No'}</span>
                      </div>
                    ))}
                  </div>
                </div>
              )}

              <div style={{ marginTop: '14px', paddingTop: '10px', borderTop: '1px solid var(--border-glass)', display: 'flex', justifyContent: 'space-between', alignItems: 'center' }}>
                <span style={{ fontSize: '11px', color: 'var(--text-secondary)' }}>🔒 Secrets and raw credentials are redacted in status inspection.</span>
                <button
                  disabled={refreshingProviderId === selectedProviderDetail.provider_id}
                  onClick={() => handleSafeDiscoverRefresh(selectedProviderDetail.provider_id)}
                  style={{ padding: '6px 14px', background: 'var(--primary-glow)', border: 'none', borderRadius: '4px', color: 'white', cursor: 'pointer', fontSize: '12px', fontWeight: '600' }}
                >
                  {refreshingProviderId === selectedProviderDetail.provider_id ? 'Refreshing...' : '🔄 Refresh Metadata'}
                </button>
              </div>
            </div>
          )}

          {/* MCP Providers List */}
          <div className="glass-card">
            <h3 style={{ margin: '0 0 12px 0', fontFamily: 'var(--font-heading)', fontSize: '16px' }}>🛠️ Provider Registry</h3>
            {allProviders.length === 0 ? <Empty>No provider status available.</Empty> : allProviders.map(provider => (
              <div key={provider.provider_id} style={{ borderTop: '1px solid var(--border-glass)', padding: '12px 0', display: 'flex', justifyContent: 'space-between', gap: '12px', alignItems: 'center', flexWrap: 'wrap' }}>
                <div>
                  <div style={{ display: 'flex', gap: '8px', alignItems: 'center' }}>
                    <strong style={{ fontSize: '15px' }}>{provider.display_name}</strong>
                    <code>({provider.provider_id})</code>
                  </div>
                  <div style={{ fontSize: '12px', color: 'var(--text-secondary)', marginTop: '4px' }}>
                    Layer: <code>{provider.provider_layer === 'external_api' ? 'Direct API' : 'MCP'}</code> | Transport: <code>{provider.transport_type || 'external_api'}</code> | Credentials: <Badge value={provider.credential_status} />
                  </div>
                  {provider.last_error && <div style={{ fontSize: '12px', color: '#ff6b6b', marginTop: '4px' }}>Last error: {provider.last_error}</div>}
                </div>

                <div style={{ display: 'flex', gap: '8px', alignItems: 'center', flexWrap: 'wrap' }}>
                  <Badge value={provider.availability_status} />
                  {provider.discovery_status && <Badge value={provider.discovery_status} />}
                  <span style={{ fontSize: '12px' }}>{provider.tool_count ?? (provider.capabilities?.length || 0)} tools</span>
                  <button
                    onClick={() => handleInspectProvider(provider.provider_id, provider.provider_layer)}
                    style={{ padding: '5px 12px', background: 'rgba(255,255,255,0.08)', border: '1px solid var(--border-glass)', borderRadius: '4px', color: 'white', cursor: 'pointer', fontSize: '12px' }}
                  >
                    🔍 Inspect
                  </button>
                  <button
                    disabled={refreshingProviderId === provider.provider_id}
                    onClick={() => handleSafeDiscoverRefresh(provider.provider_id)}
                    style={{ padding: '5px 12px', background: 'var(--primary-glow)', border: 'none', borderRadius: '4px', color: 'white', cursor: 'pointer', fontSize: '12px' }}
                    title="Safe Metadata Refresh (No write side-effects)"
                  >
                    {refreshingProviderId === provider.provider_id ? 'Refreshing...' : '🔄 Refresh Metadata'}
                  </button>
                </div>
              </div>
            ))}
          </div>

          {/* Observability Sub-Navigation Tabs */}
          <div className="glass-card" style={{ padding: '12px 16px' }}>
            <div style={{ display: 'flex', gap: '10px', alignItems: 'center', borderBottom: '1px solid var(--border-glass)', paddingBottom: '10px', marginBottom: '12px' }}>
              <strong style={{ fontSize: '14px', fontFamily: 'var(--font-heading)' }}>Observability Views:</strong>
              {[
                { id: 'overview', label: '📊 Overview' },
                { id: 'calls', label: '📞 Tool Calls' },
                { id: 'results', label: '📥 Tool Results' },
                { id: 'audit', label: '🛡️ Personal OS Audit' },
                { id: 'blocked', label: '⛔ Blocked Attempts' }
              ].map(tab => (
                <button
                  key={tab.id}
                  onClick={() => {
                    if (tab.id === 'overview') setActiveSubTab('overview');
                    else loadStandaloneObservability(tab.id);
                  }}
                  style={{
                    padding: '6px 12px',
                    borderRadius: '6px',
                    border: 'none',
                    background: activeSubTab === tab.id ? 'var(--primary-glow)' : 'transparent',
                    color: activeSubTab === tab.id ? 'white' : 'var(--text-secondary)',
                    fontSize: '12px',
                    fontWeight: '600',
                    cursor: 'pointer'
                  }}
                >
                  {tab.label}
                </button>
              ))}
            </div>

            {/* Sub-Tab Content */}
            {activeSubTab === 'overview' && (
              <div style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fit, minmax(240px, 1fr))', gap: '12px' }}>
                <div>
                  <h4 style={{ margin: '0 0 8px 0' }}>Recent Calls</h4>
                  {calls.length === 0 ? <Empty>No tool calls logged.</Empty> : calls.slice(0, 6).map(call => <div key={call.id} style={{ fontSize: '13px', padding: '4px 0' }}>{call.tool_name} <Badge value={call.status} /></div>)}
                </div>
                <div>
                  <h4 style={{ margin: '0 0 8px 0' }}>Recent Results</h4>
                  {results.length === 0 ? <Empty>No tool results logged.</Empty> : results.slice(0, 6).map(result => <div key={result.id} style={{ fontSize: '13px', padding: '4px 0' }}>{result.tool_name} <Badge value={result.status} /></div>)}
                </div>
                <div>
                  <h4 style={{ margin: '0 0 8px 0' }}>Blocked Attempts</h4>
                  {blocked.length === 0 ? <Empty>No blocked attempts logged.</Empty> : blocked.slice(0, 6).map(item => <div key={item.id} style={{ fontSize: '13px', padding: '4px 0' }}>{item.tool_name} <Badge value={item.action || item.risk_level} /></div>)}
                </div>
              </div>
            )}

            {activeSubTab === 'calls' && (
              <div>
                <h4 style={{ margin: '0 0 10px 0' }}>Standalone Tool Calls Audit Log</h4>
                {callsList.length === 0 ? <Empty>No standalone tool calls found.</Empty> : (
                  <div style={{ display: 'flex', flexDirection: 'column', gap: '6px' }}>
                    {callsList.map(item => (
                      <div key={item.id} style={{ padding: '8px', background: 'rgba(255,255,255,0.03)', borderRadius: '4px', fontSize: '12px', display: 'flex', justifyContent: 'space-between' }}>
                        <div><strong>{item.tool_name}</strong> | Session: <code>{item.session_id}</code></div>
                        <Badge value={item.status} />
                      </div>
                    ))}
                  </div>
                )}
              </div>
            )}

            {activeSubTab === 'results' && (
              <div>
                <h4 style={{ margin: '0 0 10px 0' }}>Standalone Tool Results Audit Log</h4>
                {resultsList.length === 0 ? <Empty>No standalone tool results found.</Empty> : (
                  <div style={{ display: 'flex', flexDirection: 'column', gap: '6px' }}>
                    {resultsList.map(item => (
                      <div key={item.id} style={{ padding: '8px', background: 'rgba(255,255,255,0.03)', borderRadius: '4px', fontSize: '12px', display: 'flex', justifyContent: 'space-between' }}>
                        <div><strong>{item.tool_name}</strong> | Session: <code>{item.session_id}</code></div>
                        <Badge value={item.status} />
                      </div>
                    ))}
                  </div>
                )}
              </div>
            )}

            {activeSubTab === 'audit' && (
              <div>
                <h4 style={{ margin: '0 0 10px 0' }}>Personal OS Audit Events Log</h4>
                {auditList.length === 0 ? <Empty>No audit events found.</Empty> : (
                  <div style={{ display: 'flex', flexDirection: 'column', gap: '6px' }}>
                    {auditList.map(item => (
                      <div key={item.id} style={{ padding: '8px', background: 'rgba(255,255,255,0.03)', borderRadius: '4px', fontSize: '12px' }}>
                        <div style={{ display: 'flex', justifyContent: 'space-between' }}>
                          <strong>{item.action}</strong>
                          <Badge value={item.outcome} />
                        </div>
                        <div style={{ fontSize: '11px', color: 'var(--text-secondary)', marginTop: '2px' }}>{item.reason}</div>
                      </div>
                    ))}
                  </div>
                )}
              </div>
            )}

            {activeSubTab === 'blocked' && (
              <div>
                <h4 style={{ margin: '0 0 10px 0' }}>Blocked Attempts Log</h4>
                {blockedList.length === 0 ? <Empty>No blocked attempts found.</Empty> : (
                  <div style={{ display: 'flex', flexDirection: 'column', gap: '6px' }}>
                    {blockedList.map(item => (
                      <div key={item.id} style={{ padding: '8px', background: 'rgba(255,71,87,0.1)', borderRadius: '4px', fontSize: '12px', border: '1px solid rgba(255,71,87,0.3)' }}>
                        <div style={{ display: 'flex', justifyContent: 'space-between' }}>
                          <strong style={{ color: '#ff6b6b' }}>{item.tool_name}</strong>
                          <Badge value={item.action || item.risk_level} />
                        </div>
                        <div style={{ fontSize: '11px', color: 'var(--text-secondary)', marginTop: '2px' }}>{item.reason}</div>
                      </div>
                    ))}
                  </div>
                )}
              </div>
            )}
          </div>

          {/* Personal OS Bounded Actions */}
          <div className="glass-card">
            <h3>Personal OS Bounded Actions</h3>
            <div style={{ display: 'flex', gap: '10px', flexWrap: 'wrap', marginBottom: '10px' }}>
              <Badge value={personalStatus?.status} />
              <span>{personalActions.length} bounded actions</span>
              <span>{personalAudit.length} recent audit events</span>
            </div>
            <div style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fit, minmax(180px, 1fr))', gap: '8px' }}>
              {personalActions.slice(0, 8).map(action => (
                <div key={action.tool_id} style={{ background: 'rgba(255,255,255,0.03)', padding: '8px', borderRadius: '6px' }}>
                  <strong>{action.legacy_name}</strong>
                  <div style={{ fontSize: '12px', color: 'var(--text-secondary)' }}>{action.category} | {action.approval_policy}</div>
                </div>
              ))}
            </div>
          </div>

          {/* Policy Matrix */}
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

