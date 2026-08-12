import React, { useState, useEffect } from 'react';
import { api } from '../api/client.js';

function StatusBadge({ status }) {
  const s = String(status || 'UNKNOWN').toUpperCase();
  let bg = 'rgba(255, 255, 255, 0.08)';
  let color = 'var(--text-secondary)';

  if (['ACTIVE', 'SUCCEEDED'].includes(s)) {
    bg = 'rgba(46, 204, 113, 0.2)';
    color = '#2ecc71';
  } else if (['PENDING', 'CLAIMED', 'RUNNING'].includes(s)) {
    bg = 'rgba(52, 152, 219, 0.2)';
    color = '#3498db';
  } else if (['PAUSED', 'WAITING_FOR_APPROVAL', 'FAILED_RETRYABLE'].includes(s)) {
    bg = 'rgba(243, 156, 18, 0.2)';
    color = '#f39c12';
  } else if (['FAILED_TERMINAL', 'CANCELLED', 'EXPIRED'].includes(s)) {
    bg = 'rgba(255, 71, 87, 0.2)';
    color = '#ff4757';
  }

  return (
    <span
      className="retrieval-badge"
      style={{ background: bg, color: color, padding: '3px 8px', borderRadius: '4px', fontSize: '11px', fontWeight: '600' }}
    >
      {s}
    </span>
  );
}

