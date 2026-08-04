import React, { useEffect, useState } from 'react';

const endpoints = {
  overview: '/api/memory/observability/overview',
  health: '/api/memory/observability/health',
  jobs: '/api/memory/observability/jobs',
  workers: '/api/memory/observability/workers',
  deadLetters: '/api/memory/observability/dead-letter',
  semantic: '/api/memory/observability/semantic',
  procedural: '/api/memory/observability/procedural',
  skills: '/api/memory/observability/skills'
};

function StatusPill({ value }) {
  const tone = value === 'OK' ? '#4ecdc4' : value === 'ERROR' ? '#ff6b6b' : '#ffd166';
  return (
    <span style={{ color: tone, border: `1px solid ${tone}`, borderRadius: '999px', padding: '2px 8px', fontSize: '12px' }}>
      {value || 'UNKNOWN'}
    </span>
  );
}

function Metric({ label, value }) {
  return (
    <div style={{ padding: '12px', background: 'rgba(255,255,255,0.04)', border: '1px solid var(--border-glass)', borderRadius: '8px' }}>
      <div style={{ fontSize: '12px', color: 'var(--text-secondary)' }}>{label}</div>
      <div style={{ fontSize: '22px', fontWeight: 700 }}>{value ?? 0}</div>
    </div>
  );
}

function Panel({ title, children }) {
  return (
    <section className="glass-card" style={{ padding: '16px', display: 'flex', flexDirection: 'column', gap: '12px' }}>
      <h3 style={{ margin: 0, fontFamily: 'var(--font-heading)' }}>{title}</h3>
      {children}
    </section>
  );
}

