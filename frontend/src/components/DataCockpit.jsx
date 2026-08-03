import React, { useState, useEffect } from 'react';

export default function DataCockpit({ onRefresh }) {
  const [tables, setTables] = useState([]);
  const [selectedTable, setSelectedTable] = useState("");
  const [tableData, setTableData] = useState([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState(null);

  const fetchTables = async () => {
    setLoading(true);
    setError(null);
    try {
      const res = await fetch("/api/data/tables");
      if (!res.ok) throw new Error(`HTTP error ${res.status}`);
      const data = await res.json();
      setTables(data.tables || []);
      if (data.tables && data.tables.length > 0 && !selectedTable) {
        setSelectedTable(data.tables[0]);
        fetchTableContent(data.tables[0]);
      }
    } catch (e) {
      console.error(e);
      setError(e.message || "Failed to load database tables");
    } finally {
      setLoading(false);
    }
  };

  const fetchTableContent = async (tblName) => {
    try {
      const res = await fetch(`/api/data/table/${tblName}`);
      if (res.ok) {
        const data = await res.json();
        setTableData(data.rows || []);
      }
    } catch (e) {
      console.error(e);
    }
  };

  useEffect(() => {
    fetchTables();
  }, []);

  return (
    <div style={{ display: "flex", flexDirection: "column", gap: "20px" }}>
      <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center" }}>
        <h2 style={{ fontFamily: "var(--font-heading)", margin: 0 }}>🗄️ SQLite Database Inspector</h2>
        <button
          onClick={() => { fetchTables(); if (selectedTable) fetchTableContent(selectedTable); if (onRefresh) onRefresh(); }}
          style={{ padding: "8px 16px", background: "var(--primary-glow)", border: "none", borderRadius: "6px", color: "white", cursor: "pointer" }}
        >
          🔄 Refresh
        </button>
      </div>

      <div style={{ display: "flex", gap: "10px", flexWrap: "wrap" }}>
        {tables.map(tbl => (
          <button
            key={tbl}
            onClick={() => { setSelectedTable(tbl); fetchTableContent(tbl); }}
            style={{
              padding: "8px 14px",
              background: selectedTable === tbl ? "var(--primary-glow)" : "rgba(255,255,255,0.05)",
              border: "1px solid var(--border-glass)",
              borderRadius: "6px",
              color: "white",
              cursor: "pointer"
            }}
          >
            {tbl}
          </button>
        ))}
      </div>

      {error && (
        <div style={{ padding: "12px", background: "rgba(255, 50, 50, 0.15)", borderRadius: "8px", color: "#ff6b6b" }}>
          ⚠️ Error: {error}
        </div>
      )}

      {loading ? (
        <div style={{ padding: "32px", textAlign: "center", color: "var(--text-secondary)" }}>🌀 Loading table browser...</div>
      ) : tableData.length === 0 ? (
        <div className="glass-card" style={{ textAlign: "center", padding: "48px", color: "var(--text-secondary)", fontStyle: "italic" }}>
          📭 Table '{selectedTable}' is currently empty.
        </div>
      ) : (
        <div className="glass-card" style={{ overflowX: "auto" }}>
          <table style={{ width: "100%", borderCollapse: "collapse", fontSize: "13px" }}>
            <thead>
              <tr style={{ borderBottom: "1px solid var(--border-glass)", textAlign: "left" }}>
                {Object.keys(tableData[0] || {}).map(col => (
                  <th key={col} style={{ padding: "10px", color: "#4ecdc4" }}>{col}</th>
                ))}
              </tr>
            </thead>
            <tbody>
              {tableData.map((row, idx) => (
                <tr key={idx} style={{ borderBottom: "1px solid rgba(255,255,255,0.03)" }}>
                  {Object.values(row).map((val, cidx) => (
                    <td key={cidx} style={{ padding: "10px", maxWidth: "250px", overflow: "hidden", textOverflow: "ellipsis", whiteSpace: "nowrap" }}>
                      {typeof val === 'object' ? JSON.stringify(val) : String(val)}
                    </td>
                  ))}
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
    </div>
  );
}

if (typeof window !== "undefined") {
  window.DataCockpit = DataCockpit;
}
