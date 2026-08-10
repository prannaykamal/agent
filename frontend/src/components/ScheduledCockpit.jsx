import React, { useState, useEffect } from 'react';

export default function ScheduledCockpit({ onRefresh }) {
  const [schedules, setSchedules] = useState([]);
  const [runs, setRuns] = useState([]);
  const [scheduleType, setScheduleType] = useState('one_time');
  const [runAt, setRunAt] = useState('');
  const [cronExpression, setCronExpression] = useState('0 9 * * *');
  const [timezone, setTimezone] = useState('UTC');
  const [targetTool, setTargetTool] = useState('heartbeat');
  const [payloadInput, setPayloadInput] = useState('{}');
  const [missedPolicy, setMissedPolicy] = useState('run_once');
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState(null);

  const fetchScheduled = async () => {
    setLoading(true);
    setError(null);
    try {
      const [scheduleRes, runRes] = await Promise.all([
        fetch('/api/tools/cron/schedules'),
        fetch('/api/tools/cron/runs?limit=20')
      ]);
      if (!scheduleRes.ok) throw new Error(`Schedules HTTP ${scheduleRes.status}`);
      if (!runRes.ok) throw new Error(`Runs HTTP ${runRes.status}`);
      const scheduleData = await scheduleRes.json();
      const runData = await runRes.json();
      setSchedules(scheduleData.schedules || []);
      setRuns(runData.runs || []);
    } catch (e) {
      console.error(e);
      setError(e.message || 'Failed to load schedules');
    } finally {
      setLoading(false);
    }
  };

  useEffect(() => { fetchScheduled(); }, []);

  const parsePayload = () => {
    try { return JSON.parse(payloadInput || '{}'); }
    catch { return { text: payloadInput }; }
  };

  const handleCreateSchedule = async () => {
    try {
      const body = {
        schedule_type: scheduleType,
        target_tool_id: targetTool,
        target_payload: parsePayload(),
        timezone,
        missed_run_policy: missedPolicy,
        max_catchup_runs: 1
      };
      if (scheduleType === 'one_time') body.run_at = runAt;
      if (scheduleType === 'recurring') body.cron_expression = cronExpression;
      const res = await fetch('/api/tools/cron/schedules', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(body)
      });
      if (!res.ok) throw new Error(`Create HTTP ${res.status}`);
      setRunAt('');
      fetchScheduled();
      if (onRefresh) onRefresh();
    } catch (e) {
      console.error(e);
      setError(e.message || 'Failed to create schedule');
    }
  };

  const handleCancel = async (id) => {
    try {
      const res = await fetch(`/api/tools/cron/schedules/${id}`, { method: 'DELETE' });
      if (!res.ok) throw new Error(`Cancel HTTP ${res.status}`);
      fetchScheduled();
      if (onRefresh) onRefresh();
    } catch (e) {
      console.error(e);
      setError(e.message || 'Failed to cancel schedule');
    }
  };

  return (
    <div style={{ display: 'flex', flexDirection: 'column', gap: '20px' }}>
      <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center' }}>
        <h2 style={{ fontFamily: 'var(--font-heading)', margin: 0 }}>Scheduled Local Actions</h2>
        <button onClick={() => { fetchScheduled(); if (onRefresh) onRefresh(); }} style={{ padding: '8px 16px', background: 'var(--primary-glow)', border: 'none', borderRadius: '6px', color: 'white', cursor: 'pointer' }}>
          Refresh
        </button>
      </div>

      <div className="glass-card" style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fit, minmax(180px, 1fr))', gap: '12px', alignItems: 'end' }}>
        <label>Type<select value={scheduleType} onChange={e => setScheduleType(e.target.value)}><option value="one_time">One-time</option><option value="recurring">Recurring</option></select></label>
        {scheduleType === 'one_time' ? <label>Run At<input value={runAt} onChange={e => setRunAt(e.target.value)} placeholder="2026-08-11 10:00" /></label> : <label>Cron<input value={cronExpression} onChange={e => setCronExpression(e.target.value)} placeholder="0 9 * * *" /></label>}
        <label>Timezone<input value={timezone} onChange={e => setTimezone(e.target.value)} placeholder="UTC" /></label>
        <label>Target Tool<input value={targetTool} onChange={e => setTargetTool(e.target.value)} placeholder="heartbeat" /></label>
        <label>Payload JSON<input value={payloadInput} onChange={e => setPayloadInput(e.target.value)} /></label>
        <label>Missed Policy<select value={missedPolicy} onChange={e => setMissedPolicy(e.target.value)}><option value="run_once">Run once</option><option value="skip">Skip</option><option value="catch_up_limited">Catch up limited</option></select></label>
        <button onClick={handleCreateSchedule} style={{ padding: '10px 20px', background: 'var(--primary-glow)', border: 'none', borderRadius: '6px', color: 'white', fontWeight: 600, cursor: 'pointer' }}>Create</button>
      </div>

      {error && <div style={{ padding: '12px', background: 'rgba(255, 50, 50, 0.15)', borderRadius: '8px', color: '#ff6b6b' }}>Error: {error}</div>}

      {loading ? <div style={{ padding: '32px', textAlign: 'center', color: 'var(--text-secondary)' }}>Loading schedules...</div> : schedules.length === 0 ? <div className="glass-card" style={{ textAlign: 'center', padding: '48px', color: 'var(--text-secondary)', fontStyle: 'italic' }}>No schedules registered.</div> : (
        <div style={{ display: 'flex', flexDirection: 'column', gap: '12px' }}>
          {schedules.map(schedule => (
            <div key={schedule.id} className="glass-card" style={{ display: 'flex', justifyContent: 'space-between', gap: '16px', alignItems: 'center' }}>
              <div>
                <div style={{ display: 'flex', gap: '10px', alignItems: 'center', flexWrap: 'wrap' }}><strong>{schedule.id}</strong><span className="retrieval-badge">{schedule.status}</span><span>{schedule.schedule_type}</span></div>
                <div style={{ fontSize: '13px', color: 'var(--text-secondary)' }}>Target: {schedule.target_tool_id} | Timezone: {schedule.timezone} | Policy: {schedule.missed_run_policy}</div>
                <div style={{ fontSize: '13px', color: 'var(--text-secondary)' }}>Next: {schedule.next_run_at || '(none)'} | Last: {schedule.last_run_at || '(none)'}</div>
                <div style={{ fontSize: '13px', color: 'var(--text-secondary)' }}>{schedule.cron_expression ? `Cron: ${schedule.cron_expression}` : `Run at: ${schedule.run_at}`}</div>
              </div>
              <button onClick={() => handleCancel(schedule.id)} style={{ padding: '6px 12px', background: '#ff4757', border: 'none', borderRadius: '4px', color: 'white', cursor: 'pointer' }}>Cancel</button>
            </div>
          ))}
        </div>
      )}

      <div className="glass-card">
        <h3 style={{ marginTop: 0 }}>Recent Run Attempts</h3>
        {runs.length === 0 ? <div style={{ color: 'var(--text-secondary)' }}>No run attempts yet.</div> : runs.map(run => (
          <div key={run.id} style={{ borderTop: '1px solid var(--border-glass)', padding: '10px 0' }}>
            <strong>{run.status}</strong> for {run.schedule_id} at {run.scheduled_for}
            <div style={{ fontSize: '13px', color: 'var(--text-secondary)' }}>Approval: {run.approval_request_id || '(none)'} | Attempts: {run.attempt_count}</div>
            {run.result_preview && <div style={{ fontSize: '13px' }}>{run.result_preview}</div>}
          </div>
        ))}
      </div>
    </div>
  );
}

if (typeof window !== 'undefined') {
  window.ScheduledCockpit = ScheduledCockpit;
}
