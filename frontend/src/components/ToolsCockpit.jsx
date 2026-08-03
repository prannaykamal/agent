import React, { useState, useEffect } from 'react';

export default function ToolsCockpit({ onRefresh }) {
  const [toolsData, setToolsData] = useState(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState(null);

  const fetchTools = async () => {
    setLoading(true);
    setError(null);
    try {
      const res = await fetch("/api/tools");
      if (!res.ok) throw new Error(`HTTP error ${res.status}`);
      const data = await res.json();
      setToolsData(data);
    } catch (e) {
      console.error(e);
      setError(e.message || "Failed to load tools catalog");
    } finally {
      setLoading(false);
    }
  };

  useEffect(() => {
    fetchTools();
  }, []);

  return (
    <div style={{ display: "flex", flexDirection: "column", gap: "20px" }}>
      <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center" }}>
        <h2 style={{ fontFamily: "var(--font-heading)", margin: 0 }}>🧰 Tools & MCP Gateway Catalog</h2>
        <button
          onClick={() => { fetchTools(); if (onRefresh) onRefresh(); }}
          style={{ padding: "8px 16px", background: "var(--primary-glow)", border: "none", borderRadius: "6px", color: "white", cursor: "pointer" }}
        >
          🔄 Refresh
        </button>
      </div>

      {error && (
        <div style={{ padding: "12px", background: "rgba(255, 50, 50, 0.15)", borderRadius: "8px", color: "#ff6b6b" }}>
          ⚠️ Error: {error}
        </div>
      )}

      {loading ? (
        <div style={{ padding: "32px", textAlign: "center", color: "var(--text-secondary)" }}>🌀 Loading tools catalog...</div>
      ) : (
        <div style={{ display: "grid", gridTemplateColumns: "1fr 1fr", gap: "24px" }}>
          <div className="glass-card">
            <h3>Personal OS Tools ({toolsData?.personal_os_tools?.length || 0})</h3>
            <div style={{ display: "flex", flexDirection: "column", gap: "8px", marginTop: "12px" }}>
              {toolsData?.personal_os_tools?.map((t, i) => (
                <div key={i} style={{ padding: "10px", background: "rgba(255,255,255,0.03)", borderRadius: "6px" }}>
                  <div style={{ display: "flex", justifyContent: "space-between" }}>
                    <strong>{t.name}</strong>
                    <span className="retrieval-badge" style={{ background: t.risk_level === 'High' ? 'rgba(255,50,50,0.2)' : 'rgba(50,255,100,0.15)' }}>{t.risk_level || 'Low'}</span>
                  </div>
                  <div style={{ fontSize: "12px", color: "var(--text-secondary)", marginTop: "4px" }}>{t.description}</div>
                </div>
              ))}
            </div>
          </div>

          <div className="glass-card">
            <h3>MCP Gateway Tools ({toolsData?.mcp_tools?.length || 0})</h3>
            <div style={{ display: "flex", flexDirection: "column", gap: "8px", marginTop: "12px" }}>
              {toolsData?.mcp_tools?.map((t, i) => (
                <div key={i} style={{ padding: "10px", background: "rgba(255,255,255,0.03)", borderRadius: "6px" }}>
                  <div style={{ display: "flex", justifyContent: "space-between" }}>
                    <strong>{t.name}</strong>
                    <span className="retrieval-badge" style={{ background: t.risk_level === 'High' ? 'rgba(255,50,50,0.2)' : 'rgba(78,205,196,0.15)' }}>{t.risk_level || 'Low'}</span>
                  </div>
                  <div style={{ fontSize: "12px", color: "var(--text-secondary)", marginTop: "4px" }}>{t.description}</div>
                </div>
              ))}
            </div>
          </div>
        </div>
      )}
    </div>
  );
}

if (typeof window !== "undefined") {
  window.ToolsCockpit = ToolsCockpit;
}
