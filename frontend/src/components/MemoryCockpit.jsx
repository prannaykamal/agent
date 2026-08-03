import React, { useState, useEffect } from 'react';

export default function MemoryCockpit({ onRefresh }) {
  const [activeSubTab, setActiveSubTab] = useState("semantic");
  const [memoryData, setMemoryData] = useState(null);
  const [searchQuery, setSearchQuery] = useState("");
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState(null);

  const fetchMemory = async (q = "") => {
    setLoading(true);
    setError(null);
    try {
      const url = q ? `/api/memory/full?query=${encodeURIComponent(q)}` : "/api/memory/full";
      const res = await fetch(url);
      if (!res.ok) throw new Error(`HTTP error ${res.status}`);
      const data = await res.json();
      setMemoryData(data);
    } catch (e) {
      console.error(e);
      setError(e.message || "Failed to load memory");
    } finally {
      setLoading(false);
    }
  };

  useEffect(() => {
    fetchMemory();
  }, []);

  return (
    <div style={{ display: "flex", flexDirection: "column", gap: "20px" }}>
      <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center" }}>
        <h2 style={{ fontFamily: "var(--font-heading)", margin: 0 }}>🧠 Long-Term Memory & Identity Subsystems</h2>
        <button
          onClick={() => { fetchMemory(searchQuery); if (onRefresh) onRefresh(); }}
          style={{ padding: "8px 16px", background: "var(--primary-glow)", border: "none", borderRadius: "6px", color: "white", cursor: "pointer" }}
        >
          🔄 Refresh
        </button>
      </div>

      <div style={{ display: "flex", gap: "12px" }}>
        <input
          type="text"
          value={searchQuery}
          onChange={e => setSearchQuery(e.target.value)}
          onKeyDown={e => e.key === "Enter" && fetchMemory(searchQuery)}
          placeholder="Search semantic facts or past episodes..."
          style={{ flex: 1, padding: "10px 16px", background: "rgba(0,0,0,0.3)", border: "1px solid var(--border-glass)", borderRadius: "8px", color: "white" }}
        />
        <button onClick={() => fetchMemory(searchQuery)} style={{ padding: "10px 20px", background: "var(--primary-glow)", border: "none", borderRadius: "8px", color: "white", cursor: "pointer" }}>Search</button>
      </div>

      {/* Sub tabs */}
      <div style={{ display: "flex", gap: "10px", borderBottom: "1px solid var(--border-glass)", paddingBottom: "8px" }}>
        {["semantic", "episodic", "soul", "skill", "memory_md"].map(tab => (
          <button
            key={tab}
            onClick={() => setActiveSubTab(tab)}
            style={{
              padding: "8px 16px",
              background: activeSubTab === tab ? "rgba(255,255,255,0.1)" : "transparent",
              border: activeSubTab === tab ? "1px solid var(--border-glass)" : "none",
              borderRadius: "6px",
              color: activeSubTab === tab ? "white" : "var(--text-secondary)",
              cursor: "pointer",
              textTransform: "capitalize"
            }}
          >
            {tab.replace("_", ".")}
          </button>
        ))}
      </div>

      {error && (
        <div style={{ padding: "12px", background: "rgba(255, 50, 50, 0.15)", borderRadius: "8px", color: "#ff6b6b" }}>
          ⚠️ Error: {error}
        </div>
      )}

      {loading ? (
        <div style={{ padding: "32px", textAlign: "center", color: "var(--text-secondary)" }}>🌀 Loading memory data...</div>
      ) : (
        <div className="glass-card">
          {activeSubTab === "semantic" && (
            <div>
              <h3>Semantic Facts ({memoryData?.facts?.length || 0})</h3>
              {(!memoryData?.facts || memoryData.facts.length === 0) ? (
                <div style={{ color: "var(--text-secondary)", fontStyle: "italic", padding: "16px 0" }}>📭 No semantic facts registered yet.</div>
              ) : (
                memoryData.facts.map((f, i) => (
                  <div key={i} style={{ padding: "10px", borderBottom: "1px solid var(--border-glass)" }}>
                    <strong>[{f.category}]</strong> {f.fact_text}
                  </div>
                ))
              )}
            </div>
          )}

          {activeSubTab === "episodic" && (
            <div>
              <h3>Past Episodes ({memoryData?.episodes?.length || 0})</h3>
              {(!memoryData?.episodes || memoryData.episodes.length === 0) ? (
                <div style={{ color: "var(--text-secondary)", fontStyle: "italic", padding: "16px 0" }}>📭 No past episodes recorded.</div>
              ) : (
                memoryData.episodes.map((ep, i) => (
                  <div key={i} style={{ padding: "10px", borderBottom: "1px solid var(--border-glass)" }}>
                    <div><strong>{ep.timestamp}</strong> - {ep.session_id}</div>
                    <div style={{ color: "var(--text-secondary)", fontSize: "13px" }}>{ep.content}</div>
                  </div>
                ))
              )}
            </div>
          )}

          {activeSubTab === "soul" && (
            <div>
              <h3>SOUL.md Identity Master Prompt</h3>
              <pre style={{ whiteSpace: "pre-wrap", fontFamily: "monospace", fontSize: "13px" }}>{memoryData?.soul_md || "(Empty SOUL.md)"}</pre>
            </div>
          )}

          {activeSubTab === "skill" && (
            <div>
              <h3>SKILL.md Procedural Knowledge Catalog</h3>
              <pre style={{ whiteSpace: "pre-wrap", fontFamily: "monospace", fontSize: "13px" }}>{memoryData?.skill_md || "(Empty SKILL.md)"}</pre>
            </div>
          )}

          {activeSubTab === "memory_md" && (
            <div>
              <h3>MEMORY.md Auto-Synced Fact Mirror</h3>
              <pre style={{ whiteSpace: "pre-wrap", fontFamily: "monospace", fontSize: "13px" }}>{memoryData?.memory_md || "(Empty MEMORY.md)"}</pre>
            </div>
          )}
        </div>
      )}
    </div>
  );
}

if (typeof window !== "undefined") {
  window.MemoryCockpit = MemoryCockpit;
}
