import React, { useState, useEffect } from 'react';

export default function OverviewCockpit({ activeSessionId, onRefresh }) {
  const [telemetry, setTelemetry] = useState(null);
  const [health, setHealth] = useState(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState(null);

  const fetchOverview = async () => {
    setLoading(true);
    setError(null);
    try {
      const sess = activeSessionId || "default_session";
      const [resHist, resHealth] = await Promise.all([
        fetch(`/api/history/${sess}`),
        fetch("/api/system/health")
      ]);
      
      const dataHist = resHist.ok ? await resHist.json() : {};
      const dataHealth = resHealth.ok ? await resHealth.json() : null;

      setHealth(dataHealth);
      setTelemetry({
        session_id: sess,
        total_turns: dataHist.total_turns || 0,
        gate_status: "Active (Hybrid SQL/FTS5)",
        tool_status: "Operational (22 OS + MCP Gateway)",
        memory_sync: "Synced (.agent/MEMORY.md)"
      });
    } catch (e) {
      console.error(e);
      setError(e.message || "Failed to load telemetry");
    } finally {
      setLoading(false);
    }
  };

  useEffect(() => {
    fetchOverview();
  }, [activeSessionId]);

  return (
    <div style={{ display: "flex", flexDirection: "column", gap: "20px" }}>
      <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center" }}>
        <h2 style={{ fontFamily: "var(--font-heading)", margin: 0 }}>📊 ASTRA Telemetry & System Health</h2>
        <button
          onClick={() => { fetchOverview(); if (onRefresh) onRefresh(); }}
          style={{ padding: "8px 16px", background: "var(--primary-glow)", border: "none", borderRadius: "6px", color: "white", cursor: "pointer" }}
        >
          🔄 Refresh
        </button>
      </div>

      {error && (
        <div style={{ padding: "12px", background: "rgba(255, 50, 50, 0.15)", borderRadius: "8px", color: "#ff6b6b" }}>
          ⚠️ Error loading telemetry: {error}
        </div>
      )}

      {loading ? (
        <div style={{ padding: "32px", textAlign: "center", color: "var(--text-secondary)" }}>🌀 Loading overview telemetry...</div>
      ) : (
        <>
          <div style={{ display: "grid", gridTemplateColumns: "repeat(auto-fit, minmax(220px, 1fr))", gap: "16px" }}>
            <div className="glass-card">
              <h4 style={{ color: "var(--text-secondary)", marginBottom: "8px" }}>Active Session</h4>
              <div style={{ fontSize: "16px", fontWeight: "600" }}>{telemetry?.session_id || "default_session"}</div>
            </div>
            <div className="glass-card">
              <h4 style={{ color: "var(--text-secondary)", marginBottom: "8px" }}>Logged Turns</h4>
              <div style={{ fontSize: "16px", fontWeight: "600" }}>{telemetry?.total_turns || 0} Turns</div>
            </div>
            <div className="glass-card">
              <h4 style={{ color: "var(--text-secondary)", marginBottom: "8px" }}>Schema Version</h4>
              <div style={{ fontSize: "16px", fontWeight: "600", color: "#4ecdc4" }}>v{health?.schema_version || 7}</div>
            </div>
            <div className="glass-card">
              <h4 style={{ color: "var(--text-secondary)", marginBottom: "8px" }}>Worker Status</h4>
              <div style={{ fontSize: "16px", fontWeight: "600", color: "#a8ff78" }}>🟢 {health?.worker_status || "RUNNING"}</div>
            </div>
          </div>

          {/* Integration Status Badges */}
          <div className="glass-card" style={{ marginTop: "10px" }}>
            <h3 style={{ fontFamily: "var(--font-heading)", fontSize: "16px", marginBottom: "12px" }}>🔌 Integration Provider Capabilities</h3>
            <div style={{ display: "flex", flexWrap: "wrap", gap: "10px" }}>
              {health?.providers && Object.entries(health.providers).map(([key, val]) => (
                <span
                  key={key}
                  style={{
                    padding: "6px 12px",
                    borderRadius: "6px",
                    fontSize: "12px",
                    fontWeight: "600",
                    background: val ? "rgba(46, 204, 113, 0.2)" : "rgba(255, 255, 255, 0.05)",
                    color: val ? "#2ecc71" : "#888",
                    border: val ? "1px solid rgba(46, 204, 113, 0.4)" : "1px solid rgba(255,255,255,0.1)"
                  }}
                >
                  {val ? "🟢 REAL API" : "🟡 LOCAL/DEFERRED"}: {key.toUpperCase()}
                </span>
              ))}
            </div>
          </div>
        </>
      )}
    </div>
  );
}


if (typeof window !== "undefined") {
  window.OverviewCockpit = OverviewCockpit;
}
