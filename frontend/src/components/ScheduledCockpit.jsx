import React, { useEffect, useState } from "react";
import { api } from "../api/client.js";
import PageHeader from "./ui/PageHeader.jsx";
import Notice from "./ui/Notice.jsx";
import Spinner from "./ui/Spinner.jsx";
import EmptyState from "./ui/EmptyState.jsx";
import Badge from "./ui/Badge.jsx";

function StatusBadge({ status }) {
  return <Badge value={status} />;
}

export default function ScheduledCockpit({ onRefresh }) {
  const [schedules, setSchedules] = useState([]);
  const [runs, setRuns] = useState([]);
  const [scheduleStatusFilter, setScheduleStatusFilter] = useState("ALL");
  const [runStatusFilter, setRunStatusFilter] = useState("ALL");
  const [runScheduleIdFilter, setRunScheduleIdFilter] = useState("");
  const [scheduleType, setScheduleType] = useState("one_time");
  const [runAt, setRunAt] = useState("");
  const [cronExpression, setCronExpression] = useState("0 9 * * *");
  const [timezone, setTimezone] = useState("UTC");
  const [targetTool, setTargetTool] = useState("heartbeat");
  const [payloadInput, setPayloadInput] = useState("{}");
  const [missedPolicy, setMissedPolicy] = useState("run_once");
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
      let schedUrl = "/api/tools/cron/schedules";
      if (scheduleStatusFilter !== "ALL") schedUrl += `?status=${encodeURIComponent(scheduleStatusFilter)}`;
      let runUrl = "/api/tools/cron/runs?limit=20";
      if (runStatusFilter !== "ALL") runUrl += `&status=${encodeURIComponent(runStatusFilter)}`;
      if (runScheduleIdFilter.trim()) runUrl += `&schedule_id=${encodeURIComponent(runScheduleIdFilter.trim())}`;
      const [scheduleRes, runRes] = await Promise.allSettled([api.get(schedUrl), api.get(runUrl)]);
      const scheduleData = scheduleRes.status === "fulfilled" ? scheduleRes.value : null;
      const runData = runRes.status === "fulfilled" ? runRes.value : null;
      setSchedules(scheduleData?.schedules || []);
      setRuns(runData?.runs || []);
      if (!scheduleData && !runData) {
        setError("Failed to load schedules");
      } else if (!scheduleData || !runData) {
        setError("Part of the scheduled jobs view could not load.");
      }
    } catch (e) {
      setError(e.message || "Failed to load schedules");
    } finally {
      setLoading(false);
    }
  };

  useEffect(() => {
    fetchScheduled();
  }, [scheduleStatusFilter, runStatusFilter, runScheduleIdFilter]);

  const parsePayload = (inputStr) => {
    try { return JSON.parse(inputStr || "{}"); } catch { return { text: inputStr }; }
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
        max_catchup_runs: 1,
      };
      if (scheduleType === "one_time") body.run_at = runAt;
      if (scheduleType === "recurring") body.cron_expression = cronExpression;
      const data = await api.post("/api/tools/cron/schedules", body);
      setRunAt("");
      setActionNotice(`Schedule '${data.schedule?.id || "created"}' successfully registered.`);
      fetchScheduled();
      if (onRefresh) onRefresh();
    } catch (e) {
      setError(e.message || "Failed to create schedule");
    }
  };

  const handleInspectSchedule = async (id) => {
    setError(null);
    try {
      const data = await api.get(`/api/tools/cron/schedules/${id}`);
      setSelectedScheduleDetail(data.schedule);
    } catch (e) {
      setError(`Failed to inspect schedule: ${e.message}`);
    }
  };

  const handleOpenEdit = (schedule) => {
    setEditingSchedule(schedule);
    setEditForm({
      status: schedule.status,
      target_tool_id: schedule.target_tool_id,
      cron_expression: schedule.cron_expression || "",
      run_at: schedule.run_at || "",
      timezone: schedule.timezone || "UTC",
      missed_run_policy: schedule.missed_run_policy || "run_once",
      target_payload_str: JSON.stringify(schedule.target_payload || {}, null, 2),
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
      if (editingSchedule.schedule_type === "recurring" && editForm.cron_expression) patchBody.cron_expression = editForm.cron_expression;
      if (editingSchedule.schedule_type === "one_time" && editForm.run_at) patchBody.run_at = editForm.run_at;
      if (editForm.target_payload_str) patchBody.target_payload = parsePayload(editForm.target_payload_str);
      const resData = await api.patch(`/api/tools/cron/schedules/${editingSchedule.id}`, patchBody);
      setActionNotice(`Schedule '${editingSchedule.id}' updated successfully.`);
      setEditingSchedule(null);
      if (selectedScheduleDetail && selectedScheduleDetail.id === editingSchedule.id) {
        setSelectedScheduleDetail(resData.schedule);
      }
      fetchScheduled();
      if (onRefresh) onRefresh();
    } catch (e) {
      setError(`Update failed: ${e.message}`);
    }
  };

  const handleCancel = async (id) => {
    setError(null);
    setActionNotice(null);
    try {
      await api.delete(`/api/tools/cron/schedules/${id}`);
      setActionNotice(`Schedule '${id}' cancelled.`);
      if (selectedScheduleDetail && selectedScheduleDetail.id === id) setSelectedScheduleDetail(null);
      fetchScheduled();
      if (onRefresh) onRefresh();
    } catch (e) {
      setError(e.message || "Failed to cancel schedule");
    }
  };

  return (
    <div className="page">
      <PageHeader
        title="Scheduled"
        subtitle="One-time and recurring jobs."
        actions={<button className="btn btn-primary" onClick={() => { fetchScheduled(); if (onRefresh) onRefresh(); }}>Refresh</button>}
      />

      {actionNotice ? <Notice kind="ok">{actionNotice}</Notice> : null}
      {error ? <Notice kind="error">{error}</Notice> : null}

      <section className="glass-card">
        <h3>New schedule</h3>
        <div className="form-grid" style={{ marginTop: 12 }}>
          <label className="field">Schedule Type
            <select value={scheduleType} onChange={(e) => setScheduleType(e.target.value)}>
              <option value="one_time">One-time</option>
              <option value="recurring">Recurring</option>
            </select>
          </label>
          {scheduleType === "one_time" ? (
            <label className="field">Run At (UTC / ISO)
              <input value={runAt} onChange={(e) => setRunAt(e.target.value)} placeholder="2026-08-12 10:00" />
            </label>
          ) : (
            <label className="field">Cron Expression
              <input value={cronExpression} onChange={(e) => setCronExpression(e.target.value)} placeholder="0 9 * * *" />
            </label>
          )}
          <label className="field">Timezone<input value={timezone} onChange={(e) => setTimezone(e.target.value)} /></label>
          <label className="field">Target Tool ID<input value={targetTool} onChange={(e) => setTargetTool(e.target.value)} /></label>
          <label className="field">Payload JSON<input value={payloadInput} onChange={(e) => setPayloadInput(e.target.value)} /></label>
          <label className="field">Missed Policy
            <select value={missedPolicy} onChange={(e) => setMissedPolicy(e.target.value)}>
              <option value="run_once">Run once</option>
              <option value="skip">Skip</option>
              <option value="catch_up_limited">Catch up limited</option>
            </select>
          </label>
          <button className="btn btn-primary" onClick={handleCreateSchedule}>Submit Schedule</button>
        </div>
      </section>

      {selectedScheduleDetail ? (
        <section className="glass-card">
          <div className="card-head">
            <h3>Details: <code>{selectedScheduleDetail.id}</code></h3>
            <div className="actions">
              <StatusBadge status={selectedScheduleDetail.status} />
              <button className="btn btn-ghost btn-sm" onClick={() => setSelectedScheduleDetail(null)}>Close</button>
            </div>
          </div>
          <div className="provider-grid">
            <div>Type: <strong>{selectedScheduleDetail.schedule_type}</strong></div>
            <div>Target Tool: <code>{selectedScheduleDetail.target_tool_id}</code></div>
            <div>Timezone: <strong>{selectedScheduleDetail.timezone}</strong></div>
            <div>Missed Policy: <strong>{selectedScheduleDetail.missed_run_policy}</strong></div>
            <div>Next Run: <strong>{selectedScheduleDetail.next_run_at || "None"}</strong></div>
            <div>Last Run: <strong>{selectedScheduleDetail.last_run_at || "None"}</strong></div>
            <div>Timing: <strong>{selectedScheduleDetail.cron_expression ? `Cron: ${selectedScheduleDetail.cron_expression}` : `Run At: ${selectedScheduleDetail.run_at}`}</strong></div>
          </div>
          <pre className="json-block">{JSON.stringify(selectedScheduleDetail.target_payload || {}, null, 2)}</pre>
          <div className="actions" style={{ marginTop: 12 }}>
            <button className="btn btn-primary btn-sm" onClick={() => handleOpenEdit(selectedScheduleDetail)}>Safe Edit / Patch</button>
            <button className="btn btn-danger btn-sm" onClick={() => handleCancel(selectedScheduleDetail.id)}>Cancel Schedule</button>
          </div>
        </section>
      ) : null}

      {editingSchedule ? (
        <section className="glass-card">
          <h3>Edit: <code>{editingSchedule.id}</code></h3>
          <div className="form-grid" style={{ marginTop: 12 }}>
            <label className="field">Status
              <select value={editForm.status} onChange={(e) => setEditForm({ ...editForm, status: e.target.value })}>
                <option value="ACTIVE">ACTIVE</option>
                <option value="PAUSED">PAUSED</option>
              </select>
            </label>
            <label className="field">Target Tool ID<input value={editForm.target_tool_id} onChange={(e) => setEditForm({ ...editForm, target_tool_id: e.target.value })} /></label>
            {editingSchedule.schedule_type === "recurring" ? (
              <label className="field">Cron Expression<input value={editForm.cron_expression} onChange={(e) => setEditForm({ ...editForm, cron_expression: e.target.value })} /></label>
            ) : (
              <label className="field">Run At<input value={editForm.run_at} onChange={(e) => setEditForm({ ...editForm, run_at: e.target.value })} /></label>
            )}
            <label className="field">Timezone<input value={editForm.timezone} onChange={(e) => setEditForm({ ...editForm, timezone: e.target.value })} /></label>
            <label className="field">Missed Policy
              <select value={editForm.missed_run_policy} onChange={(e) => setEditForm({ ...editForm, missed_run_policy: e.target.value })}>
                <option value="run_once">Run once</option>
                <option value="skip">Skip</option>
                <option value="catch_up_limited">Catch up limited</option>
              </select>
            </label>
          </div>
          <label className="field" style={{ marginTop: 12 }}>Target Payload JSON
            <textarea rows={3} value={editForm.target_payload_str} onChange={(e) => setEditForm({ ...editForm, target_payload_str: e.target.value })} />
          </label>
          <div className="actions" style={{ marginTop: 12 }}>
            <button className="btn btn-ok" onClick={handleSavePatchUpdate}>Save Patch</button>
            <button className="btn btn-ghost" onClick={() => setEditingSchedule(null)}>Cancel</button>
          </div>
        </section>
      ) : null}

      <section>
        <div className="page-header">
          <h3>Schedules</h3>
          <div className="chip-row">
            {["ALL", "ACTIVE", "PAUSED", "CANCELLED"].map((st) => (
              <button key={st} className={`tab ${scheduleStatusFilter === st ? "active" : ""}`} onClick={() => setScheduleStatusFilter(st)}>{st}</button>
            ))}
          </div>
        </div>
        {loading ? (
          <Spinner label="Loading schedules..." />
        ) : schedules.length === 0 ? (
          <EmptyState body={`No schedules found matching filter '${scheduleStatusFilter}'.`} />
        ) : (
          schedules.map((schedule) => (
            <article key={schedule.id} className="glass-card" style={{ marginBottom: 12 }}>
              <div className="row-card" style={{ border: 0, padding: 0 }}>
                <div>
                  <div className="chip-row">
                    <strong><code>{schedule.id}</code></strong>
                    <StatusBadge status={schedule.status} />
                    <span className="lede">{schedule.schedule_type}</span>
                  </div>
                  <div className="lede">Target: <code>{schedule.target_tool_id}</code> | Timezone: {schedule.timezone} | Policy: {schedule.missed_run_policy}</div>
                  <div className="lede">Next: {schedule.next_run_at || "(none)"} | Last: {schedule.last_run_at || "(none)"} | {schedule.cron_expression ? `Cron: ${schedule.cron_expression}` : `Run at: ${schedule.run_at}`}</div>
                </div>
                <div className="actions">
                  <button className="btn btn-ghost btn-sm" onClick={() => handleInspectSchedule(schedule.id)}>Details</button>
                  <button className="btn btn-primary btn-sm" onClick={() => handleOpenEdit(schedule)}>Edit</button>
                  {schedule.status !== "CANCELLED" ? <button className="btn btn-danger btn-sm" onClick={() => handleCancel(schedule.id)}>Cancel</button> : null}
                </div>
              </div>
            </article>
          ))
        )}
      </section>

      <section className="glass-card">
        <div className="card-head">
          <h3>Recent runs</h3>
          <div className="actions">
            <label className="field">Status
              <select value={runStatusFilter} onChange={(e) => setRunStatusFilter(e.target.value)}>
                {["ALL", "PENDING", "CLAIMED", "WAITING_FOR_APPROVAL", "RUNNING", "SUCCEEDED", "FAILED_RETRYABLE", "FAILED_TERMINAL", "CANCELLED"].map((st) => (
                  <option key={st} value={st}>{st}</option>
                ))}
              </select>
            </label>
            <label className="field">Schedule ID
              <input value={runScheduleIdFilter} onChange={(e) => setRunScheduleIdFilter(e.target.value)} placeholder="Filter by ID" />
            </label>
          </div>
        </div>
        {runs.length === 0 ? (
          <div className="lede">No run attempts match filter criteria.</div>
        ) : (
          runs.map((run) => (
            <div key={run.id} className="row-card">
              <div>
                <div className="chip-row">
                  <StatusBadge status={run.status} />
                  <span>Schedule: <code>{run.schedule_id}</code></span>
                </div>
                <div className="lede">Run ID: <code>{run.id}</code> | Approval ID: <code>{run.approval_request_id || "none"}</code> | Attempts: {run.attempt_count}</div>
                {run.result_preview ? <pre className="json-block">{run.result_preview}</pre> : null}
              </div>
              <span className="lede">{run.scheduled_for}</span>
            </div>
          ))
        )}
      </section>
    </div>
  );
}

if (typeof window !== "undefined") {
  window.ScheduledCockpit = ScheduledCockpit;
}
