import React, { useState } from "react";
import { api } from "../api/client.js";
import PageHeader from "./ui/PageHeader.jsx";
import Notice from "./ui/Notice.jsx";
import Badge from "./ui/Badge.jsx";
import { formatJson, previewText } from "../lib/format.js";

function ResultBlock({ title, payload }) {
  if (payload == null) return null;
  const text = typeof payload === "string" ? payload : formatJson(payload);
  return (
    <section className="glass-card">
      <h3>{title}</h3>
      <pre className="json-block">{text}</pre>
    </section>
  );
}

export default function WorkspaceCockpit({ onOpenApprovals }) {
  const [tab, setTab] = useState("search");
  const [notice, setNotice] = useState(null);
  const [error, setError] = useState(null);
  const [busy, setBusy] = useState(false);

  const [searchQuery, setSearchQuery] = useState("");
  const [maxResults, setMaxResults] = useState(5);
  const [searchResult, setSearchResult] = useState(null);

  const [calStart, setCalStart] = useState("");
  const [calEnd, setCalEnd] = useState("");
  const [calRead, setCalRead] = useState(null);
  const [calTitle, setCalTitle] = useState("");
  const [calStartTime, setCalStartTime] = useState("");
  const [calEndTime, setCalEndTime] = useState("");
  const [calLocation, setCalLocation] = useState("");
  const [calAttendees, setCalAttendees] = useState("");

  const [mailQuery, setMailQuery] = useState("");
  const [mailLimit, setMailLimit] = useState(10);
  const [mailRead, setMailRead] = useState(null);
  const [mailTo, setMailTo] = useState("");
  const [mailSubject, setMailSubject] = useState("");
  const [mailBody, setMailBody] = useState("");

  const run = async (fn) => {
    setBusy(true);
    setError(null);
    setNotice(null);
    try {
      await fn();
    } catch (e) {
      setError(e.message || "Workspace request failed");
    } finally {
      setBusy(false);
    }
  };

  const handleApprovalResponse = (data, fallback) => {
    if (data?.status === "APPROVAL_REQUIRED") {
      const id = data.approval_request?.id || data.approval_request?.request_id;
      setNotice(`${data.message || fallback} Request ID: ${id || "pending"}. Open Approvals to decide.`);
      return;
    }
    setNotice(data?.message || fallback);
  };

  const handleSearch = () => run(async () => {
    const data = await api.get(`/api/search?q=${encodeURIComponent(searchQuery)}&max_results=${maxResults}`);
    setSearchResult(data);
    if (!data.total_results) setNotice("Search returned no results. The provider may be unavailable or unconfigured.");
  });

  const handleCalendarRead = () => run(async () => {
    const params = new URLSearchParams();
    if (calStart) params.set("start_date", calStart);
    if (calEnd) params.set("end_date", calEnd);
    const qs = params.toString();
    const data = await api.get(`/api/calendar/events${qs ? `?${qs}` : ""}`);
    setCalRead(data);
  });

  const handleCalendarCreate = () => run(async () => {
    const data = await api.post("/api/calendar/events", {
      title: calTitle,
      start_time: calStartTime,
      end_time: calEndTime,
      attendees: calAttendees,
      location: calLocation,
      status: "CONFIRMED",
    });
    handleApprovalResponse(data, "Calendar create submitted.");
  });

  const handleMailRead = () => run(async () => {
    const params = new URLSearchParams({ limit: String(mailLimit) });
    if (mailQuery) params.set("query", mailQuery);
    const data = await api.get(`/api/email/messages?${params.toString()}`);
    setMailRead(data);
  });

  const handleMailDraft = () => run(async () => {
    const data = await api.post("/api/email/draft", { to: mailTo, subject: mailSubject, body: mailBody });
    setNotice(data.message || "Draft created.");
    setMailRead(data);
  });

  const handleMailSend = () => run(async () => {
    const data = await api.post("/api/email/send", { to: mailTo, subject: mailSubject, body: mailBody });
    handleApprovalResponse(data, "Send submitted.");
  });

  return (
    <div className="page">
      <PageHeader
        title="Workspace"
        subtitle="Search, calendar, and mail. High-risk writes wait in Approvals."
        actions={onOpenApprovals ? <button className="btn btn-ghost" onClick={onOpenApprovals}>Open Approvals</button> : null}
      />

      <div className="tabs">
        {[
          { id: "search", label: "Search" },
          { id: "calendar", label: "Calendar" },
          { id: "mail", label: "Mail" },
        ].map((item) => (
          <button key={item.id} className={`tab ${tab === item.id ? "active" : ""}`} onClick={() => setTab(item.id)}>{item.label}</button>
        ))}
      </div>

      {notice ? <Notice kind="ok">{notice}</Notice> : null}
      {error ? <Notice kind="error">{error}</Notice> : null}

      {tab === "search" && (
        <>
          <section className="glass-card">
            <h3>Search</h3>
            <div className="form-grid" style={{ marginTop: 12 }}>
              <label className="field" style={{ gridColumn: "span 2" }}>Query
                <input value={searchQuery} onChange={(e) => setSearchQuery(e.target.value)} onKeyDown={(e) => e.key === "Enter" && handleSearch()} placeholder="Search the web" />
              </label>
              <label className="field">Max results
                <select value={maxResults} onChange={(e) => setMaxResults(Number(e.target.value))}>
                  <option value={3}>3</option>
                  <option value={5}>5</option>
                  <option value={8}>8</option>
                </select>
              </label>
              <button className="btn btn-primary" onClick={handleSearch} disabled={!searchQuery.trim() || busy}>Search</button>
            </div>
          </section>
          {searchResult ? (
            <section className="glass-card">
              <div className="card-head">
                <h3>Results for “{searchResult.query}”</h3>
                <Badge value={`${searchResult.total_results || 0} hits`} />
              </div>
              {(searchResult.results || []).length === 0 ? (
                <div className="lede">No structured hits. Provider output may still appear below.</div>
              ) : (
                (searchResult.results || []).map((item, idx) => (
                  <div key={idx} className="row-card">
                    <div>
                      <strong>{item.title || item.name || `Result ${idx + 1}`}</strong>
                      <div className="lede">{item.snippet || item.content || previewText(item)}</div>
                      {item.url ? <a href={item.url} target="_blank" rel="noreferrer">{item.url}</a> : null}
                    </div>
                  </div>
                ))
              )}
            </section>
          ) : null}
        </>
      )}

      {tab === "calendar" && (
        <>
          <section className="glass-card">
            <h3>Availability / inspect</h3>
            <div className="form-grid" style={{ marginTop: 12 }}>
              <label className="field">Start date<input value={calStart} onChange={(e) => setCalStart(e.target.value)} placeholder="2026-08-13" /></label>
              <label className="field">End date<input value={calEnd} onChange={(e) => setCalEnd(e.target.value)} placeholder="2026-08-20" /></label>
              <button className="btn btn-primary" onClick={handleCalendarRead} disabled={busy}>Load events</button>
            </div>
          </section>
          <ResultBlock title="Calendar provider result" payload={calRead?.result || calRead} />
          <section className="glass-card">
            <h3>Create event</h3>
            <p className="lede">Create and delete require human approval. The backend will pause and emit an approval request.</p>
            <div className="form-grid" style={{ marginTop: 12 }}>
              <label className="field">Title<input value={calTitle} onChange={(e) => setCalTitle(e.target.value)} /></label>
              <label className="field">Start<input value={calStartTime} onChange={(e) => setCalStartTime(e.target.value)} placeholder="2026-08-13 10:00" /></label>
              <label className="field">End<input value={calEndTime} onChange={(e) => setCalEndTime(e.target.value)} placeholder="2026-08-13 11:00" /></label>
              <label className="field">Location<input value={calLocation} onChange={(e) => setCalLocation(e.target.value)} /></label>
              <label className="field">Attendees<input value={calAttendees} onChange={(e) => setCalAttendees(e.target.value)} placeholder="comma-separated" /></label>
              <button className="btn btn-primary" onClick={handleCalendarCreate} disabled={!calTitle.trim() || busy}>Request create</button>
            </div>
          </section>
        </>
      )}

      {tab === "mail" && (
        <>
          <section className="glass-card">
            <h3>Read / search inbox</h3>
            <div className="form-grid" style={{ marginTop: 12 }}>
              <label className="field" style={{ gridColumn: "span 2" }}>Query<input value={mailQuery} onChange={(e) => setMailQuery(e.target.value)} placeholder="optional search query" /></label>
              <label className="field">Limit
                <select value={mailLimit} onChange={(e) => setMailLimit(Number(e.target.value))}>
                  <option value={5}>5</option>
                  <option value={10}>10</option>
                  <option value={20}>20</option>
                </select>
              </label>
              <button className="btn btn-primary" onClick={handleMailRead} disabled={busy}>Load messages</button>
            </div>
          </section>
          <ResultBlock title="Mail provider result" payload={mailRead?.result || mailRead} />
          <section className="glass-card">
            <h3>Compose</h3>
            <p className="lede">Drafts execute immediately. Send is high-risk and requires approval.</p>
            <div className="form-grid" style={{ marginTop: 12 }}>
              <label className="field">To<input value={mailTo} onChange={(e) => setMailTo(e.target.value)} /></label>
              <label className="field">Subject<input value={mailSubject} onChange={(e) => setMailSubject(e.target.value)} /></label>
              <label className="field" style={{ gridColumn: "1 / -1" }}>Body<textarea value={mailBody} onChange={(e) => setMailBody(e.target.value)} /></label>
              <div className="actions">
                <button className="btn btn-ghost" onClick={handleMailDraft} disabled={!mailTo.trim() || busy}>Save draft</button>
                <button className="btn btn-primary" onClick={handleMailSend} disabled={!mailTo.trim() || busy}>Request send</button>
              </div>
            </div>
          </section>
        </>
      )}
    </div>
  );
}

if (typeof window !== "undefined") {
  window.WorkspaceCockpit = WorkspaceCockpit;
}
