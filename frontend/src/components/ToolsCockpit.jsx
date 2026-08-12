import React, { useState, useEffect } from 'react';
import { api } from '../api/client.js';

function Badge({ value }) {
  const text = String(value || 'unknown');
  const high = ['High', 'blocked', 'unavailable', 'approval_required'].some(marker => text.includes(marker));
  const low = ['Low', 'available', 'no_approval_needed'].includes(text);
  return (
    <span
      className="retrieval-badge"
      style={{
        background: high ? 'rgba(255,50,50,0.18)' : low ? 'rgba(46,204,113,0.16)' : 'rgba(78,205,196,0.14)',
        color: high ? '#ff6b6b' : low ? '#2ecc71' : '#4ecdc4'
      }}
    >
      {text}
    </span>
  );
}

function ToolRow({ tool }) {
  return (
    <div style={{ padding: '10px', background: 'rgba(255,255,255,0.03)', borderRadius: '6px' }}>
      <div style={{ display: 'flex', justifyContent: 'space-between', gap: '8px', alignItems: 'center', flexWrap: 'wrap' }}>
        <strong>{tool.legacy_name || tool.name}</strong>
        <div style={{ display: 'flex', gap: '6px', flexWrap: 'wrap' }}>
          <Badge value={tool.availability_status || 'available'} />
          <Badge value={tool.risk_class || tool.risk_level || 'Low'} />
        </div>
      </div>
      <div style={{ fontSize: '12px', color: 'var(--text-secondary)', marginTop: '4px' }}>
        Provider: {tool.provider || 'legacy'} | Type: {tool.implementation_type || 'active'} | Policy: {tool.approval_policy || 'no_approval_needed'} | Capability: {tool.read_write_capability || 'unknown'}
      </div>
      {tool.description && <div style={{ fontSize: '12px', color: 'var(--text-secondary)', marginTop: '4px' }}>{tool.description}</div>}
    </div>
  );
}

function Group({ title, tools, empty }) {
  return (
    <div className="glass-card">
      <h3 style={{ marginTop: 0 }}>{title} ({tools?.length || 0})</h3>
      {!tools || tools.length === 0 ? (
        <div style={{ color: 'var(--text-secondary)' }}>{empty || 'No entries.'}</div>
      ) : (
        <div style={{ display: 'flex', flexDirection: 'column', gap: '8px', marginTop: '12px' }}>
          {tools.map(tool => <ToolRow key={tool.tool_id || tool.name} tool={tool} />)}
        </div>
      )}
    </div>
  );
}

export default function ToolsCockpit({ onRefresh }) {
  const [toolsData, setToolsData] = useState(null);
  const [overview, setOverview] = useState(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState(null);

  const fetchTools = async () => {
    setLoading(true);
    setError(null);
    try {
      const [catalogData, overviewData] = await Promise.all([
        api.get('/api/tools'),
        api.get('/api/tools/observability/overview')
      ]);
      setToolsData(catalogData);
      setOverview(overviewData);
    } catch (e) {
      setError(e.message || 'Failed to load tools catalog');
    } finally {
      setLoading(false);
    }
  };

  useEffect(() => { fetchTools(); }, []);

  const groups = overview?.registry?.groups || {};
  const unavailableMcp = (groups.mcp || []).filter(tool => tool.availability_status !== 'available');
  const activeMcp = (groups.mcp || []).filter(tool => tool.availability_status === 'available');

  return (
    <div style={{ display: 'flex', flexDirection: 'column', gap: '20px' }}>
      <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center' }}>
        <h2 style={{ fontFamily: 'var(--font-heading)', margin: 0 }}>Tools Catalog</h2>
        <button onClick={() => { fetchTools(); if (onRefresh) onRefresh(); }} style={{ padding: '8px 16px', background: 'var(--primary-glow)', border: 'none', borderRadius: '6px', color: 'white', cursor: 'pointer' }}>Refresh</button>
      </div>

      {error && <div style={{ padding: '12px', background: 'rgba(255, 50, 50, 0.15)', borderRadius: '8px', color: '#ff6b6b' }}>Error: {error}</div>}
      {loading ? <div style={{ padding: '32px', textAlign: 'center', color: 'var(--text-secondary)' }}>Loading tools catalog...</div> : (
        <>
          <div style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fit, minmax(180px, 1fr))', gap: '12px' }}>
            <div className="glass-card"><h4>Legacy API Shape</h4><strong>{toolsData?.total_tools || 0}</strong><div>Active catalog entries</div></div>
            <div className="glass-card"><h4>Bindable</h4><strong>{overview?.status?.registry?.total_bindable_tools || 0}</strong><div>Primary agent tools</div></div>
            <div className="glass-card"><h4>Removed</h4><strong>{groups.removed?.length || 0}</strong><div>Blocked metadata entries</div></div>
          </div>
          <div style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fit, minmax(300px, 1fr))', gap: '16px' }}>
            <Group title="Personal OS" tools={groups.personal_os || []} />
            <Group title="Cron Boundary" tools={groups.cron || []} />
            <Group title="Provider-managed MCP Available" tools={activeMcp} empty="No MCP provider tools are currently available." />
            <Group title="Unavailable MCP Providers/Tools" tools={unavailableMcp} />
            <Group title="Removed/Blocked Tools" tools={groups.removed || []} empty="No removed-tool metadata found." />
          </div>
        </>
      )}
    </div>
  );
}

if (typeof window !== 'undefined') {
  window.ToolsCockpit = ToolsCockpit;
}