function SimpleTable({ rows, emptyText }) {
  if (!rows || rows.length === 0) {
    return <div style={{ color: 'var(--text-secondary)', fontStyle: 'italic', padding: '12px 0' }}>{emptyText}</div>;
  }
  const columns = Object.keys(rows[0] || {}).slice(0, 8);
  return (
    <div style={{ overflowX: 'auto' }}>
      <table style={{ width: '100%', borderCollapse: 'collapse', fontSize: '12px' }}>
        <thead>
          <tr style={{ borderBottom: '1px solid var(--border-glass)', textAlign: 'left' }}>
            {columns.map(col => <th key={col} style={{ padding: '8px', color: '#4ecdc4' }}>{col}</th>)}
          </tr>
        </thead>
        <tbody>
          {rows.map((row, idx) => (
            <tr key={idx} style={{ borderBottom: '1px solid rgba(255,255,255,0.04)' }}>
              {columns.map(col => (
                <td key={col} style={{ padding: '8px', maxWidth: '220px', overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap' }}>
                  {typeof row[col] === 'object' ? JSON.stringify(row[col]) : String(row[col] ?? '')}
                </td>
              ))}
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}

export default function MemoryObservabilityCockpit() {
  const [data, setData] = useState({});
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState(null);
  const [traceQuery, setTraceQuery] = useState('');
  const [traceSession, setTraceSession] = useState('default_session');
  const [showPromptBlock, setShowPromptBlock] = useState(false);
  const [trace, setTrace] = useState(null);
  const [traceError, setTraceError] = useState(null);

  const loadPanelData = async () => {
    setLoading(true);
    setError(null);
    try {
      const entries = await Promise.all(Object.entries(endpoints).map(async ([key, url]) => {
        const res = await fetch(url);
        if (!res.ok) throw new Error(`${key}: HTTP ${res.status}`);
        return [key, await res.json()];
      }));
      setData(Object.fromEntries(entries));
    } catch (err) {
      setError(err.message || 'Failed to load memory observability');
    } finally {
      setLoading(false);
    }
  };

  const runTrace = async () => {
    setTraceError(null);
    setTrace(null);
    try {
      const res = await fetch('/api/memory/observability/retrieval/trace', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          query: traceQuery,
          session_id: traceSession,
          include_prompt_block: showPromptBlock,
          include_candidates: true
        })
      });
      if (!res.ok) throw new Error(`Trace failed: HTTP ${res.status}`);
      setTrace(await res.json());
    } catch (err) {
      setTraceError(err.message || 'Trace failed');
    }
  };

  useEffect(() => {
    loadPanelData();
  }, []);

  const health = data.health || data.overview?.health || {};
  const jobs = data.jobs || {};
  const workers = data.workers || {};
  const deadLetters = data.deadLetters || {};
  const semantic = data.semantic || {};
  const procedural = data.procedural || {};
  const skills = data.skills || {};

  return (
    <div style={{ display: 'flex', flexDirection: 'column', gap: '20px' }}>
      <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center' }}>
        <div>
          <h2 style={{ margin: 0, fontFamily: 'var(--font-heading)' }}>Memory Ops</h2>
          <div style={{ color: 'var(--text-secondary)', fontSize: '13px' }}>Read-only observability for memory queues, retrieval, candidates, and skills.</div>
        </div>
        <button onClick={loadPanelData} style={{ padding: '8px 16px', background: 'var(--primary-glow)', border: 'none', borderRadius: '6px', color: 'white', cursor: 'pointer' }}>Refresh</button>
      </div>

      {error && <div style={{ padding: '12px', background: 'rgba(255,50,50,0.15)', borderRadius: '8px', color: '#ff6b6b' }}>{error}</div>}
      {loading ? <div style={{ color: 'var(--text-secondary)' }}>Loading memory observability...</div> : (
        <>
          <Panel title="Health Overview">
            <div style={{ display: 'flex', alignItems: 'center', gap: '12px' }}><span>Status</span><StatusPill value={health.status} /></div>
            <div style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fit, minmax(150px, 1fr))', gap: '12px' }}>
              <Metric label="Jobs" value={health.queue?.total_jobs} />
              <Metric label="Dead Letters" value={health.queue?.dead_letter_count} />
              <Metric label="Active Workers" value={health.workers?.active_workers} />
              <Metric label="Semantic Pending" value={health.semantic?.pending_candidates} />
              <Metric label="Ready Skills" value={health.procedural?.ready_for_promotion} />
              <Metric label="Active Versions" value={health.skills?.active_versions} />
            </div>
          </Panel>

          <Panel title="Queue and Workers">
            <SimpleTable rows={jobs.jobs || []} emptyText="No memory jobs found." />
            <SimpleTable rows={workers.workers || []} emptyText="No worker heartbeats recorded. The memory worker is not auto-started." />
          </Panel>

          <Panel title="Dead Letters">
            <SimpleTable rows={deadLetters.dead_letters || []} emptyText="No dead-lettered memory jobs." />
          </Panel>

          <Panel title="Retrieval Trace">
            <div style={{ display: 'flex', gap: '10px', flexWrap: 'wrap' }}>
              <input value={traceQuery} onChange={e => setTraceQuery(e.target.value)} placeholder="Query to trace" style={{ flex: 2, minWidth: '260px', padding: '10px', background: 'rgba(0,0,0,0.3)', border: '1px solid var(--border-glass)', borderRadius: '6px', color: 'white' }} />
              <input value={traceSession} onChange={e => setTraceSession(e.target.value)} placeholder="Session ID" style={{ flex: 1, minWidth: '160px', padding: '10px', background: 'rgba(0,0,0,0.3)', border: '1px solid var(--border-glass)', borderRadius: '6px', color: 'white' }} />
              <label style={{ display: 'flex', alignItems: 'center', gap: '6px', color: 'var(--text-secondary)' }}>
                <input type="checkbox" checked={showPromptBlock} onChange={e => setShowPromptBlock(e.target.checked)} /> Show redacted prompt block
              </label>
              <button onClick={runTrace} style={{ padding: '10px 16px', background: 'var(--primary-glow)', border: 'none', borderRadius: '6px', color: 'white', cursor: 'pointer' }}>Trace</button>
            </div>
            {traceError && <div style={{ color: '#ff6b6b' }}>{traceError}</div>}
            {trace ? (
              <div style={{ display: 'grid', gridTemplateColumns: 'minmax(220px, 0.8fr) 1fr', gap: '12px' }}>
                <pre style={{ whiteSpace: 'pre-wrap', fontSize: '12px', background: 'rgba(0,0,0,0.25)', padding: '12px', borderRadius: '8px' }}>{JSON.stringify({ gate: trace.gate, plan: trace.plan, assembly: trace.assembly }, null, 2)}</pre>
                <SimpleTable rows={trace.candidates || []} emptyText="No candidates selected." />
              </div>
            ) : <div style={{ color: 'var(--text-secondary)', fontStyle: 'italic' }}>Run a trace to inspect planner and retrieval decisions.</div>}
          </Panel>

          <Panel title="Semantic Pipeline">
            <SimpleTable rows={semantic.candidates || []} emptyText="No semantic candidates." />
            <SimpleTable rows={semantic.recent_consolidation_runs || []} emptyText="No semantic consolidation runs." />
          </Panel>

          <Panel title="Procedural Pipeline">
            <SimpleTable rows={procedural.candidates || []} emptyText="No procedural candidates." />
            <SimpleTable rows={procedural.approvals || []} emptyText="No procedural approvals." />
          </Panel>

          <Panel title="Skill Versions / Usage">
            <SimpleTable rows={skills.active_versions || []} emptyText="No active skill versions." />
          </Panel>
        </>
      )}
    </div>
  );
}

if (typeof window !== 'undefined') {
  window.MemoryObservabilityCockpit = MemoryObservabilityCockpit;
}
