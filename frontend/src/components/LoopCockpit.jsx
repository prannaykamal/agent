import React, { useState, useEffect } from 'react';

export default function LoopCockpit({ activeSessionId, onRefresh }) {
  const [events, setEvents] = useState([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState(null);

  const loadLoopTrace = async () => {
    setLoading(true);
    setError(null);
    try {
      const sess = activeSessionId || "default_session";
      let res = await fetch(`/api/history/${sess}`);
      if (!res.ok) {
        res = await fetch(`/api/loop/events/${sess}`);
      }
      if (!res.ok) {
        let errDetail = `HTTP error ${res.status}`;
        try {
          const errData = await res.json();
          if (errData && errData.detail) errDetail = errData.detail;
        } catch (_) {}

        if (res.status >= 500) {
          errDetail = `Backend server error (${res.status}). Ensure the FastAPI backend is running on port 8000 (python src/api/server.py). (${errDetail})`;
        }
        throw new Error(errDetail);
      }
      const data = await res.json();
      setEvents(data.loop_trace || data.loop_events || []);
    } catch (e) {
      console.error(e);
      setError(e.message || "Failed to load loop events");
    } finally {
      setLoading(false);
    }
  };


  useEffect(() => {
    loadLoopTrace();
  }, [activeSessionId]);

  return (
    <div style={{ display: "flex", flexDirection: "column", gap: "20px" }}>
      <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center" }}>
        <h2 style={{ fontFamily: "var(--font-heading)", margin: 0 }}>🔁 Step-By-Step Agent Loop Timeline</h2>
        <button
          onClick={() => { loadLoopTrace(); if (onRefresh) onRefresh(); }}
          style={{ padding: "8px 16px", background: "var(--primary-glow)", border: "none", borderRadius: "6px", color: "white", cursor: "pointer" }}
        >
          🔄 Refresh
        </button>
      </div>

      {error && (
        <div style={{ padding: "12px", background: "rgba(255, 50, 50, 0.15)", borderRadius: "8px", color: "#ff6b6b" }}>
          ⚠️ Error loading loop events: {error}
        </div>
      )}

      {loading ? (
        <div style={{ padding: "32px", textAlign: "center", color: "var(--text-secondary)" }}>🌀 Loading loop trace...</div>
      ) : events.length === 0 ? (
        <div className="glass-card" style={{ textAlign: "center", padding: "48px", color: "var(--text-secondary)", fontStyle: "italic" }}>
          📭 No loop events recorded for this session.
        </div>
      ) : (
        <div style={{ display: "flex", flexDirection: "column", gap: "12px" }}>
          {events.map((ev, idx) => (
            <div key={idx} className="glass-card" style={{ display: "flex", flexDirection: "column", gap: "6px" }}>
              <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center" }}>
                <strong style={{ color: "#4ecdc4" }}>Step #{idx + 1} - {ev.step_type || ev.sender || "EVENT"}</strong>
                {ev.created_at && <span style={{ fontSize: "12px", color: "var(--text-secondary)" }}>{ev.created_at}</span>}
              </div>
              <div style={{ fontSize: "14px", color: "var(--text-primary)" }}>{ev.reasoning || ev.content || ev.text}</div>
              {ev.tool_name && (
                <div style={{ fontSize: "12px", color: "#a8ff78" }}>⚙️ Tool: {ev.tool_name}</div>
              )}
            </div>
          ))}
        </div>
      )}
    </div>
  );
}

if (typeof window !== "undefined") {
  window.LoopCockpit = LoopCockpit;
}
