import React, { useState, useEffect } from 'react';
import { api } from '../api/client.js';

export default function ApprovalInbox({ onRefresh }) {
  const [approvals, setApprovals] = useState([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState(null);
  const [actionStatus, setActionStatus] = useState(null);
  const [lastDecisionResult, setLastDecisionResult] = useState(null);

  const loadApprovals = async () => {
    setLoading(true);
    setError(null);
    try {
      const data = await api.get("/api/approvals");
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
      setActionStatus(`Processing ${decision} decision for request '${reqId}'...`);
      setLastDecisionResult(null);
      const data = await api.post(`/api/approvals/${reqId}/decision`, { decision });

      let resultMsg = `Decision ${data.status || decision} recorded for tool '${data.tool_name || "action"}'.`;
      if (data.message) {
        resultMsg = data.message;
      } else if (data.response) {
        resultMsg = typeof data.response === "string" ? data.response : JSON.stringify(data.response);
      } else if (data.tool_result) {
        resultMsg = typeof data.tool_result === "string" ? data.tool_result : JSON.stringify(data.tool_result);
      }

      setActionStatus(resultMsg);
      setLastDecisionResult(data);
      loadApprovals();
      if (onRefresh) onRefresh();
    } catch (e) {
      console.error(e);
      setActionStatus(`Error processing decision: ${e.message}`);
      setLastDecisionResult({ error: e.message, status: "ERROR" });
    }
  };

  const getRequestBadge = (req) => {
    const name = (req.tool_name || "").toLowerCase();
    const reason = (req.reason || "").toLowerCase();

    if (name.includes("procedural") || name.includes("skill") || reason.includes("procedural") || reason.includes("skill")) {
      return { label: "🎓 Skill Promotion", bg: "rgba(155, 89, 182, 0.2)", color: "#9b59b6" };
    }
    if (name.includes("calendar") || name.includes("email") || name.includes("whatsapp") || name.includes("telegram")) {
      return { label: "🌐 External Integration", bg: "rgba(52, 152, 219, 0.2)", color: "#3498db" };
    }
    if (name.includes("cron") || name.includes("schedule")) {
      return { label: "⏱️ Scheduled Action", bg: "rgba(230, 126, 34, 0.2)", color: "#e67e22" };
    }
    return { label: "🛡️ High Risk Tool", bg: "rgba(255, 50, 50, 0.2)", color: "#ff6b6b" };
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
        <div
          style={{
            padding: "12px 16px",
            background: lastDecisionResult?.error
              ? "rgba(255,50,50,0.15)"
              : "rgba(78, 205, 196, 0.15)",
            border: lastDecisionResult?.error
              ? "1px solid rgba(255,50,50,0.4)"
              : "1px solid rgba(78, 205, 196, 0.4)",
            borderRadius: "8px",
            color: lastDecisionResult?.error ? "#ff6b6b" : "#4ecdc4",
            fontSize: "14px"
          }}
        >
          <strong>{lastDecisionResult?.error ? "⚠️ Decision Error" : "ℹ️ Decision Outcome"}:</strong> {actionStatus}
        </div>
      )}

      {lastDecisionResult && lastDecisionResult.procedural_skill_approval && (
        <div
          style={{
            padding: "14px 18px",
            background: "rgba(155, 89, 182, 0.15)",
            border: "1px solid rgba(155, 89, 182, 0.4)",
            borderRadius: "8px",
            color: "#e0b0ff"
          }}
        >
          <strong style={{ display: "block", fontSize: "15px", marginBottom: "6px" }}>
            🎓 Procedural Skill Decision Details
          </strong>
          <div style={{ fontSize: "13px" }}>
            <span>Skill: <strong>{lastDecisionResult.procedural_skill_approval.name || "N/A"}</strong></span> |{" "}
            <span>Status: <strong>{lastDecisionResult.procedural_skill_approval.status || lastDecisionResult.status}</strong></span>
          </div>
          {lastDecisionResult.procedural_skill_approval.description && (
            <div style={{ fontSize: "12px", marginTop: "4px", opacity: 0.9 }}>
              Description: {lastDecisionResult.procedural_skill_approval.description}
            </div>
          )}
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
          {approvals.map(req => {
            const badge = getRequestBadge(req);
            const isUnavailable = (req.reason || "").toLowerCase().includes("unavailable") || (req.tool_name || "").toLowerCase().includes("unavailable");
            const isBlocked = (req.reason || "").toLowerCase().includes("blocked") || (req.reason || "").toLowerCase().includes("policy");

            return (
              <div
                key={req.id}
                className="glass-card"
                style={{
                  display: "flex",
                  justify: "space-between",
                  alignItems: "center",
                  borderLeft: `4px solid ${isUnavailable ? "#f39c12" : isBlocked ? "#ff4757" : badge.color}`,
                  flexWrap: "wrap",
                  gap: "16px"
                }}
              >
                <div style={{ flex: 1, minWidth: "280px" }}>
                  <div style={{ display: "flex", gap: "10px", alignItems: "center", marginBottom: "6px", flexWrap: "wrap" }}>
                    <strong style={{ fontSize: "16px" }}>⚙️ Tool: {req.tool_name}</strong>
                    <span className="retrieval-badge" style={{ background: badge.bg, color: badge.color }}>
                      {badge.label}
                    </span>
                    {isUnavailable && (
                      <span className="retrieval-badge" style={{ background: "rgba(243, 156, 18, 0.2)", color: "#f39c12" }}>
                        ⚠️ Provider Unavailable
                      </span>
                    )}
                    {isBlocked && (
                      <span className="retrieval-badge" style={{ background: "rgba(255, 71, 87, 0.2)", color: "#ff4757" }}>
                        ⛔ Policy Blocked
                      </span>
                    )}
                  </div>
                  <div style={{ fontSize: "13px", color: "var(--text-secondary)" }}>
                    Session: <code>{req.session_id || "global"}</code> | Request ID: <code>{req.id}</code>
                  </div>
                  <div style={{ fontSize: "14px", marginTop: "8px" }}>
                    <strong>Reason:</strong> {req.reason}
                  </div>
                  {req.created_at && (
                    <div style={{ fontSize: "11px", color: "var(--text-secondary)", marginTop: "4px" }}>
                      Requested at: {req.created_at}
                    </div>
                  )}
                </div>

                <div style={{ display: "flex", gap: "12px" }}>
                  <button
                    onClick={() => handleDecision(req.id, "APPROVED")}
                    style={{ padding: "10px 20px", background: "#2ed573", border: "none", borderRadius: "6px", color: "white", fontWeight: "600", cursor: "pointer" }}
                  >
                    ✓ Approve
                  </button>
                  <button
                    onClick={() => handleDecision(req.id, "REJECTED")}
                    style={{ padding: "10px 20px", background: "#ff4757", border: "none", borderRadius: "6px", color: "white", fontWeight: "600", cursor: "pointer" }}
                  >
                    ✕ Reject
                  </button>
                </div>
              </div>
            );
          })}
        </div>
      )}
    </div>
  );
}

if (typeof window !== "undefined") {
  window.ApprovalInbox = ApprovalInbox;
}

