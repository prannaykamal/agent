import React, { useEffect, useState } from "react";
import { api } from "../api/client.js";
import PageHeader from "./ui/PageHeader.jsx";
import Notice from "./ui/Notice.jsx";
import Spinner from "./ui/Spinner.jsx";
import Badge from "./ui/Badge.jsx";

const COLUMNS = [
  { id: "PENDING", label: "Pending" },
  { id: "IN_PROGRESS", label: "In progress" },
  { id: "COMPLETED", label: "Done" },
  { id: "CANCELLED", label: "Cancelled" },
];

function normalizeStatus(status) {
  const value = String(status || "PENDING").toUpperCase();
  if (value === "RUNNING" || value === "STARTED") return "IN_PROGRESS";
  if (value === "DONE" || value === "COMPLETE") return "COMPLETED";
  if (value === "CANCELED") return "CANCELLED";
  if (COLUMNS.some((col) => col.id === value)) return value;
  return "PENDING";
}

export default function TaskBoard({ onRefresh }) {
  const [tasks, setTasks] = useState([]);
  const [tasksSummary, setTasksSummary] = useState("");
  const [subAgents, setSubAgents] = useState([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState(null);
  const [notice, setNotice] = useState(null);
  const [title, setTitle] = useState("");
  const [description, setDescription] = useState("");
  const [priority, setPriority] = useState("Medium");
  const [busy, setBusy] = useState(false);

  const loadTasksData = async ({ silent = false } = {}) => {
    if (!silent) setLoading(true);
    setError(null);
    try {
      const data = await api.get("/api/tasks");
      setTasks(data.tasks || []);
      setTasksSummary(data.tasks_summary || "");
      setSubAgents(data.sub_agents || []);
    } catch (e) {
      setError(e.message || "Failed to load tasks");
    } finally {
      setLoading(false);
    }
  };

  useEffect(() => {
    loadTasksData();
  }, []);

  const handleCreate = async (e) => {
    e.preventDefault();
    if (!title.trim()) return;
    setBusy(true);
    setError(null);
    setNotice(null);
    try {
      const data = await api.post("/api/tasks", { title: title.trim(), description, priority });
      setNotice(data.result || "Task created.");
      setTitle("");
      setDescription("");
      await loadTasksData({ silent: true });
      if (onRefresh) onRefresh();
    } catch (err) {
      setError(err.message || "Failed to create task");
    } finally {
      setBusy(false);
    }
  };

  const handleUpdate = async (taskId, status, progress) => {
    setBusy(true);
    setError(null);
    try {
      await api.patch(`/api/tasks/${taskId}`, { status, progress });
      await loadTasksData({ silent: true });
    } catch (err) {
      setError(err.message || "Failed to update task");
    } finally {
      setBusy(false);
    }
  };

  const grouped = COLUMNS.reduce((acc, col) => {
    acc[col.id] = tasks.filter((task) => normalizeStatus(task.status) === col.id);
    return acc;
  }, {});

  return (
    <div className="page">
      <PageHeader
        title="Tasks"
        subtitle={tasksSummary || "Local tasks and spawned sub-agents."}
        actions={<button className="btn btn-primary" onClick={() => { loadTasksData(); if (onRefresh) onRefresh(); }}>Refresh</button>}
      />
      {error ? <Notice kind="error">Error loading board: {error}</Notice> : null}
      {notice ? <Notice kind="ok">{notice}</Notice> : null}

      <section className="glass-card">
        <div className="card-head"><h3>New task</h3></div>
        <form onSubmit={handleCreate} className="form-grid" style={{ marginTop: 12 }}>
          <label className="field">Title<input value={title} onChange={(e) => setTitle(e.target.value)} placeholder="Prepare Independence Day note" /></label>
          <label className="field">Priority
            <select value={priority} onChange={(e) => setPriority(e.target.value)}>
              <option>High</option>
              <option>Medium</option>
              <option>Low</option>
            </select>
          </label>
          <label className="field" style={{ gridColumn: "1 / -1" }}>Description<input value={description} onChange={(e) => setDescription(e.target.value)} /></label>
          <button type="submit" className="btn btn-primary" disabled={busy || !title.trim()}>Create task</button>
        </form>
      </section>

      {loading && tasks.length === 0 ? (
        <Spinner label="Loading tasks and sub-agents..." />
      ) : (
        <>
          <div className="kanban">
            {COLUMNS.map((col) => (
              <section key={col.id} className="glass-card kanban-col">
                <div className="card-head">
                  <h3>{col.label}</h3>
                  <span className="lede">{grouped[col.id].length}</span>
                </div>
                {grouped[col.id].length === 0 ? (
                  <div className="lede">No {col.label.toLowerCase()} tasks.</div>
                ) : (
                  grouped[col.id].map((t, idx) => (
                    <div key={t.id || idx} className="provider-card" style={{ marginBottom: 10 }}>
                      <div className="actions" style={{ justifyContent: "space-between" }}>
                        <strong>{t.title}</strong>
                        <Badge value={t.status} />
                      </div>
                      {t.description ? <div className="lede">{t.description}</div> : null}
                      <div className="lede">Priority: {t.priority || "Medium"}{typeof t.progress === "number" ? ` · ${t.progress}%` : ""}{t.created_at ? ` · ${t.created_at}` : ""}</div>
                      <div className="actions" style={{ marginTop: 8 }}>
                        {normalizeStatus(t.status) === "PENDING" ? (
                          <button className="btn btn-sm" disabled={busy} onClick={() => handleUpdate(t.id, "IN_PROGRESS", 50)}>Start</button>
                        ) : null}
                        {normalizeStatus(t.status) !== "COMPLETED" && normalizeStatus(t.status) !== "CANCELLED" ? (
                          <button className="btn btn-sm btn-ok" disabled={busy} onClick={() => handleUpdate(t.id, "COMPLETED", 100)}>Complete</button>
                        ) : null}
                        {normalizeStatus(t.status) !== "CANCELLED" && normalizeStatus(t.status) !== "COMPLETED" ? (
                          <button className="btn btn-sm btn-danger" disabled={busy} onClick={() => handleUpdate(t.id, "CANCELLED", 0)}>Cancel</button>
                        ) : null}
                      </div>
                    </div>
                  ))
                )}
              </section>
            ))}
          </div>
          <section className="glass-card">
            <div className="card-head"><h3>Sub-agents ({subAgents.length})</h3></div>
            {subAgents.length === 0 ? (
              <div className="lede">No sub-agents currently active.</div>
            ) : (
              subAgents.map((ag, i) => (
                <div key={ag.agent_id || i} className="provider-card" style={{ marginBottom: 10 }}>
                  <div className="actions" style={{ justifyContent: "space-between" }}>
                    <strong>{ag.role}</strong>
                    <Badge value={ag.status} />
                  </div>
                  <div className="lede">ID: {ag.agent_id}</div>
                  <div>{ag.instructions}</div>
                </div>
              ))
            )}
          </section>
        </>
      )}
    </div>
  );
}

if (typeof window !== "undefined") {
  window.TaskBoard = TaskBoard;
}
