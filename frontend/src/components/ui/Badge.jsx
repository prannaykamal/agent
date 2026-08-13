import React from "react";
import { statusTone } from "../../lib/format.js";

const LABELS = {
  available: "Available",
  mcp_available: "Available",
  unavailable: "Unavailable",
  mcp_unavailable: "Unavailable",
  not_configured: "Not configured",
  missing_config: "Not configured",
  configured: "Configured",
  api_configured: "Configured",
  api_missing: "Missing API",
  online: "Online",
  offline: "Offline",
  healthy: "Healthy",
  pending: "Pending",
  running: "Running",
  succeeded: "Succeeded",
  failed: "Failed",
  blocked: "Blocked",
  active: "Active",
  paused: "Paused",
  stale: "Stale",
};

function prettyLabel(value) {
  const raw = String(value).trim();
  const key = raw.toLowerCase().replace(/[\s-]+/g, "_");
  if (LABELS[key]) return LABELS[key];
  const spaced = raw.replace(/_/g, " ");
  if (spaced && spaced === spaced.toUpperCase()) {
    return spaced.charAt(0) + spaced.slice(1).toLowerCase();
  }
  return spaced;
}

export default function Badge({ value, tone }) {
  if (value == null || value === "") return null;
  const resolved = tone || statusTone(value);
  const cls = resolved === "ok" ? "badge-ok" : resolved === "warn" ? "badge-warn" : resolved === "danger" ? "badge-danger" : "";
  return (
    <span className={`badge retrieval-badge ${cls}`} title={String(value)}>
      {prettyLabel(value)}
    </span>
  );
}
