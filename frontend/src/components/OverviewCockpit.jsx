import React, { useEffect, useState } from "react";
import { api } from "../api/client.js";
import PageHeader from "./ui/PageHeader.jsx";
import Notice from "./ui/Notice.jsx";
import Spinner from "./ui/Spinner.jsx";
import Badge from "./ui/Badge.jsx";
import { formatBytes, statusTone } from "../lib/format.js";

function StatusBadge({ status }) {
  return <Badge value={status} />;
}

export default function OverviewCockpit({ activeSessionId, onRefresh }) {
  const [telemetry, setTelemetry] = useState(null);
  const [health, setHealth] = useState(null);
  const [integrations, setIntegrations] = useState(null);
  const [mcpProviders, setMcpProviders] = useState([]);
  const [externalProviders, setExternalProviders] = useState([]);
  const [workerObs, setWorkerObs] = useState(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState(null);
  const [backups, setBackups] = useState([]);
  const [totalBackups, setTotalBackups] = useState(0);
  const [loadingBackups, setLoadingBackups] = useState(false);
  const [creatingBackup, setCreatingBackup] = useState(false);
  const [restoringBackup, setRestoringBackup] = useState(false);
  const [selectedBackupForRestore, setSelectedBackupForRestore] = useState(null);
  const [customBackupPath, setCustomBackupPath] = useState("");
  const [backupNotice, setBackupNotice] = useState(null);
  const [backupError, setBackupError] = useState(null);

  const fetchOverview = async () => {
    setLoading(true);
    setError(null);
    try {
      const sess = activeSessionId || "default_session";
      const [histRes, healthRes, intRes, mcpRes, externalRes, workerRes] = await Promise.allSettled([
        api.get(`/api/history/${sess}`),
        api.get("/api/system/health"),
        api.get("/api/integrations/status"),
        api.get("/api/tools/mcp/providers"),
        api.get("/api/tools/external/providers"),
        api.get("/api/memory/observability/workers"),
      ]);

      const dataHist = histRes.status === "fulfilled" ? histRes.value : {};
      const dataHealth = healthRes.status === "fulfilled" ? healthRes.value : null;
      const dataInt = intRes.status === "fulfilled" ? intRes.value : null;
      const dataMcp = mcpRes.status === "fulfilled" ? mcpRes.value : null;
      const dataExternal = externalRes.status === "fulfilled" ? externalRes.value : null;
      const dataWorkers = workerRes.status === "fulfilled" ? workerRes.value : null;

      setHealth(dataHealth);
      setIntegrations(dataInt?.integrations || null);
      setMcpProviders((dataMcp?.providers || []).map((p) => ({ ...p, provider_layer: "mcp" })));
      setExternalProviders((dataExternal?.providers || []).map((p) => ({ ...p, provider_layer: "external_api" })));
      setWorkerObs(dataWorkers?.summary || null);
      setTelemetry({
        session_id: sess,
        total_turns: dataHist.total_turns || 0,
        gate_status: "Active (Hybrid SQL/FTS5)",
        tool_status: "Personal OS + cron + provider-managed MCP + direct APIs",
        memory_sync: "Synced (.agent/MEMORY.md)",
      });
    } catch (e) {
      setError(e.message || "Failed to load telemetry");
    } finally {
      setLoading(false);
    }
  };

  const fetchBackups = async () => {
    setLoadingBackups(true);
    try {
      const data = await api.get("/api/system/backups");
      setBackups(data.backups || []);
      setTotalBackups(data.total_backups || 0);
    } catch (e) {
      setBackupError(`Failed to load backups list: ${e.message}`);
    } finally {
      setLoadingBackups(false);
    }
  };

  useEffect(() => {
    fetchOverview();
    fetchBackups();
  }, [activeSessionId]);

  const handleCreateBackup = async () => {
    setCreatingBackup(true);
    setBackupNotice(null);
    setBackupError(null);
    try {
      const res = await api.post("/api/system/backup");
      setBackupNotice(
        `Backup archive created successfully! Location: ${res.backup_path} (${res.packed_files?.length || 0} files packed, ${formatBytes(res.size_bytes)})`
      );
      fetchBackups();
    } catch (e) {
      setBackupError(`Backup creation failed: ${e.message}`);
    } finally {
      setCreatingBackup(false);
    }
  };

  const handleConfirmRestore = async (backupPath) => {
    if (!backupPath || !backupPath.trim()) {
      setBackupError("Please specify a valid backup archive path for restore.");
      return;
    }
    setRestoringBackup(true);
    setBackupNotice(null);
    setBackupError(null);
    try {
      const res = await api.post("/api/system/restore", { backup_path: backupPath.trim() });
      setBackupNotice(
        `System restored successfully from '${res.backup_path}'! Restored files: ${(res.restored_files || []).join(", ")}.`
      );
      setSelectedBackupForRestore(null);
      setCustomBackupPath("");
      fetchOverview();
      fetchBackups();
    } catch (e) {
      setBackupError(`Restore failed: ${e.message}`);
    } finally {
      setRestoringBackup(false);
    }
  };

  return (
    <div className="page">
      <PageHeader
        title="Overview"
        subtitle={telemetry?.tool_status}
        actions={
          <button className="btn btn-primary" onClick={() => { fetchOverview(); fetchBackups(); if (onRefresh) onRefresh(); }}>
            Refresh
          </button>
        }
      />

      {error ? <Notice kind="error">Error loading telemetry: {error}</Notice> : null}

      {loading ? (
        <Spinner label="Loading…" />
      ) : (
        <>
          <div className="metric-grid">
            <div className="metric-card">
              <h4>Session</h4>
              <div className="metric-value">{telemetry?.session_id || "default_session"}</div>
              <div className="metric-meta">{telemetry?.total_turns || 0} turns</div>
            </div>
            <div className="metric-card">
              <h4>Database</h4>
              <div className="metric-value">{health?.schema_version != null ? `SQLite v${health.schema_version}` : "SQLite"}</div>
              <div className="metric-meta">{health?.database_path ? String(health.database_path).split(/[\\/]/).pop() : "unavailable"}</div>
            </div>
            <div className="metric-card">
              <h4>Health</h4>
              <div className="metric-value">{health?.status || "unknown"}</div>
              <div className="metric-meta">Worker: {health?.worker_status || "STOPPED"}</div>
            </div>
            <div className="metric-card">
              <h4>Memory workers</h4>
              <div className="metric-value">{workerObs ? `${workerObs.active ?? 0} active / ${workerObs.total ?? 0}` : "0 / 0"}</div>
              <div className="metric-meta">Stale: {workerObs ? (workerObs.stale ?? 0) : 0}</div>
            </div>
          </div>

          <section className="glass-card">
            <div className="card-head"><h3>Integrations</h3></div>
            {integrations ? (
              <div className="provider-grid">
                {Object.entries(integrations).map(([key, item]) => (
                  <div key={key} className={`provider-card is-${statusTone(item.status)}`}>
                    <div className="actions" style={{ justifyContent: "space-between" }}>
                      <strong>{item.name || key.toUpperCase()}</strong>
                      <StatusBadge status={item.status} />
                    </div>
                    <div className="lede">{item.description}</div>
                    <div className="lede">Mode: <code>{item.mode}</code></div>
                  </div>
                ))}
              </div>
            ) : (
              <div className="lede">No integration status response.</div>
            )}
          </section>

          <section className="glass-card">
            <div className="card-head"><h3>MCP providers</h3></div>
            {mcpProviders.length > 0 ? (
              <div className="provider-grid">
                {mcpProviders.map((p) => (
                  <div key={p.provider_id} className={`provider-card is-${statusTone(p.availability_status)}`}>
                    <div className="actions" style={{ justifyContent: "space-between" }}>
                      <strong><code>{p.provider_id}</code></strong>
                      <StatusBadge status={p.availability_status} />
                    </div>
                    <div className="lede">
                      Layer: <code>{p.provider_layer === "external_api" ? "Direct API" : "MCP"}</code>
                      {" · "}Transport: <code>{p.transport_type || p.transport || "external_api"}</code>
                      {" · "}Tools: <strong>{p.tool_count ?? (p.capabilities?.length || 0)}</strong>
                    </div>
                    {p.last_error ? <div className="notice notice-error">{p.last_error}</div> : null}
                  </div>
                ))}
              </div>
            ) : (
              <div className="lede">No providers registered.</div>
            )}
          </section>

          {externalProviders.length > 0 ? (
            <section className="glass-card">
              <div className="card-head"><h3>Direct API Providers</h3></div>
              <div className="provider-grid">
                {externalProviders.map((p) => (
                  <div key={p.provider_id} className={`provider-card is-${statusTone(p.availability_status)}`}>
                    <div className="actions" style={{ justifyContent: "space-between" }}>
                      <strong><code>{p.provider_id}</code></strong>
                      <StatusBadge status={p.availability_status} />
                    </div>
                    <div className="lede">Layer: Direct API · Tools: {p.tool_count ?? (p.capabilities?.length || 0)}</div>
                  </div>
                ))}
              </div>
            </section>
          ) : null}

          <section className="glass-card">
            <div className="card-head">
              <div>
                <h3>Backups</h3>
                <p className="lede">Includes state.db, SOUL.md, MEMORY.md, SKILL.md. {totalBackups} on disk.</p>
              </div>
              <button className="btn btn-primary" disabled={creatingBackup} onClick={handleCreateBackup}>
                {creatingBackup ? "Creating…" : "Create backup"}
              </button>
            </div>

            {backupNotice ? <Notice kind="ok">{backupNotice}</Notice> : null}
            {backupError ? <Notice kind="error">{backupError}</Notice> : null}

            {selectedBackupForRestore ? (
              <div className="danger-panel" style={{ margin: "12px 0" }}>
                <h4 style={{ color: "var(--danger)", marginBottom: 8 }}>Restore this backup?</h4>
                <p className="lede">
                  You are about to restore system state from: <code>{selectedBackupForRestore.path || selectedBackupForRestore.filename}</code>.
                  This will overwrite active database records, memory files, and skills. A safety rollback copy (<code>state.db.bak</code>) will be saved automatically.
                </p>
                <div className="actions" style={{ justifyContent: "flex-end", marginTop: 12 }}>
                  <button className="btn btn-ghost" onClick={() => setSelectedBackupForRestore(null)}>Cancel</button>
                  <button
                    className="btn btn-danger"
                    disabled={restoringBackup}
                    onClick={() => handleConfirmRestore(selectedBackupForRestore.path || selectedBackupForRestore.filename)}
                  >
                    {restoringBackup ? "Restoring System..." : "Confirm System Restore"}
                  </button>
                </div>
              </div>
            ) : null}

            {loadingBackups ? (
              <Spinner label="Loading available backups..." />
            ) : backups.length === 0 ? (
              <div className="lede">No backups yet.</div>
            ) : (
              backups.map((b) => (
                <div key={b.filename} className="row-card">
                  <div>
                    <strong>{b.filename}</strong>
                    <div className="lede">Created: {b.created_at} · Size: {formatBytes(b.size_bytes)}</div>
                  </div>
                  <button className="btn btn-danger btn-sm" onClick={() => setSelectedBackupForRestore(b)}>Restore</button>
                </div>
              ))
            )}

            <div className="form-grid" style={{ marginTop: 16, paddingTop: 12, borderTop: "1px solid var(--border-glass)" }}>
              <label className="field" style={{ gridColumn: "1 / -1" }}>
                Restore from custom file path
                <div className="actions">
                  <input
                    value={customBackupPath}
                    onChange={(e) => setCustomBackupPath(e.target.value)}
                    placeholder="/path/to/agent_backup_....zip"
                  />
                  <button
                    className="btn btn-danger"
                    disabled={!customBackupPath.trim()}
                    onClick={() => setSelectedBackupForRestore({ path: customBackupPath, filename: customBackupPath })}
                  >
                    Inspect & Restore
                  </button>
                </div>
              </label>
            </div>
          </section>
        </>
      )}
    </div>
  );
}

if (typeof window !== "undefined") {
  window.OverviewCockpit = OverviewCockpit;
}
