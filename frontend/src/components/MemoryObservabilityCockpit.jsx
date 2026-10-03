import React, { useEffect, useState } from "react";
import { api } from "../api/client.js";
import PageHeader from "./ui/PageHeader.jsx";
import Notice from "./ui/Notice.jsx";
import Spinner from "./ui/Spinner.jsx";
import Badge from "./ui/Badge.jsx";
import DataTable from "./ui/DataTable.jsx";

const endpoints = {
  overview: "/api/memory/observability/overview",
  health: "/api/memory/observability/health",
  jobs: "/api/memory/observability/jobs",
  workers: "/api/memory/observability/workers",
  deadLetters: "/api/memory/observability/dead-letter",
  longTerm: "/api/memory/observability/long-term",
};

function StatusPill({ value }) {
  return <Badge value={value || "UNKNOWN"} />;
}

function Metric({ label, value }) {
  return (
    <div className="metric-card">
      <h4>{label}</h4>
      <div className="metric-value">{value ?? 0}</div>
    </div>
  );
}

function Panel({ title, actions, children }) {
  return (
    <section className="glass-card">
      <div className="panel-heading">
        <h3>{title}</h3>
        {actions}
      </div>
      {children}
    </section>
  );
}

function SimpleTable({ rows, emptyText, columns }) {
  return <DataTable rows={rows} emptyText={emptyText} columns={columns} />;
}

