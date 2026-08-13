import React, { useEffect, useRef, useState } from "react";
import { api } from "../api/client.js";
import PageHeader from "./ui/PageHeader.jsx";
import Notice from "./ui/Notice.jsx";
import Spinner from "./ui/Spinner.jsx";
import EmptyState from "./ui/EmptyState.jsx";
import DataTable from "./ui/DataTable.jsx";

export default function DataCockpit({ onRefresh }) {
  const [tables, setTables] = useState([]);
  const [selectedTable, setSelectedTable] = useState("");
  const [rowLimit, setRowLimit] = useState(50);
  const [tableResponse, setTableResponse] = useState(null);
  const [loadingTables, setLoadingTables] = useState(true);
  const [loadingRows, setLoadingRows] = useState(false);
  const [error, setError] = useState(null);
  const tableReq = useRef(0);

  const fetchTableContent = async (tblName, limit = rowLimit) => {
    if (!tblName) return;
    const req = ++tableReq.current;
    setLoadingRows(true);
    setError(null);
    try {
      const data = await api.get(`/api/data/table/${tblName}?limit=${limit}`);
      if (req !== tableReq.current) return;
      setTableResponse(data);
    } catch (e) {
      if (req !== tableReq.current) return;
      setError(e.message || `Failed to inspect table '${tblName}'`);
      setTableResponse(null);
    } finally {
      if (req === tableReq.current) setLoadingRows(false);
    }
  };

  const fetchTables = async () => {
    setLoadingTables(true);
    setError(null);
    try {
      const data = await api.get("/api/data/tables");
      const tableList = data.tables || [];
      setTables(tableList);
      if (tableList.length > 0) {
        const initialTbl = selectedTable && tableList.includes(selectedTable) ? selectedTable : tableList[0];
        setSelectedTable(initialTbl);
        fetchTableContent(initialTbl, rowLimit);
      } else {
        setSelectedTable("");
        setTableResponse(null);
      }
    } catch (e) {
      setError(e.message || "Failed to load database tables");
    } finally {
      setLoadingTables(false);
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
    if (selectedTable) fetchTableContent(selectedTable, l);
  };

  const columns = tableResponse?.columns || (tableResponse?.rows && tableResponse.rows.length > 0 ? Object.keys(tableResponse.rows[0]) : []);
  const rows = tableResponse?.rows || [];
  const totalRows = tableResponse?.total_rows ?? rows.length;

  return (
    <div className="page">
      <PageHeader
        title="Data"
        subtitle="Read-only tables from the local database."
        actions={<button className="btn btn-primary" onClick={() => { fetchTables(); if (selectedTable) fetchTableContent(selectedTable, rowLimit); if (onRefresh) onRefresh(); }}>Refresh</button>}
      />
      {error ? <Notice kind="error">{error}</Notice> : null}
      {loadingTables ? (
        <Spinner label="Loading database table registry..." />
      ) : tables.length === 0 ? (
        <EmptyState title="No tables" body="No data tables available in SQLite database." />
      ) : (
        <>
          <section className="glass-card">
            <div className="actions" style={{ justifyContent: "space-between" }}>
              <div className="table-pills">
                <span className="lede">Tables:</span>
                {tables.map((tbl) => (
                  <button key={tbl} className={`tab ${selectedTable === tbl ? "active" : ""}`} onClick={() => handleSelectTable(tbl)}>{tbl}</button>
                ))}
              </div>
              <label className="field" style={{ width: 140 }}>
                Limit Rows
                <select value={rowLimit} onChange={(e) => handleLimitChange(e.target.value)}>
                  <option value={25}>25 rows</option>
                  <option value={50}>50 rows</option>
                  <option value={100}>100 rows</option>
                  <option value={200}>200 rows</option>
                </select>
              </label>
            </div>
          </section>
          <section className="glass-card">
            <div className="card-head">
              <div>Inspect Table: <code><strong>{selectedTable}</strong></code></div>
              <div className="lede">Showing <strong>{rows.length}</strong> of <strong>{totalRows}</strong> total rows (Query Limit: {rowLimit})</div>
            </div>
            {loadingRows ? (
              <Spinner label="Loading table content..." />
            ) : rows.length === 0 ? (
              <div className="lede">Table '<code>{selectedTable}</code>' is currently empty.</div>
            ) : (
              <DataTable rows={rows} columns={columns} />
            )}
          </section>
        </>
      )}
    </div>
  );
}

if (typeof window !== "undefined") {
  window.DataCockpit = DataCockpit;
}
