import React, { useEffect, useState } from "react";
import { api } from "../api/client.js";
import PageHeader from "./ui/PageHeader.jsx";
import Notice from "./ui/Notice.jsx";
import Spinner from "./ui/Spinner.jsx";
import EmptyState from "./ui/EmptyState.jsx";
import Badge from "./ui/Badge.jsx";

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
      if (data.message) resultMsg = data.message;
      else if (data.response) resultMsg = typeof data.response === "string" ? data.response : JSON.stringify(data.response);
      else if (data.tool_result) resultMsg = typeof data.tool_result === "string" ? data.tool_result : JSON.stringify(data.tool_result);
      setActionStatus(resultMsg);
      setLastDecisionResult(data);
      loadApprovals();
      if (onRefresh) onRefresh();
    } catch (e) {
      setActionStatus(`Error processing decision: ${e.message}`);
      setLastDecisionResult({ error: e.message, status: "ERROR" });
    }
  };

  const getRequestBadge = (req) => {
    const name = (req.tool_name || "").toLowerCase();
    const reason = (req.reason || "").toLowerCase();
    if (name.includes("procedural") || name.includes("skill") || reason.includes("procedural") || reason.includes("skill")) {
      return "Skill Promotion";
    }
    if (name.includes("calendar") || name.includes("email") || name.includes("whatsapp") || name.includes("telegram")) {
      return "External Integration";
    }
    if (name.includes("cron") || name.includes("schedule")) {
      return "Scheduled Action";
    }
    return "High Risk Tool";
  };

  return (
    <div className="page">
      <PageHeader
        title="Approvals"
        subtitle="High-risk writes wait here until you approve or reject them."
        actions={<button className="btn btn-primary" onClick={() => { loadApprovals(); if (onRefresh) onRefresh(); }}>Refresh</button>}
      />

      {actionStatus ? (
        <Notice kind={lastDecisionResult?.error ? "error" : "ok"}>
          <strong>{lastDecisionResult?.error ? "Decision Error" : "Decision Outcome"}:</strong> {actionStatus}
        </Notice>
      ) : null}

      {lastDecisionResult?.procedural_skill_approval ? (
        <Notice>
          <strong>Procedural Skill Decision Details</strong>
          <div>
            Skill: <strong>{lastDecisionResult.procedural_skill_approval.name || "N/A"}</strong>
            {" · "}Status: <strong>{lastDecisionResult.procedural_skill_approval.status || lastDecisionResult.status}</strong>
          </div>
          {lastDecisionResult.procedural_skill_approval.description ? (
            <div className="lede">{lastDecisionResult.procedural_skill_approval.description}</div>
          ) : null}
        </Notice>
      ) : null}

      {error ? <Notice kind="error">Error: {error}</Notice> : null}

      {loading ? (
        <Spinner label="Loading pending approvals..." />
      ) : approvals.length === 0 ? (
        <EmptyState title="Nothing waiting" body="No pending approval requests." />
      ) : (
        approvals.map((req) => {
          const badge = getRequestBadge(req);
          const isUnavailable = (req.reason || "").toLowerCase().includes("unavailable") || (req.tool_name || "").toLowerCase().includes("unavailable");
          const isBlocked = (req.reason || "").toLowerCase().includes("blocked") || (req.reason || "").toLowerCase().includes("policy");
          return (
            <article key={req.id} className="glass-card">
              <div className="row-card" style={{ border: 0, padding: 0 }}>
                <div>
                  <div className="chip-row" style={{ marginBottom: 8 }}>
                    <strong>Tool: {req.tool_name}</strong>
                    <Badge value={badge} />
                    {isUnavailable ? <Badge value="Provider Unavailable" tone="warn" /> : null}
                    {isBlocked ? <Badge value="Policy Blocked" tone="danger" /> : null}
                  </div>
                  <div className="lede">Session: <code>{req.session_id || "global"}</code> · Request ID: <code>{req.id}</code></div>
                  <div style={{ marginTop: 8 }}><strong>Reason:</strong> {req.reason}</div>
                  {req.created_at ? <div className="lede">Requested at: {req.created_at}</div> : null}
                  {req.tool_args ? <pre className="json-block">{JSON.stringify(req.tool_args, null, 2)}</pre> : null}
                </div>
                <div className="actions">
                  <button className="btn btn-ok" onClick={() => handleDecision(req.id, "APPROVED")}>Approve</button>
                  <button className="btn btn-danger" onClick={() => handleDecision(req.id, "REJECTED")}>Reject</button>
                </div>
              </div>
            </article>
          );
        })
      )}
    </div>
  );
}

if (typeof window !== "undefined") {
  window.ApprovalInbox = ApprovalInbox;
}
