import React, { useState, useEffect } from 'react';
import { api } from '../api/client.js';

export default function DataCockpit({ onRefresh }) {
  const [tables, setTables] = useState([]);
  const [selectedTable, setSelectedTable] = useState('');
  const [rowLimit, setRowLimit] = useState(50);
  const [tableResponse, setTableResponse] = useState(null);
  const [loadingTables, setLoadingTables] = useState(true);
  const [loadingRows, setLoadingRows] = useState(false);
  const [error, setError] = useState(null);

  const fetchTables = async () => {
    setLoadingTables(true);
    setError(null);
    try {
      const data = await api.get('/api/data/tables');
      const tableList = data.tables || [];
      setTables(tableList);
      
      if (tableList.length > 0) {
        const initialTbl = selectedTable && tableList.includes(selectedTable) ? selectedTable : tableList[0];
        setSelectedTable(initialTbl);
        fetchTableContent(initialTbl, rowLimit);
      } else {
        setSelectedTable('');
        setTableResponse(null);
      }
    } catch (e) {
      console.error(e);
      setError(e.message || 'Failed to load database tables');
    } finally {
      setLoadingTables(false);
    }
  };

  const fetchTableContent = async (tblName, limit = rowLimit) => {
    if (!tblName) return;
    setLoadingRows(true);
    setError(null);
    try {
      const data = await api.get(`/api/data/table/${tblName}?limit=${limit}`);
      setTableResponse(data);
    } catch (e) {
      console.error(e);
      setError(e.message || `Failed to inspect table '${tblName}'`);
      setTableResponse(null);
    } finally {
      setLoadingRows(false);
    }
  };

  useEffect(() => {
    fetchTables();
  }, []);

  const handleSelectTable = (tbl) => {
    setSelectedTable(tbl);
    fetchTableContent(tbl, rowLimit);
  };

  const handleLimitChange = (newLimit) => {
    const l = Number(newLimit);
    setRowLimit(l);
    if (selectedTable) {
      fetchTableContent(selectedTable, l);
    }
  };

  const columns = tableResponse?.columns || (tableResponse?.rows && tableResponse.rows.length > 0 ? Object.keys(tableResponse.rows[0]) : []);
  const rows = tableResponse?.rows || [];
  const totalRows = tableResponse?.total_rows ?? rows.length;

  return (
    <div style={{ display: 'flex', flexDirection: 'column', gap: '20px' }}>
      {/* Top Header */}
      <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', flexWrap: 'wrap', gap: '10px' }}>
        <div>
          <h2 style={{ fontFamily: 'var(--font-heading)', margin: 0 }}>🗄️ SQLite Database Inspector</h2>
          <span style={{ fontSize: '12px', color: 'var(--text-secondary)' }}>
            Read-only schema inspection for allowed database tables.
          </span>
        </div>
        <button
          onClick={() => { fetchTables(); if (selectedTable) fetchTableContent(selectedTable, rowLimit); if (onRefresh) onRefresh(); }}
          style={{ padding: '8px 16px', background: 'var(--primary-glow)', border: 'none', borderRadius: '6px', color: 'white', cursor: 'pointer' }}
        >
          🔄 Refresh
        </button>
      </div>

      {error && (
        <div style={{ padding: '12px', background: 'rgba(255, 50, 50, 0.15)', borderRadius: '8px', color: '#ff6b6b', fontSize: '13px' }}>
          ⚠️ {error}
        </div>
      )}

      {loadingTables ? (
        <div style={{ padding: '32px', textAlign: 'center', color: 'var(--text-secondary)' }}>🌀 Loading database table registry...</div>
      ) : tables.length === 0 ? (
        <div className="glass-card" style={{ textAlign: 'center', padding: '48px', color: 'var(--text-secondary)', fontStyle: 'italic' }}>
          📭 No data tables available in SQLite database.
        </div>
      ) : (
        <>
          {/* Table Selector Strip & Limit Control */}
          <div className="glass-card" style={{ padding: '14px', display: 'flex', justifyContent: 'space-between', alignItems: 'center', flexWrap: 'wrap', gap: '12px' }}>
            <div style={{ display: 'flex', gap: '8px', flexWrap: 'wrap', alignItems: 'center' }}>
              <span style={{ fontSize: '13px', fontWeight: '600', color: 'var(--text-secondary)' }}>Tables:</span>
              {tables.map(tbl => (
                <button
                  key={tbl}
                  onClick={() => handleSelectTable(tbl)}
                  style={{
                    padding: '6px 14px',
                    background: selectedTable === tbl ? 'var(--primary-glow)' : 'rgba(255,255,255,0.05)',
                    border: selectedTable === tbl ? '1px solid var(--primary-glow)' : '1px solid var(--border-glass)',
                    borderRadius: '6px',
                    color: 'white',
                    cursor: 'pointer',
                    fontSize: '12px',
                    fontWeight: selectedTable === tbl ? '600' : 'normal'
                  }}
                >
                  {tbl}
                </button>
              ))}
            </div>

            {/* Preset Row Limit Control */}
            <div style={{ display: 'flex', gap: '8px', alignItems: 'center' }}>
              <span style={{ fontSize: '12px', color: 'var(--text-secondary)' }}>Limit Rows:</span>
              <select
                value={rowLimit}
                onChange={e => handleLimitChange(e.target.value)}
                style={{
                  padding: '6px 10px',
                  background: 'rgba(0,0,0,0.4)',
                  border: '1px solid var(--border-glass)',
                  borderRadius: '6px',
                  color: 'white',
                  fontSize: '12px',
                  cursor: 'pointer'
                }}
              >
                <option value={25}>25 rows</option>
                <option value={50}>50 rows</option>
                <option value={100}>100 rows</option>
                <option value={200}>200 rows</option>
              </select>
            </div>
          </div>

          {/* Table Data Metadata & Grid */}
          <div className="glass-card" style={{ display: 'flex', flexDirection: 'column', gap: '12px' }}>
            <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', fontSize: '13px' }}>
              <div>
                Inspect Table: <code><strong>{selectedTable}</strong></code>
              </div>
              <div style={{ color: 'var(--text-secondary)', fontSize: '12px' }}>
                Showing <strong>{rows.length}</strong> of <strong>{totalRows}</strong> total rows (Query Limit: {rowLimit})
              </div>
            </div>

            {loadingRows ? (
              <div style={{ padding: '32px', textAlign: 'center', color: 'var(--text-secondary)' }}>🌀 Loading table content...</div>
            ) : rows.length === 0 ? (
              <div style={{ textAlign: 'center', padding: '36px 0', color: 'var(--text-secondary)', fontStyle: 'italic' }}>
                📭 Table '<code>{selectedTable}</code>' is currently empty.
              </div>
            ) : (
              <div style={{ overflowX: 'auto' }}>
                <table style={{ width: '100%', borderCollapse: 'collapse', fontSize: '12px' }}>
                  <thead>
                    <tr style={{ borderBottom: '1px solid var(--border-glass)', textAlign: 'left', background: 'rgba(255,255,255,0.03)' }}>
                      {columns.map(col => (
                        <th key={col} style={{ padding: '10px', color: '#4ecdc4', fontFamily: 'monospace', fontWeight: '600' }}>
                          {col}
                        </th>
                      ))}
                    </tr>
                  </thead>
                  <tbody>
                    {rows.map((row, idx) => (
                      <tr key={idx} style={{ borderBottom: '1px solid rgba(255,255,255,0.03)' }}>
                        {columns.map(col => {
                          const val = row[col];
                          return (
                            <td key={col} style={{ padding: '8px 10px', maxWidth: '260px', overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap' }}>
                              {typeof val === 'object' && val !== null ? JSON.stringify(val) : String(val ?? '')}
                            </td>
                          );
                        })}
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
            )}
          </div>
        </>
      )}
    </div>
  );
}

if (typeof window !== 'undefined') {
  window.DataCockpit = DataCockpit;
}