export default function MemoryObservabilityCockpit() {
  const [data, setData] = useState({});
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState(null);
  const [traceQuery, setTraceQuery] = useState("");
  const [traceSession, setTraceSession] = useState("default_session");
  const [showPromptBlock, setShowPromptBlock] = useState(false);
  const [trace, setTrace] = useState(null);
  const [traceError, setTraceError] = useState(null);
  const [jobStatus, setJobStatus] = useState("");
  const [includePayload, setIncludePayload] = useState(false);
  const [mergeSession, setMergeSession] = useState("default_session");
  const [merging, setMerging] = useState(false);
  const [mergeNotice, setMergeNotice] = useState(null);

  const loadPanelData = async () => {
    setLoading(true);
    setError(null);
    try {
      const entries = await Promise.allSettled(Object.entries(endpoints).map(async ([key, url]) => {
        let target = url;
        if (key === "jobs") {
          const params = new URLSearchParams();
          if (jobStatus) params.set("status", jobStatus);
          if (includePayload) params.set("include_payload", "true");
          const qs = params.toString();
          target = qs ? `${url}?${qs}` : url;
        }
        const payload = await api.get(target);
        return [key, payload];
      }));
      const next = {};
      const failed = [];
      entries.forEach((entry, index) => {
        const key = Object.keys(endpoints)[index];
        if (entry.status === "fulfilled") {
          next[entry.value[0]] = entry.value[1];
        } else {
          failed.push(key);
        }
      });
      setData(next);
      if (failed.length && Object.keys(next).length === 0) {
        setError("Failed to load memory observability");
      } else if (failed.length) {
        setError(`Some panels failed to load: ${failed.join(", ")}`);
      }
    } catch (err) {
      console.error(err);
      setError(err.message || "Failed to load memory observability");
    } finally {
      setLoading(false);
    }
  };

  const handleMergeSession = async () => {
    if (!mergeSession.trim()) return;
    setMerging(true);
    setMergeNotice(null);
    try {
      const payload = await api.post(`/api/memory/sessions/${encodeURIComponent(mergeSession.trim())}/merge`, {});
      setMergeNotice({
        kind: payload.inserted ? "ok" : "info",
        text: payload.inserted ? "Merge queued. The worker will merge this session into the main graph." : "A merge for this session is already queued.",
      });
      await loadPanelData();
    } catch (err) {
      console.error(err);
      setMergeNotice({ kind: "error", text: err.message || "Failed to queue merge" });
    } finally {
      setMerging(false);
    }
  };

  const handleTrace = async (e) => {
    if (e && e.preventDefault) e.preventDefault();
    setTraceError(null);
    setTrace(null);
    if (!traceQuery.trim()) {
      setTraceError("Query must be non-empty.");
      return;
    }
    try {
      const payload = await api.post("/api/memory/observability/retrieval/trace", {
        query: traceQuery.trim(),
        session_id: traceSession || "default_session",
        include_prompt_block: showPromptBlock,
        include_candidates: true,
      }, { method: 'POST' });
      setTrace(payload);
    } catch (err) {
      console.error(err);
      setTraceError(err.message || "Trace failed");
    }
  };

  useEffect(() => {
    loadPanelData();
  }, []);

  const health = data.health || data.overview?.health || {};
  const jobs = data.jobs || {};
  const workers = data.workers || {};
  const deadLetters = data.deadLetters || {};
  const longTerm = data.longTerm || health.long_term || {};
  const pipeline = longTerm.pipeline || {};
  const pipelineRows = Object.entries(pipeline).map(([jobType, info]) => ({
    job_type: jobType,
    queued: info.by_status?.QUEUED ?? 0,
    running: info.by_status?.RUNNING ?? 0,
    succeeded: info.by_status?.SUCCEEDED ?? 0,
    dead_lettered: info.by_status?.DEAD_LETTERED ?? 0,
    last_succeeded_at: info.last_succeeded_at,
  }));

  return (
    <div className="page">
      <PageHeader
        title="Memory Ops"
        subtitle="Queues, workers, cognee pipeline, and retrieval."
        actions={<button className="btn btn-primary" onClick={loadPanelData}>Refresh</button>}
      />

      {error ? <Notice kind="error">{error}</Notice> : null}
      {loading && !data.health && !(data.jobs) ? <Spinner label="Loading memory observability..." /> : (
        <>
          <Panel title="Health">
            <div className="actions" style={{ marginBottom: 12 }}><span>Status</span><StatusPill value={health.status} /></div>
            <div className="metric-grid">
              <Metric label="Jobs" value={health.queue?.total_jobs} />
              <Metric label="Dead Letters" value={health.queue?.dead_letter_count} />
              <Metric label="Active Workers" value={health.workers?.active_workers ?? health.workers?.active} />
              <Metric label="Session Writes" value={pipeline.memory_session_write?.by_status?.SUCCEEDED} />
              <Metric label="Merges Pending" value={pipeline.memory_session_merge?.by_status?.QUEUED} />
            </div>
          </Panel>

          <Panel title="Queue and Workers">
            <div className="actions" style={{ marginBottom: 12 }}>
              <select value={jobStatus} onChange={(e) => setJobStatus(e.target.value)}>
                <option value="">All job statuses</option>
                <option value="QUEUED">QUEUED</option>
                <option value="RUNNING">RUNNING</option>
                <option value="RETRYING">RETRYING</option>
                <option value="SUCCEEDED">SUCCEEDED</option>
                <option value="DEAD_LETTERED">DEAD_LETTERED</option>
              </select>
              <label className="chip-row">
                <input type="checkbox" checked={includePayload} onChange={(e) => setIncludePayload(e.target.checked)} />
                Include payload
              </label>
              <button className="btn btn-ghost btn-sm" onClick={loadPanelData}>Apply filters</button>
            </div>
            <SimpleTable rows={jobs.jobs || []} emptyText="No memory jobs found." columns={["id", "job_type", "status", "session_id", "attempt_count", "last_error", "created_at"]} />
            <SimpleTable rows={workers.workers || []} emptyText="No worker heartbeats recorded. The memory worker is not auto-started." columns={["worker_id", "status", "current_job_id", "last_heartbeat_at", "stale"]} />
          </Panel>

          <Panel title="Dead Letters">
            <SimpleTable rows={deadLetters.dead_letters || []} emptyText="No dead-lettered memory jobs." columns={["id", "job_id", "job_type", "session_id", "error_message", "failed_at"]} />
          </Panel>

          <Panel title="Retrieval Trace">
            <div className="form-grid">
              <input value={traceQuery} onChange={(e) => setTraceQuery(e.target.value)} placeholder="Query to trace" />
              <input value={traceSession} onChange={(e) => setTraceSession(e.target.value)} placeholder="Session ID" />
              <label className="chip-row">
                <input type="checkbox" checked={showPromptBlock} onChange={(e) => setShowPromptBlock(e.target.checked)} /> Show redacted prompt block
              </label>
              <button className="btn btn-primary" onClick={handleTrace}>Trace</button>
            </div>
            {traceError ? <Notice kind="error">{traceError}</Notice> : null}
            {trace ? (
              <div className="split" style={{ marginTop: 12, gridTemplateColumns: "minmax(220px, 0.8fr) 1fr" }}>
                <pre className="json-block">{JSON.stringify({ gate: trace.gate, search_type: trace.search_type, available: trace.available, error: trace.error, token_count: trace.token_count, prompt_block: trace.prompt_block }, null, 2)}</pre>
                <SimpleTable
                  rows={(trace.candidates || []).map((candidate) => ({
                    rank: candidate.rank,
                    content: candidate.content_preview,
                  }))}
                  emptyText="Nothing recalled."
                  columns={["rank", "content"]}
                />
              </div>
            ) : <div className="lede">Run a trace to see exactly what cognee recalls for a chat turn.</div>}
          </Panel>

          <Panel
            title="Knowledge Graph (cognee)"
            actions={
              <div className="actions">
                <input value={mergeSession} onChange={(e) => setMergeSession(e.target.value)} placeholder="Session ID" />
                <button className="btn btn-primary btn-sm" onClick={handleMergeSession} disabled={merging}>
                  {merging ? "Queuing…" : "Merge session now"}
                </button>
              </div>
            }
          >
            {mergeNotice ? <Notice kind={mergeNotice.kind}>{mergeNotice.text}</Notice> : null}
            <div className="actions" style={{ marginBottom: 12 }}>
              <span>Backend</span>
              <StatusPill value={longTerm.available ? "AVAILABLE" : "UNAVAILABLE"} />
              <span className="lede">dataset <code>{longTerm.dataset_name || "-"}</code> · search <code>{longTerm.search_type || "-"}</code></span>
            </div>
            <div className="actions" style={{ marginBottom: 12 }}>
              <span>Jev</span>
              <StatusPill value={longTerm.jev?.configured ? "CONFIGURED" : "NOT CONFIGURED"} />
              <span className="lede">model <code>{longTerm.jev?.model || "-"}</code> · tool review {longTerm.jev?.tool_review_enabled ? "on" : "off"}</span>
            </div>
            {longTerm.error ? <Notice kind="error">{longTerm.error}</Notice> : null}
            <SimpleTable rows={pipelineRows} emptyText="No cognee jobs yet." columns={["job_type", "queued", "running", "succeeded", "dead_lettered", "last_succeeded_at"]} />
          </Panel>
        </>
      )}
    </div>
  );
}

if (typeof window !== "undefined") {
  window.MemoryObservabilityCockpit = MemoryObservabilityCockpit;
}
