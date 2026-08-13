import React, { useEffect, useState } from "react";
import { api } from "../api/client.js";
import PageHeader from "./ui/PageHeader.jsx";
import Notice from "./ui/Notice.jsx";
import Spinner from "./ui/Spinner.jsx";
import Badge from "./ui/Badge.jsx";
import { statusTone } from "../lib/format.js";

function ToolRow({ tool }) {
  return (
    <div className={`provider-card is-${statusTone(tool.availability_status || "available")}`}>
      <div className="actions" style={{ justifyContent: "space-between" }}>
        <strong>{tool.legacy_name || tool.name}</strong>
        <div className="chip-row">
          <Badge value={tool.availability_status || "available"} />
          <Badge value={tool.risk_class || tool.risk_level || "Low"} />
        </div>
      </div>
      <div className="lede">
        Provider: {tool.provider || "legacy"} | Type: {tool.implementation_type || "active"} | Policy: {tool.approval_policy || "no_approval_needed"} | Capability: {tool.read_write_capability || "unknown"}
      </div>
      {tool.description ? <div className="lede">{tool.description}</div> : null}
    </div>
  );
}

function Group({ title, tools, empty }) {
  return (
    <div className="glass-card">
      <h3>{title} ({tools?.length || 0})</h3>
      {!tools || tools.length === 0 ? (
        <div className="lede">{empty || "No entries."}</div>
      ) : (
        <div style={{ display: "flex", flexDirection: "column", gap: 8, marginTop: 12 }}>
          {tools.map((tool) => <ToolRow key={tool.tool_id || tool.name} tool={tool} />)}
        </div>
      )}
    </div>
  );
}

export default function ToolsCockpit({ onRefresh }) {
  const [toolsData, setToolsData] = useState(null);
  const [overview, setOverview] = useState(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState(null);

  const fetchTools = async () => {
    setLoading(true);
    setError(null);
    try {
      const [catalogData, overviewData] = await Promise.all([
        api.get("/api/tools"),
        api.get("/api/tools/observability/overview"),
      ]);
      setToolsData(catalogData);
      setOverview(overviewData);
    } catch (e) {
      setError(e.message || "Failed to load tools catalog");
    } finally {
      setLoading(false);
    }
  };

  useEffect(() => { fetchTools(); }, []);

  const groups = overview?.registry?.groups || {};
  const unavailableMcp = (groups.mcp || []).filter((tool) => tool.availability_status !== "available");
  const activeMcp = (groups.mcp || []).filter((tool) => tool.availability_status === "available");
  const externalApi = groups.external_api || [];

  return (
    <div className="page">
      <PageHeader
        title="Tools Catalog"
        subtitle="Personal OS, cron, MCP, and removed tools."
        actions={<button className="btn btn-primary" onClick={() => { fetchTools(); if (onRefresh) onRefresh(); }}>Refresh</button>}
      />
      {error ? <Notice kind="error">Error: {error}</Notice> : null}
      {loading ? <Spinner label="Loading tools catalog..." /> : (
        <>
          <div className="metric-grid">
            <div className="metric-card"><h4>Legacy API Shape</h4><div className="metric-value">{toolsData?.total_tools || 0}</div><div className="metric-meta">Active catalog entries</div></div>
            <div className="metric-card"><h4>Bindable</h4><div className="metric-value">{overview?.status?.registry?.total_bindable_tools || 0}</div><div className="metric-meta">Primary agent tools</div></div>
            <div className="metric-card"><h4>Removed</h4><div className="metric-value">{groups.removed?.length || 0}</div><div className="metric-meta">Blocked metadata entries</div></div>
          </div>
          <div className="catalog-grid">
            <Group title="Personal OS" tools={groups.personal_os || []} />
            <Group title="Cron Boundary" tools={groups.cron || []} />
            <Group title="Provider-managed MCP Available" tools={activeMcp} empty="No MCP provider tools are currently available." />
            <Group title="Direct API Providers" tools={externalApi} empty="No direct API provider tools are currently available." />
            <Group title="Unavailable MCP Providers/Tools" tools={unavailableMcp} />
            <Group title="Removed/Blocked Tools" tools={groups.removed || []} empty="No removed-tool metadata found." />
          </div>
        </>
      )}
    </div>
  );
}

if (typeof window !== "undefined") {
  window.ToolsCockpit = ToolsCockpit;
}
