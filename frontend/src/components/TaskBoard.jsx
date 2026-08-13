import React, { useEffect, useState } from "react";
import { api } from "../api/client.js";
import PageHeader from "./ui/PageHeader.jsx";
import Notice from "./ui/Notice.jsx";
import Spinner from "./ui/Spinner.jsx";
import Badge from "./ui/Badge.jsx";

export default function TaskBoard({ onRefresh }) {
  const [tasks, setTasks] = useState([]);
  const [tasksSummary, setTasksSummary] = useState("");
  const [subAgents, setSubAgents] = useState([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState(null);

  const loadTasksData = async () => {
    setLoading(true);
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

  return (
    <div className="page">
      <PageHeader
        title="Tasks"
        subtitle={tasksSummary || "Local tasks and spawned sub-agents."}
        actions={<button className="btn btn-primary" onClick={() => { loadTasksData(); if (onRefresh) onRefresh(); }}>Refresh</button>}
      />
      {error ? <Notice kind="error">Error loading board: {error}</Notice> : null}
      {loading ? (
        <Spinner label="Loading tasks and sub-agents..." />
      ) : (
        <div className="kanban">
          <section className="glass-card">
            <div className="card-head"><h3>Tasks ({tasks.length})</h3></div>
            {tasks.length === 0 ? (
              <div className="lede">No internal tasks registered.</div>
            ) : (
              tasks.map((t, idx) => (
                <div key={t.id || idx} className="provider-card" style={{ marginBottom: 10 }}>
                  <div className="actions" style={{ justifyContent: "space-between" }}>
                    <strong>{t.title}</strong>
                    <Badge value={t.status} />
                  </div>
                  {t.description ? <div className="lede">{t.description}</div> : null}
                  <div className="lede">Priority: {t.priority || "Medium"}{t.created_at ? ` · Created: ${t.created_at}` : ""}</div>
                </div>
              ))
            )}
          </section>
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
        </div>
      )}
    </div>
  );
}

if (typeof window !== "undefined") {
  window.TaskBoard = TaskBoard;
}