export default function ScheduledCockpit({ onRefresh }) {
  const [schedules, setSchedules] = useState([]);
  const [runs, setRuns] = useState([]);
  
  // Filters
  const [scheduleStatusFilter, setScheduleStatusFilter] = useState('ALL');
  const [runStatusFilter, setRunStatusFilter] = useState('ALL');
  const [runScheduleIdFilter, setRunScheduleIdFilter] = useState('');

  // Form states for Create
  const [scheduleType, setScheduleType] = useState('one_time');
  const [runAt, setRunAt] = useState('');
  const [cronExpression, setCronExpression] = useState('0 9 * * *');
  const [timezone, setTimezone] = useState('UTC');
  const [targetTool, setTargetTool] = useState('heartbeat');
  const [payloadInput, setPayloadInput] = useState('{}');
  const [missedPolicy, setMissedPolicy] = useState('run_once');

  // Detail & Edit states
  const [selectedScheduleDetail, setSelectedScheduleDetail] = useState(null);
  const [editingSchedule, setEditingSchedule] = useState(null);
  const [editForm, setEditForm] = useState({});

  const [loading, setLoading] = useState(true);
  const [error, setError] = useState(null);
  const [actionNotice, setActionNotice] = useState(null);

  const fetchScheduled = async () => {
    setLoading(true);
    setError(null);
    try {
      let schedUrl = '/api/tools/cron/schedules';
      if (scheduleStatusFilter !== 'ALL') {
        schedUrl += `?status=${encodeURIComponent(scheduleStatusFilter)}`;
      }

      let runUrl = '/api/tools/cron/runs?limit=20';
      if (runStatusFilter !== 'ALL') {
        runUrl += `&status=${encodeURIComponent(runStatusFilter)}`;
      }
      if (runScheduleIdFilter.trim()) {
        runUrl += `&schedule_id=${encodeURIComponent(runScheduleIdFilter.trim())}`;
      }

      const [scheduleData, runData] = await Promise.all([
        api.get(schedUrl),
        api.get(runUrl)
      ]);

      setSchedules(scheduleData.schedules || []);
      setRuns(runData.runs || []);
    } catch (e) {
      console.error(e);
      setError(e.message || 'Failed to load schedules');
    } finally {
      setLoading(false);
    }
  };

  useEffect(() => {
    fetchScheduled();
  }, [scheduleStatusFilter, runStatusFilter, runScheduleIdFilter]);

  const parsePayload = (inputStr) => {
    try { return JSON.parse(inputStr || '{}'); }
    catch { return { text: inputStr }; }
  };

  const handleCreateSchedule = async () => {
    setError(null);
    setActionNotice(null);
    try {
      const body = {
        schedule_type: scheduleType,
        target_tool_id: targetTool,
        target_payload: parsePayload(payloadInput),
        timezone,
        missed_run_policy: missedPolicy,
        max_catchup_runs: 1
      };
      if (scheduleType === 'one_time') body.run_at = runAt;
      if (scheduleType === 'recurring') body.cron_expression = cronExpression;

      const data = await api.post('/api/tools/cron/schedules', body);
      setRunAt('');
      setActionNotice(`Schedule '${data.schedule?.id || 'created'}' successfully registered.`);
      fetchScheduled();
      if (onRefresh) onRefresh();
    } catch (e) {
      console.error(e);
      setError(e.message || 'Failed to create schedule');
    }
  };

  const handleInspectSchedule = async (id) => {
    setError(null);
    try {
      const data = await api.get(`/api/tools/cron/schedules/${id}`);
      setSelectedScheduleDetail(data.schedule);
    } catch (e) {
      console.error(e);
      setError(`Failed to inspect schedule: ${e.message}`);
    }
  };

  const handleOpenEdit = (schedule) => {
    setEditingSchedule(schedule);
    setEditForm({
      status: schedule.status,
      target_tool_id: schedule.target_tool_id,
      cron_expression: schedule.cron_expression || '',
      run_at: schedule.run_at || '',
      timezone: schedule.timezone || 'UTC',
      missed_run_policy: schedule.missed_run_policy || 'run_once',
      target_payload_str: JSON.stringify(schedule.target_payload || {}, null, 2)
    });
  };

  const handleSavePatchUpdate = async () => {
    if (!editingSchedule) return;
    setError(null);
    setActionNotice(null);
    try {
      const patchBody = {};
      if (editForm.status) patchBody.status = editForm.status;
      if (editForm.target_tool_id) patchBody.target_tool_id = editForm.target_tool_id;
      if (editForm.timezone) patchBody.timezone = editForm.timezone;
      if (editForm.missed_run_policy) patchBody.missed_run_policy = editForm.missed_run_policy;
      if (editingSchedule.schedule_type === 'recurring' && editForm.cron_expression) {
        patchBody.cron_expression = editForm.cron_expression;
      }
      if (editingSchedule.schedule_type === 'one_time' && editForm.run_at) {
        patchBody.run_at = editForm.run_at;
      }
      if (editForm.target_payload_str) {
        patchBody.target_payload = parsePayload(editForm.target_payload_str);
      }

      const resData = await api.patch(`/api/tools/cron/schedules/${editingSchedule.id}`, patchBody);
      setActionNotice(`Schedule '${editingSchedule.id}' updated successfully.`);
      setEditingSchedule(null);
      if (selectedScheduleDetail && selectedScheduleDetail.id === editingSchedule.id) {
        setSelectedScheduleDetail(resData.schedule);
      }
      fetchScheduled();
      if (onRefresh) onRefresh();
    } catch (e) {
      console.error(e);
      setError(`Update failed: ${e.message}`);
    }
  };

  const handleCancel = async (id) => {
    setError(null);
    setActionNotice(null);
    try {
      await api.delete(`/api/tools/cron/schedules/${id}`);
      setActionNotice(`Schedule '${id}' cancelled.`);
      if (selectedScheduleDetail && selectedScheduleDetail.id === id) {
        setSelectedScheduleDetail(null);
      }
      fetchScheduled();
      if (onRefresh) onRefresh();
    } catch (e) {
      console.error(e);
      setError(e.message || 'Failed to cancel schedule');
    }
  };

  return (
    <div style={{ display: 'flex', flexDirection: 'column', gap: '20px' }}>
      {/* Header */}
      <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center' }}>
        <h2 style={{ fontFamily: 'var(--font-heading)', margin: 0 }}>⏱️ Scheduled Local Actions & Cron Manager</h2>
        <button
          onClick={() => { fetchScheduled(); if (onRefresh) onRefresh(); }}
          style={{ padding: '8px 16px', background: 'var(--primary-glow)', border: 'none', borderRadius: '6px', color: 'white', cursor: 'pointer' }}
        >
          🔄 Refresh
        </button>
      </div>

      {actionNotice && (
        <div style={{ padding: '10px 16px', background: 'rgba(46, 204, 113, 0.15)', border: '1px solid rgba(46, 204, 113, 0.3)', borderRadius: '8px', color: '#2ecc71', fontSize: '13px' }}>
          ✓ {actionNotice}
        </div>
      )}

      {error && (
        <div style={{ padding: '12px', background: 'rgba(255, 50, 50, 0.15)', borderRadius: '8px', color: '#ff6b6b', fontSize: '13px' }}>
          ⚠️ {error}
        </div>
      )}

      {/* Create Schedule Form */}
      <div className="glass-card" style={{ display: 'flex', flexDirection: 'column', gap: '12px' }}>
        <h3 style={{ margin: 0, fontFamily: 'var(--font-heading)', fontSize: '15px' }}>➕ Register New Durable Schedule</h3>
        <div style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fit, minmax(180px, 1fr))', gap: '12px', alignItems: 'end' }}>
          <label style={{ fontSize: '12px', color: 'var(--text-secondary)' }}>
            Schedule Type
            <select value={scheduleType} onChange={e => setScheduleType(e.target.value)} style={{ display: 'block', width: '100%', marginTop: '4px', padding: '6px', background: 'rgba(0,0,0,0.3)', border: '1px solid var(--border-glass)', borderRadius: '4px', color: 'white' }}>
              <option value="one_time">One-time</option>
              <option value="recurring">Recurring</option>
            </select>
          </label>

          {scheduleType === 'one_time' ? (
            <label style={{ fontSize: '12px', color: 'var(--text-secondary)' }}>
              Run At (UTC / ISO)
              <input value={runAt} onChange={e => setRunAt(e.target.value)} placeholder="2026-08-12 10:00" style={{ display: 'block', width: '100%', marginTop: '4px', padding: '6px', background: 'rgba(0,0,0,0.3)', border: '1px solid var(--border-glass)', borderRadius: '4px', color: 'white' }} />
            </label>
          ) : (
            <label style={{ fontSize: '12px', color: 'var(--text-secondary)' }}>
              Cron Expression
              <input value={cronExpression} onChange={e => setCronExpression(e.target.value)} placeholder="0 9 * * *" style={{ display: 'block', width: '100%', marginTop: '4px', padding: '6px', background: 'rgba(0,0,0,0.3)', border: '1px solid var(--border-glass)', borderRadius: '4px', color: 'white' }} />
            </label>
          )}

          <label style={{ fontSize: '12px', color: 'var(--text-secondary)' }}>
            Timezone
            <input value={timezone} onChange={e => setTimezone(e.target.value)} placeholder="UTC" style={{ display: 'block', width: '100%', marginTop: '4px', padding: '6px', background: 'rgba(0,0,0,0.3)', border: '1px solid var(--border-glass)', borderRadius: '4px', color: 'white' }} />
          </label>

          <label style={{ fontSize: '12px', color: 'var(--text-secondary)' }}>
            Target Tool ID
            <input value={targetTool} onChange={e => setTargetTool(e.target.value)} placeholder="heartbeat" style={{ display: 'block', width: '100%', marginTop: '4px', padding: '6px', background: 'rgba(0,0,0,0.3)', border: '1px solid var(--border-glass)', borderRadius: '4px', color: 'white' }} />
          </label>

          <label style={{ fontSize: '12px', color: 'var(--text-secondary)' }}>
            Payload JSON
            <input value={payloadInput} onChange={e => setPayloadInput(e.target.value)} style={{ display: 'block', width: '100%', marginTop: '4px', padding: '6px', background: 'rgba(0,0,0,0.3)', border: '1px solid var(--border-glass)', borderRadius: '4px', color: 'white' }} />
          </label>

          <label style={{ fontSize: '12px', color: 'var(--text-secondary)' }}>
            Missed Policy
            <select value={missedPolicy} onChange={e => setMissedPolicy(e.target.value)} style={{ display: 'block', width: '100%', marginTop: '4px', padding: '6px', background: 'rgba(0,0,0,0.3)', border: '1px solid var(--border-glass)', borderRadius: '4px', color: 'white' }}>
              <option value="run_once">Run once</option>
              <option value="skip">Skip</option>
              <option value="catch_up_limited">Catch up limited</option>
            </select>
          </label>

          <button onClick={handleCreateSchedule} style={{ padding: '8px 18px', background: 'var(--primary-glow)', border: 'none', borderRadius: '6px', color: 'white', fontWeight: '600', cursor: 'pointer' }}>
            Submit Schedule
          </button>
        </div>
      </div>

      {/* Schedule Detail Inspection Modal / View */}
      {selectedScheduleDetail && (
        <div className="glass-card" style={{ border: '1px solid var(--primary-glow)', background: 'rgba(0,0,0,0.4)', padding: '16px', position: 'relative' }}>
          <button
            onClick={() => setSelectedScheduleDetail(null)}
            style={{ position: 'absolute', top: '12px', right: '12px', background: 'none', border: 'none', color: 'var(--text-secondary)', cursor: 'pointer', fontSize: '16px' }}
          >
            ✖
          </button>
          <h3 style={{ margin: '0 0 10px 0', fontFamily: 'var(--font-heading)', fontSize: '16px', display: 'flex', alignItems: 'center', gap: '10px' }}>
            <span>🔍 Schedule Details: <code>{selectedScheduleDetail.id}</code></span>
            <StatusBadge status={selectedScheduleDetail.status} />
          </h3>
          <div style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fit, minmax(200px, 1fr))', gap: '10px', fontSize: '13px' }}>
            <div>Type: <strong>{selectedScheduleDetail.schedule_type}</strong></div>
            <div>Target Tool: <code>{selectedScheduleDetail.target_tool_id}</code></div>
            <div>Timezone: <strong>{selectedScheduleDetail.timezone}</strong></div>
            <div>Missed Policy: <strong>{selectedScheduleDetail.missed_run_policy}</strong></div>
            <div>Next Run: <strong>{selectedScheduleDetail.next_run_at || 'None'}</strong></div>
            <div>Last Run: <strong>{selectedScheduleDetail.last_run_at || 'None'}</strong></div>
            <div>Created By: <strong>{selectedScheduleDetail.created_by || 'api'}</strong></div>
            <div>Created At: <strong>{selectedScheduleDetail.created_at || 'N/A'}</strong></div>
            <div>Timing: <strong>{selectedScheduleDetail.cron_expression ? `Cron: ${selectedScheduleDetail.cron_expression}` : `Run At: ${selectedScheduleDetail.run_at}`}</strong></div>
          </div>
          <div style={{ marginTop: '12px' }}>
            <strong style={{ fontSize: '12px', color: 'var(--text-secondary)' }}>Target Payload Preview:</strong>
            <pre style={{ margin: '4px 0 0 0', padding: '10px', background: 'rgba(0,0,0,0.5)', borderRadius: '6px', fontSize: '12px', color: '#4ecdc4', overflowX: 'auto' }}>
              {JSON.stringify(selectedScheduleDetail.target_payload || {}, null, 2)}
            </pre>
          </div>
          <div style={{ marginTop: '12px', display: 'flex', gap: '10px' }}>
            <button
              onClick={() => handleOpenEdit(selectedScheduleDetail)}
              style={{ padding: '6px 14px', background: '#3498db', border: 'none', borderRadius: '4px', color: 'white', cursor: 'pointer', fontSize: '12px', fontWeight: '600' }}
            >
              ✏️ Safe Edit / Patch
            </button>
            <button
              onClick={() => handleCancel(selectedScheduleDetail.id)}
              style={{ padding: '6px 14px', background: '#ff4757', border: 'none', borderRadius: '4px', color: 'white', cursor: 'pointer', fontSize: '12px', fontWeight: '600' }}
            >
              Cancel Schedule
            </button>
          </div>
        </div>
      )}

      {/* Safe Schedule Edit Modal / Form */}
      {editingSchedule && (
        <div className="glass-card" style={{ border: '1px solid #3498db', background: 'rgba(0,0,0,0.5)', padding: '16px' }}>
          <h3 style={{ margin: '0 0 12px 0', fontFamily: 'var(--font-heading)', fontSize: '15px' }}>
            ✏️ Patch Schedule: <code>{editingSchedule.id}</code>
          </h3>
          <div style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fit, minmax(180px, 1fr))', gap: '12px', marginBottom: '12px' }}>
            <label style={{ fontSize: '12px', color: 'var(--text-secondary)' }}>
              Status
              <select value={editForm.status} onChange={e => setEditForm({ ...editForm, status: e.target.value })} style={{ display: 'block', width: '100%', marginTop: '4px', padding: '6px', background: 'rgba(0,0,0,0.4)', border: '1px solid var(--border-glass)', borderRadius: '4px', color: 'white' }}>
                <option value="ACTIVE">ACTIVE</option>
                <option value="PAUSED">PAUSED</option>
              </select>
            </label>

            <label style={{ fontSize: '12px', color: 'var(--text-secondary)' }}>
              Target Tool ID
              <input value={editForm.target_tool_id} onChange={e => setEditForm({ ...editForm, target_tool_id: e.target.value })} style={{ display: 'block', width: '100%', marginTop: '4px', padding: '6px', background: 'rgba(0,0,0,0.4)', border: '1px solid var(--border-glass)', borderRadius: '4px', color: 'white' }} />
            </label>

            {editingSchedule.schedule_type === 'recurring' ? (
              <label style={{ fontSize: '12px', color: 'var(--text-secondary)' }}>
                Cron Expression
                <input value={editForm.cron_expression} onChange={e => setEditForm({ ...editForm, cron_expression: e.target.value })} style={{ display: 'block', width: '100%', marginTop: '4px', padding: '6px', background: 'rgba(0,0,0,0.4)', border: '1px solid var(--border-glass)', borderRadius: '4px', color: 'white' }} />
              </label>
            ) : (
              <label style={{ fontSize: '12px', color: 'var(--text-secondary)' }}>
                Run At
                <input value={editForm.run_at} onChange={e => setEditForm({ ...editForm, run_at: e.target.value })} style={{ display: 'block', width: '100%', marginTop: '4px', padding: '6px', background: 'rgba(0,0,0,0.4)', border: '1px solid var(--border-glass)', borderRadius: '4px', color: 'white' }} />
              </label>
            )}

            <label style={{ fontSize: '12px', color: 'var(--text-secondary)' }}>
              Timezone
              <input value={editForm.timezone} onChange={e => setEditForm({ ...editForm, timezone: e.target.value })} style={{ display: 'block', width: '100%', marginTop: '4px', padding: '6px', background: 'rgba(0,0,0,0.4)', border: '1px solid var(--border-glass)', borderRadius: '4px', color: 'white' }} />
            </label>

            <label style={{ fontSize: '12px', color: 'var(--text-secondary)' }}>
              Missed Policy
              <select value={editForm.missed_run_policy} onChange={e => setEditForm({ ...editForm, missed_run_policy: e.target.value })} style={{ display: 'block', width: '100%', marginTop: '4px', padding: '6px', background: 'rgba(0,0,0,0.4)', border: '1px solid var(--border-glass)', borderRadius: '4px', color: 'white' }}>
                <option value="run_once">Run once</option>
                <option value="skip">Skip</option>
                <option value="catch_up_limited">Catch up limited</option>
              </select>
            </label>
          </div>

          <label style={{ fontSize: '12px', color: 'var(--text-secondary)', display: 'block', marginBottom: '12px' }}>
            Target Payload JSON
            <textarea
              rows={3}
              value={editForm.target_payload_str}
              onChange={e => setEditForm({ ...editForm, target_payload_str: e.target.value })}
              style={{ display: 'block', width: '100%', marginTop: '4px', padding: '6px', background: 'rgba(0,0,0,0.4)', border: '1px solid var(--border-glass)', borderRadius: '4px', color: '#4ecdc4', fontFamily: 'monospace', fontSize: '12px' }}
            />
          </label>

          <div style={{ display: 'flex', gap: '10px' }}>
            <button onClick={handleSavePatchUpdate} style={{ padding: '8px 16px', background: '#2ecc71', border: 'none', borderRadius: '4px', color: 'white', fontWeight: '600', cursor: 'pointer' }}>
              Save Patch
            </button>
            <button onClick={() => setEditingSchedule(null)} style={{ padding: '8px 16px', background: '#666', border: 'none', borderRadius: '4px', color: 'white', cursor: 'pointer' }}>
              Cancel
            </button>
          </div>
        </div>
      )}

      {/* Schedules Section with Status Filtering */}
      <div>
        <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: '12px' }}>
          <h3 style={{ fontFamily: 'var(--font-heading)', fontSize: '16px', margin: 0 }}>📋 Registered Schedules</h3>
          <div style={{ display: 'flex', gap: '6px', alignItems: 'center' }}>
            <span style={{ fontSize: '12px', color: 'var(--text-secondary)' }}>Status Filter:</span>
            {['ALL', 'ACTIVE', 'PAUSED', 'CANCELLED'].map(st => (
              <button
                key={st}
                onClick={() => setScheduleStatusFilter(st)}
                style={{
                  padding: '4px 10px',
                  borderRadius: '4px',
                  border: 'none',
                  fontSize: '11px',
                  fontWeight: '600',
                  cursor: 'pointer',
                  background: scheduleStatusFilter === st ? 'var(--primary-glow)' : 'rgba(255,255,255,0.06)',
                  color: scheduleStatusFilter === st ? 'white' : 'var(--text-secondary)'
                }}
              >
                {st}
              </button>
            ))}
          </div>
        </div>

        {loading ? (
          <div style={{ padding: '32px', textAlign: 'center', color: 'var(--text-secondary)' }}>🌀 Loading schedules...</div>
        ) : schedules.length === 0 ? (
          <div className="glass-card" style={{ textAlign: 'center', padding: '32px', color: 'var(--text-secondary)', fontStyle: 'italic' }}>
            No schedules found matching filter '{scheduleStatusFilter}'.
          </div>
        ) : (
          <div style={{ display: 'flex', flexDirection: 'column', gap: '12px' }}>
            {schedules.map(schedule => (
              <div key={schedule.id} className="glass-card" style={{ display: 'flex', justifyContent: 'space-between', gap: '16px', alignItems: 'center', flexWrap: 'wrap' }}>
                <div>
                  <div style={{ display: 'flex', gap: '10px', alignItems: 'center', flexWrap: 'wrap' }}>
                    <strong><code>{schedule.id}</code></strong>
                    <StatusBadge status={schedule.status} />
                    <span style={{ fontSize: '12px', color: 'var(--text-secondary)' }}>{schedule.schedule_type}</span>
                  </div>
                  <div style={{ fontSize: '13px', color: 'var(--text-secondary)', marginTop: '4px' }}>
                    Target: <code>{schedule.target_tool_id}</code> | Timezone: {schedule.timezone} | Policy: {schedule.missed_run_policy}
                  </div>
                  <div style={{ fontSize: '12px', color: 'var(--text-secondary)', marginTop: '2px' }}>
                    Next: {schedule.next_run_at || '(none)'} | Last: {schedule.last_run_at || '(none)'} | {schedule.cron_expression ? `Cron: ${schedule.cron_expression}` : `Run at: ${schedule.run_at}`}
                  </div>
                </div>

                <div style={{ display: 'flex', gap: '8px' }}>
                  <button
                    onClick={() => handleInspectSchedule(schedule.id)}
                    style={{ padding: '6px 12px', background: 'rgba(255,255,255,0.08)', border: '1px solid var(--border-glass)', borderRadius: '4px', color: 'white', cursor: 'pointer', fontSize: '12px' }}
                  >
                    🔍 Details
                  </button>
                  <button
                    onClick={() => handleOpenEdit(schedule)}
                    style={{ padding: '6px 12px', background: '#3498db', border: 'none', borderRadius: '4px', color: 'white', cursor: 'pointer', fontSize: '12px' }}
                  >
                    ✏️ Edit
                  </button>
                  {schedule.status !== 'CANCELLED' && (
                    <button
                      onClick={() => handleCancel(schedule.id)}
                      style={{ padding: '6px 12px', background: '#ff4757', border: 'none', borderRadius: '4px', color: 'white', cursor: 'pointer', fontSize: '12px' }}
                    >
                      Cancel
                    </button>
                  )}
                </div>
              </div>
            ))}
          </div>
        )}
      </div>

      {/* Recent Run Attempts Section with Filtering */}
      <div className="glass-card">
        <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: '14px', flexWrap: 'wrap', gap: '10px' }}>
          <h3 style={{ margin: 0, fontFamily: 'var(--font-heading)', fontSize: '16px' }}>🏃 Recent Run Attempts</h3>
          <div style={{ display: 'flex', gap: '10px', alignItems: 'center', flexWrap: 'wrap' }}>
            <label style={{ fontSize: '12px', color: 'var(--text-secondary)' }}>
              Status:
              <select
                value={runStatusFilter}
                onChange={e => setRunStatusFilter(e.target.value)}
                style={{ marginLeft: '6px', padding: '4px 8px', background: 'rgba(0,0,0,0.3)', border: '1px solid var(--border-glass)', borderRadius: '4px', color: 'white', fontSize: '12px' }}
              >
                <option value="ALL">ALL</option>
                <option value="PENDING">PENDING</option>
                <option value="CLAIMED">CLAIMED</option>
                <option value="WAITING_FOR_APPROVAL">WAITING_FOR_APPROVAL</option>
                <option value="RUNNING">RUNNING</option>
                <option value="SUCCEEDED">SUCCEEDED</option>
                <option value="FAILED_RETRYABLE">FAILED_RETRYABLE</option>
                <option value="FAILED_TERMINAL">FAILED_TERMINAL</option>
                <option value="CANCELLED">CANCELLED</option>
              </select>
            </label>
            <label style={{ fontSize: '12px', color: 'var(--text-secondary)' }}>
              Schedule ID:
              <input
                type="text"
                value={runScheduleIdFilter}
                onChange={e => setRunScheduleIdFilter(e.target.value)}
                placeholder="Filter by ID"
                style={{ marginLeft: '6px', padding: '4px 8px', background: 'rgba(0,0,0,0.3)', border: '1px solid var(--border-glass)', borderRadius: '4px', color: 'white', fontSize: '12px', width: '120px' }}
              />
            </label>
          </div>
        </div>

        {runs.length === 0 ? (
          <div style={{ color: 'var(--text-secondary)', padding: '16px 0', textAlign: 'center', fontStyle: 'italic' }}>
            No run attempts match filter criteria.
          </div>
        ) : (
          <div style={{ display: 'flex', flexDirection: 'column', gap: '10px' }}>
            {runs.map(run => (
              <div key={run.id} style={{ borderTop: '1px solid var(--border-glass)', paddingTop: '10px' }}>
                <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: '4px' }}>
                  <div style={{ display: 'flex', gap: '8px', alignItems: 'center' }}>
                    <StatusBadge status={run.status} />
                    <span>Schedule: <code>{run.schedule_id}</code></span>
                  </div>
                  <span style={{ fontSize: '11px', color: 'var(--text-secondary)' }}>Scheduled for: {run.scheduled_for}</span>
                </div>
                <div style={{ fontSize: '12px', color: 'var(--text-secondary)' }}>
                  Run ID: <code>{run.id}</code> | Approval ID: <code>{run.approval_request_id || 'none'}</code> | Attempts: {run.attempt_count}
                </div>
                {run.result_preview && (
                  <div style={{ fontSize: '12px', marginTop: '4px', color: '#4ecdc4', background: 'rgba(0,0,0,0.2)', padding: '4px 8px', borderRadius: '4px' }}>
                    {run.result_preview}
                  </div>
                )}
              </div>
            ))}
          </div>
        )}
      </div>
    </div>
  );
}

if (typeof window !== 'undefined') {
  window.ScheduledCockpit = ScheduledCockpit;
}

