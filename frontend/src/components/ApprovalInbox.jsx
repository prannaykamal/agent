import React, { useState, useEffect } from 'react';

export default function ApprovalInbox({ onRefresh }) {
  const [approvals, setApprovals] = useState([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState(null);
  const [actionStatus, setActionStatus] = useState(null);

  const loadApprovals = async () => {
    setLoading(true);
    setError(null);
    try {
      const res = await fetch("/api/approvals");
      if (!res.ok) throw new Error(`HTTP error ${res.status}`);
      const data = await res.json();
      setApprovals(data.approval_requests || []);
    } catch (e) {
      console.error(e);
      setError(e.message || "Failed to load approval requests");
    } finally {
      setLoading(false);
    }
  };

  useEffect(() => {
    loadApprovals();
  }, []);

  const handleDecision = async (reqId, decision) => {
    try {
      setActionStatus(`Processing decision for ${reqId}...`);
      const res = await fetch(`/api/approvals/${reqId}/decision`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ decision })
      });
      if (!res.ok) throw new Error(`HTTP error ${res.status}`);
      const data = await res.json();
      setActionStatus(`Decision processed: ${data.status} for tool '${data.tool_name}'`);
      loadApprovals();
      if (onRefresh) onRefresh();
    } catch (e) {
      console.error(e);
      setActionStatus(`Error processing decision: ${e.message}`);
    }
  };

  return (
    <div style={{ display: "flex", flexDirection: "column", gap: "20px" }}>
      <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center" }}>
        <h2 style={{ fontFamily: "var(--font-heading)", margin: 0 }}>🛡️ Human-In-The-Loop Approval Inbox</h2>
        <button
          onClick={() => { loadApprovals(); if (onRefresh) onRefresh(); }}
          style={{ padding: "8px 16px", background: "var(--primary-glow)", border: "none", borderRadius: "6px", color: "white", cursor: "pointer" }}
        >
          🔄 Refresh
        </button>
      </div>

      {actionStatus && (
        <div style={{ padding: "10px 16px", background: "rgba(78, 205, 196, 0.15)", border: "1px solid rgba(78, 205, 196, 0.3)", borderRadius: "8px", color: "#4ecdc4", fontSize: "14px" }}>
          ℹ️ {actionStatus}
        </div>
      )}

      {error && (
        <div style={{ padding: "12px", background: "rgba(255,50,50,0.15)", borderRadius: "8px", color: "#ff6b6b" }}>
          ⚠️ Error: {error}
        </div>
      )}

      {loading ? (
        <div style={{ padding: "32px", textAlign: "center", color: "var(--text-secondary)" }}>🌀 Loading pending approvals...</div>
      ) : approvals.length === 0 ? (
        <div className="glass-card" style={{ textAlign: "center", padding: "48px", color: "var(--text-secondary)", fontStyle: "italic" }}>
          ✅ No pending high-risk approval requests requiring human decision.
        </div>
      ) : (
        <div style={{ display: "flex", flexDirection: "column", gap: "16px" }}>
          {approvals.map(req => (
            <div key={req.id} className="glass-card" style={{ display: "flex", justifyContent: "space-between", alignItems: "center", borderLeft: "4px solid #ff6b6b" }}>
              <div>
                <div style={{ display: "flex", gap: "10px", alignItems: "center", marginBottom: "6px" }}>
                  <strong style={{ fontSize: "16px" }}>⚙️ Tool: {req.tool_name}</strong>
                  <span className="retrieval-badge" style={{ background: "rgba(255, 50, 50, 0.2)", color: "#ff6b6b" }}>High Risk</span>
                </div>
                <div style={{ fontSize: "13px", color: "var(--text-secondary)" }}>Session: {req.session_id} | Request ID: {req.id}</div>
                <div style={{ fontSize: "14px", marginTop: "8px" }}>Reason: {req.reason}</div>
              </div>

              <div style={{ display: "flex", gap: "12px" }}>
                <button
                  onClick={() => handleDecision(req.id, "APPROVED")}
                  style={{ padding: "10px 20px", background: "#2ed573", border: "none", borderRadius: "6px", color: "white", fontWeight: "600", cursor: "pointer" }}
                >
                  Approve
                </button>
                <button
                  onClick={() => handleDecision(req.id, "REJECTED")}
                  style={{ padding: "10px 20px", background: "#ff4757", border: "none", borderRadius: "6px", color: "white", fontWeight: "600", cursor: "pointer" }}
                >
                  Reject
                </button>
              </div>
            </div>
          ))}
        </div>
      )}
    </div>
  );
}

if (typeof window !== "undefined") {
  window.ApprovalInbox = ApprovalInbox;
}
