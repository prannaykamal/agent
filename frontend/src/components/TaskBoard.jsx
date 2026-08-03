import React, { useState, useEffect } from 'react';

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
      const res = await fetch("/api/tasks");
      if (!res.ok) throw new Error(`HTTP error ${res.status}`);
      const data = await res.json();
      setTasks(data.tasks || []);
      setTasksSummary(data.tasks_summary || "");
      setSubAgents(data.sub_agents || []);
    } catch (e) {
      console.error(e);
      setError(e.message || "Failed to load tasks");
    } finally {
      setLoading(false);
    }
  };

  useEffect(() => {
    loadTasksData();
  }, []);

  return (
    <div style={{ display: "flex", flexDirection: "column", gap: "20px" }}>
      <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center" }}>
        <h2 style={{ fontFamily: "var(--font-heading)", margin: 0 }}>📋 Personal OS Task & Sub-Agent Board</h2>
        <button 
          onClick={() => { loadTasksData(); if (onRefresh) onRefresh(); }} 
          style={{ padding: "8px 16px", background: "var(--primary-glow)", border: "none", borderRadius: "6px", color: "white", cursor: "pointer" }}
        >
          🔄 Refresh
        </button>
      </div>

      {error && (
        <div style={{ padding: "12px", background: "rgba(255, 50, 50, 0.15)", border: "1px solid rgba(255, 50, 50, 0.3)", borderRadius: "8px", color: "#ff6b6b" }}>
          ⚠️ Error loading board: {error}
        </div>
      )}

      {loading ? (
        <div style={{ padding: "32px", textAlign: "center", color: "var(--text-secondary)" }}>
          🌀 Loading tasks and sub-agents...
        </div>
      ) : (
        <div style={{ display: "grid", gridTemplateColumns: "1fr 1fr", gap: "24px" }}>
          {/* Internal Tasks Column */}
          <div className="glass-card">
            <h3 style={{ fontFamily: "var(--font-heading)", marginBottom: "16px" }}>📋 Registered Tasks ({tasks.length})</h3>
            {tasks.length === 0 ? (
              <div style={{ color: "var(--text-secondary)", fontSize: "14px", fontStyle: "italic", padding: "16px 0" }}>
                📭 No internal tasks registered.
              </div>
            ) : (
              <div style={{ display: "flex", flexDirection: "column", gap: "10px" }}>
                {tasks.map((t, idx) => (
                  <div key={t.id || idx} style={{ padding: "12px", background: "rgba(255,255,255,0.03)", borderRadius: "8px", border: "1px solid var(--border-glass)" }}>
                    <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center" }}>
                      <strong>{t.title}</strong>
                      <span className="retrieval-badge" style={{ background: t.status === 'COMPLETED' ? 'rgba(50,255,100,0.15)' : 'rgba(255,180,0,0.15)' }}>
                        {t.status}
                      </span>
                    </div>
                    {t.description && <div style={{ fontSize: "13px", color: "var(--text-secondary)", marginTop: "6px" }}>{t.description}</div>}
                    <div style={{ display: "flex", gap: "12px", fontSize: "11px", color: "var(--text-secondary)", marginTop: "8px" }}>
                      <span>Priority: {t.priority || 'Medium'}</span>
                      {t.created_at && <span>Created: {t.created_at}</span>}
                    </div>
                  </div>
                ))}
              </div>
            )}
          </div>

          {/* Sub-Agents Column */}
          <div className="glass-card">
            <h3 style={{ fontFamily: "var(--font-heading)", marginBottom: "16px" }}>🤖 Spawned Sub-Agents ({subAgents.length})</h3>
            {subAgents.length === 0 ? (
              <div style={{ color: "var(--text-secondary)", fontSize: "14px", fontStyle: "italic", padding: "16px 0" }}>
                📭 No sub-agents currently active.
              </div>
            ) : (
              <div style={{ display: "flex", flexDirection: "column", gap: "12px" }}>
                {subAgents.map((ag, i) => (
                  <div key={ag.agent_id || i} style={{ padding: "12px", background: "rgba(255,255,255,0.03)", borderRadius: "8px", border: "1px solid var(--border-glass)" }}>
                    <div style={{ display: "flex", justifyContent: "space-between" }}>
                      <strong>{ag.role}</strong>
                      <span className="retrieval-badge">{ag.status}</span>
                    </div>
                    <div style={{ fontSize: "12px", color: "var(--text-secondary)", marginTop: "4px" }}>ID: {ag.agent_id}</div>
                    <div style={{ fontSize: "13px", marginTop: "6px" }}>{ag.instructions}</div>
                  </div>
                ))}
              </div>
            )}
          </div>
        </div>
      )}
    </div>
  );
}

if (typeof window !== "undefined") {
  window.TaskBoard = TaskBoard;
}
