import React, { useState, useEffect } from 'react';

export default function ScheduledCockpit({ onRefresh }) {
  const [scheduledJobs, setScheduledJobs] = useState([]);
  const [cronInput, setCronInput] = useState("");
  const [payloadInput, setPayloadInput] = useState("");
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState(null);

  const fetchScheduled = async () => {
    setLoading(true);
    setError(null);
    try {
      const res = await fetch("/api/scheduled");
      if (!res.ok) throw new Error(`HTTP error ${res.status}`);
      const data = await res.json();
      setScheduledJobs(data.scheduled_jobs || []);
    } catch (e) {
      console.error(e);
      setError(e.message || "Failed to load scheduled jobs");
    } finally {
      setLoading(false);
    }
  };

  useEffect(() => {
    fetchScheduled();
  }, []);

  const handleCreateJob = async () => {
    if (!cronInput.trim() || !payloadInput.trim()) return;
    try {
      const res = await fetch("/api/scheduled", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ cron_or_timestamp: cronInput, task_payload: payloadInput })
      });
      if (res.ok) {
        setCronInput("");
        setPayloadInput("");
        fetchScheduled();
        if (onRefresh) onRefresh();
      }
    } catch (e) {
      console.error(e);
    }
  };

  const handleDeleteJob = async (id) => {
    try {
      const res = await fetch(`/api/scheduled/${id}`, { method: "DELETE" });
      if (res.ok) {
        fetchScheduled();
        if (onRefresh) onRefresh();
      }
    } catch (e) {
      console.error(e);
    }
  };

  return (
    <div style={{ display: "flex", flexDirection: "column", gap: "20px" }}>
      <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center" }}>
        <h2 style={{ fontFamily: "var(--font-heading)", margin: 0 }}>⏱️ Scheduled Jobs & Cron Operations</h2>
        <button
          onClick={() => { fetchScheduled(); if (onRefresh) onRefresh(); }}
          style={{ padding: "8px 16px", background: "var(--primary-glow)", border: "none", borderRadius: "6px", color: "white", cursor: "pointer" }}
        >
          🔄 Refresh
        </button>
      </div>

      <div className="glass-card" style={{ display: "flex", gap: "12px", alignItems: "center" }}>
        <input
          type="text"
          value={cronInput}
          onChange={e => setCronInput(e.target.value)}
          placeholder="Cron or Timestamp (e.g. */5 * * * * or 2026-08-01 10:00)"
          style={{ flex: 1, padding: "10px 14px", background: "rgba(0,0,0,0.3)", border: "1px solid var(--border-glass)", borderRadius: "6px", color: "white" }}
        />
        <input
          type="text"
          value={payloadInput}
          onChange={e => setPayloadInput(e.target.value)}
          placeholder="Task Payload Description"
          style={{ flex: 1, padding: "10px 14px", background: "rgba(0,0,0,0.3)", border: "1px solid var(--border-glass)", borderRadius: "6px", color: "white" }}
        />
        <button onClick={handleCreateJob} style={{ padding: "10px 20px", background: "var(--primary-glow)", border: "none", borderRadius: "6px", color: "white", fontWeight: "600", cursor: "pointer" }}>
          + Schedule Job
        </button>
      </div>

      {error && (
        <div style={{ padding: "12px", background: "rgba(255, 50, 50, 0.15)", borderRadius: "8px", color: "#ff6b6b" }}>
          ⚠️ Error: {error}
        </div>
      )}

      {loading ? (
        <div style={{ padding: "32px", textAlign: "center", color: "var(--text-secondary)" }}>🌀 Loading scheduled jobs...</div>
      ) : scheduledJobs.length === 0 ? (
        <div className="glass-card" style={{ textAlign: "center", padding: "48px", color: "var(--text-secondary)", fontStyle: "italic" }}>
          📭 No active or pending scheduled jobs registered.
        </div>
      ) : (
        <div style={{ display: "flex", flexDirection: "column", gap: "12px" }}>
          {scheduledJobs.map(job => (
            <div key={job.id} className="glass-card" style={{ display: "flex", justifyContent: "space-between", alignItems: "center" }}>
              <div>
                <div style={{ display: "flex", gap: "10px", alignItems: "center" }}>
                  <strong>ID: {job.id}</strong>
                  <span className="retrieval-badge">{job.status}</span>
                </div>
                <div style={{ fontSize: "13px", marginTop: "4px", color: "var(--text-secondary)" }}>Schedule: {job.cron_or_timestamp}</div>
                <div style={{ fontSize: "14px", marginTop: "6px" }}>Payload: {job.task_payload}</div>
              </div>
              <button onClick={() => handleDeleteJob(job.id)} style={{ padding: "6px 12px", background: "#ff4757", border: "none", borderRadius: "4px", color: "white", cursor: "pointer" }}>
                Cancel
              </button>
            </div>
          ))}
        </div>
      )}
    </div>
  );
}

if (typeof window !== "undefined") {
  window.ScheduledCockpit = ScheduledCockpit;
}
