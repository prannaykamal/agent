import React, { useEffect, useState } from "react";
import { api } from "../api/client.js";
import PageHeader from "./ui/PageHeader.jsx";
import Notice from "./ui/Notice.jsx";
import Spinner from "./ui/Spinner.jsx";
import Badge from "./ui/Badge.jsx";

const SEARCH_TYPES = ["GRAPH_COMPLETION", "RAG_COMPLETION", "CHUNKS", "SUMMARIES"];

export default function MemoryCockpit({ onRefresh }) {
  const [activeSubTab, setActiveSubTab] = useState("recall");
  const [backend, setBackend] = useState(null);
  const [soulMd, setSoulMd] = useState("");
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState(null);
  const [successNotice, setSuccessNotice] = useState(null);

  const [searchQuery, setSearchQuery] = useState("");
  const [searchType, setSearchType] = useState("");
  const [searching, setSearching] = useState(false);
  const [results, setResults] = useState(null);

  const [factCategory, setFactCategory] = useState("user_preference");
  const [factText, setFactText] = useState("");
  const [submittingFact, setSubmittingFact] = useState(false);

  const [procName, setProcName] = useState("");
  const [procDescription, setProcDescription] = useState("");
  const [procKeywords, setProcKeywords] = useState("");
  const [procSteps, setProcSteps] = useState("");
  const [submittingProc, setSubmittingProc] = useState(false);

  const fetchOverview = async () => {
    setLoading(true);
    setError(null);
    try {
      const data = await api.get("/api/memory/full");
      setBackend(data.backend || null);
      setSoulMd(data.soul_md || "");
    } catch (e) {
      setError(e.message || "Failed to load memory status");
    } finally {
      setLoading(false);
    }
  };

  useEffect(() => {
    fetchOverview();
  }, []);

  const runSearch = async () => {
    if (!searchQuery.trim()) return;
    setSearching(true);
    setError(null);
    try {
      const body = { query: searchQuery.trim() };
      if (searchType) body.search_type = searchType;
      setResults(await api.post("/api/memory/search", body));
    } catch (e) {
      setError(`Search failed: ${e.message}`);
    } finally {
      setSearching(false);
    }
  };

  const queuedNotice = (label, res) =>
    `${label} queued (${res.inserted ? "new" : "already queued"}). It becomes searchable once the memory worker processes it.`;

  const handleAddFact = async (e) => {
    e.preventDefault();
    if (!factText.trim()) {
      setError("Fact text must not be empty.");
      return;
    }
    setSubmittingFact(true);
    setError(null);
    setSuccessNotice(null);
    try {
      const res = await api.post("/api/memory/fact", { category: factCategory.trim(), fact_text: factText.trim() });
      setSuccessNotice(queuedNotice("Fact", res));
      setFactText("");
      if (onRefresh) onRefresh();
    } catch (e) {
      setError(`Failed to add fact: ${e.message}`);
    } finally {
      setSubmittingFact(false);
    }
  };

  const handleAddProcedure = async (e) => {
    e.preventDefault();
    if (!procName.trim() || !procSteps.trim()) {
      setError("Procedure name and steps must not be empty.");
      return;
    }
    setSubmittingProc(true);
    setError(null);
    setSuccessNotice(null);
    try {
      const res = await api.post("/api/memory/procedure", {
        name: procName.trim(),
        description: procDescription.trim(),
        trigger_keywords: procKeywords.trim(),
        execution_steps: procSteps.trim(),
      });
      setSuccessNotice(queuedNotice(`Procedure '${procName.trim()}'`, res));
      setProcName("");
      setProcDescription("");
      setProcKeywords("");
      setProcSteps("");
    } catch (e) {
      setError(`Failed to add procedure: ${e.message}`);
    } finally {
      setSubmittingProc(false);
    }
  };

  return (
    <div className="page">
      <PageHeader
        title="Memory"
        subtitle="One cognee knowledge graph. Jev decides what to store and when to recall."
        actions={<button className="btn btn-primary" onClick={() => { fetchOverview(); if (onRefresh) onRefresh(); }}>Refresh</button>}
      />

      {successNotice ? <Notice kind="ok">{successNotice}</Notice> : null}
      {error ? <Notice kind="error">Error: {error}</Notice> : null}

      {loading && !backend ? (
        <Spinner label="Loading memory status..." />
      ) : backend ? (
        <section className="glass-card">
          <div className="chip-row">
            <Badge value={backend.available ? "available" : "unavailable"} />
            <span className="lede">dataset <code>{backend.dataset_name}</code></span>
            <span className="lede">search <code>{backend.search_type}</code></span>
            <span className="lede">idle merge after <code>{backend.session_idle_timeout_minutes} min</code></span>
            {!backend.storage_enabled ? <Badge value="storage off" /> : null}
            {!backend.retrieval_enabled ? <Badge value="retrieval off" /> : null}
            {backend.version ? <span className="lede">cognee <code>{backend.version}</code></span> : null}
          </div>
          {!backend.available && backend.error ? <div className="lede" style={{ marginTop: 8 }}>{backend.error}</div> : null}
        </section>
      ) : null}

      <div className="tabs">
        {[
          { id: "recall", label: "Recall" },
          { id: "teach", label: "Teach" },
          { id: "soul", label: "SOUL.md" },
        ].map((tab) => (
          <button key={tab.id} className={`tab ${activeSubTab === tab.id ? "active" : ""}`} onClick={() => setActiveSubTab(tab.id)}>
            {tab.label}
          </button>
        ))}
      </div>

      {activeSubTab === "recall" && (
        <>
          <section className="glass-card">
            <div className="actions">
              <input
                value={searchQuery}
                onChange={(e) => setSearchQuery(e.target.value)}
                onKeyDown={(e) => e.key === "Enter" && runSearch()}
                placeholder="Ask the knowledge graph, e.g. what does the user prefer for summaries?"
              />
              <select value={searchType} onChange={(e) => setSearchType(e.target.value)}>
                <option value="">Default search</option>
                {SEARCH_TYPES.map((type) => <option key={type} value={type}>{type}</option>)}
              </select>
              <button className="btn btn-primary" onClick={runSearch} disabled={searching}>{searching ? "Searching..." : "Search"}</button>
            </div>
            <div className="lede" style={{ marginTop: 10 }}>Searches the main graph only. Sessions join it after they go idle.</div>
          </section>
          {results ? (
            <section className="glass-card">
              <h3>Results ({results.memories?.length || 0}) <span className="lede">{results.search_type}</span></h3>
              {results.error ? <Notice kind="error">{results.error}</Notice> : null}
              {(results.memories || []).length === 0 ? (
                <div className="lede">Nothing relevant in memory yet.</div>
              ) : (
                results.memories.map((item, i) => (
                  <div key={i} className="row-card">
                    <span style={{ whiteSpace: "pre-wrap" }}>{item.content}</span>
                  </div>
                ))
              )}
            </section>
          ) : null}
        </>
      )}

      {activeSubTab === "teach" && (
        <>
          <section className="glass-card">
            <h3>Add fact</h3>
            <form onSubmit={handleAddFact} className="form-grid" style={{ marginTop: 12 }}>
              <label className="field">
                Category
                <input value={factCategory} onChange={(e) => setFactCategory(e.target.value)} placeholder="e.g. user_preference" />
              </label>
              <label className="field">
                Fact Text
                <input value={factText} onChange={(e) => setFactText(e.target.value)} placeholder="e.g. User prefers concise bullet points for summaries." />
              </label>
              <button type="submit" className="btn btn-primary" disabled={submittingFact}>
                {submittingFact ? "Saving..." : "Save Fact"}
              </button>
            </form>
          </section>
          <section className="glass-card">
            <h3>Add procedure</h3>
            <form onSubmit={handleAddProcedure} style={{ display: "flex", flexDirection: "column", gap: 12, marginTop: 12 }}>
              <div className="form-grid">
                <label className="field">Name<input value={procName} onChange={(e) => setProcName(e.target.value)} placeholder="e.g. weekly inbox digest" /></label>
                <label className="field">Purpose<input value={procDescription} onChange={(e) => setProcDescription(e.target.value)} placeholder="Summarize unread email into action items" /></label>
              </div>
              <label className="field">Use when (keywords)
                <input value={procKeywords} onChange={(e) => setProcKeywords(e.target.value)} placeholder="summarize, inbox, digest" />
              </label>
              <label className="field">Steps
                <textarea rows={3} value={procSteps} onChange={(e) => setProcSteps(e.target.value)} placeholder={"1. Fetch unread email\n2. Extract the top 3 action items\n3. Format as bullets"} />
              </label>
              <div className="actions" style={{ justifyContent: "flex-end" }}>
                <button type="submit" className="btn btn-primary" disabled={submittingProc}>{submittingProc ? "Saving..." : "Save Procedure"}</button>
              </div>
            </form>
          </section>
        </>
      )}

      {activeSubTab === "soul" && (
        <section className="glass-card">
          <h3>SOUL.md</h3>
          <pre className="md-block">{soulMd || "(Empty SOUL.md)"}</pre>
        </section>
      )}
    </div>
  );
}

if (typeof window !== "undefined") {
  window.MemoryCockpit = MemoryCockpit;
}
