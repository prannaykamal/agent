import React from "react";

export default function DataTable({ rows, emptyText, columns }) {
  if (!rows || rows.length === 0) {
    return <div className="empty" style={{ padding: "18px 0" }}>{emptyText || "No rows."}</div>;
  }
  const cols = columns || Object.keys(rows[0] || {}).slice(0, 8);
  return (
    <div className="table-wrap">
      <table className="data data-table">
        <thead>
          <tr>
            {cols.map((col) => <th key={col}>{col}</th>)}
          </tr>
        </thead>
        <tbody>
          {rows.map((row, idx) => (
            <tr key={row.id || idx}>
              {cols.map((col) => {
                const val = row[col];
                return (
                  <td key={col} title={typeof val === "object" ? JSON.stringify(val) : String(val ?? "")}>
                    {typeof val === "object" && val !== null ? JSON.stringify(val) : String(val ?? "")}
                  </td>
                );
              })}
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}
