import React, { useEffect, useState } from "react";
import { api } from "../api/client.js";
import PageHeader from "./ui/PageHeader.jsx";
import Notice from "./ui/Notice.jsx";
import Spinner from "./ui/Spinner.jsx";
import EmptyState from "./ui/EmptyState.jsx";
import Badge from "./ui/Badge.jsx";

export default function LoopCockpit({ activeSessionId, onRefresh }) {
  const [events, setEvents] = useState([]);
  const [sessions, setSessions] = useState([]);
  const [selectedSession, setSelectedSession] = useState(activeSessionId || "");
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState(null);

  useEffect(() => {
    setSelectedSession(activeSessionId || "");
  }, [activeSessionId]);

  useEffect(() => {
    api.get("/api/sessions").then((data) => {
      setSessions(data.sessions || []);
    }).catch(() => {});
  }, []);

  const loadLoopTrace = async (sessionId) => {
    setLoading(true);
    setError(null);
    const sess = sessionId || selectedSession || activeSessionId || "default_session";
    try {
      let data;
      try {
        data = await api.get(`/api/history/${sess}`);
      } catch {
        data = await api.get(`/api/loop/events/${sess}`);
      }
      const trace = Array.isArray(data.loop_trace)
        ? data.loop_trace
        : (Array.isArray(data.loop_events) ? data.loop_events : []);
      setEvents(trace);
    } catch (e) {
      setError(e.message || "Failed to load loop events");
    } finally {
      setLoading(false);
    }
  };

  useEffect(() => {
    loadLoopTrace(selectedSession || activeSessionId);
  }, [selectedSession, activeSessionId]);

  const sessionOptions = Array.from(new Set([selectedSession, activeSessionId, ...sessions].filter(Boolean)));

  return (
    <div className="page">
      <PageHeader
        title="Loop"
        subtitle={`Session ${selectedSession || activeSessionId || "default_session"}`}
        actions={
          <div className="actions">
            <select
              value={selectedSession || activeSessionId || ""}
              onChange={(e) => setSelectedSession(e.target.value)}
            >
              {sessionOptions.length === 0 ? <option value="">No sessions yet</option> : null}
              {sessionOptions.map((sid) => (
                <option key={sid} value={sid}>{sid}</option>
              ))}
            </select>
            <button className="btn btn-primary" onClick={() => { loadLoopTrace(selectedSession); if (onRefresh) onRefresh(); }}>Refresh</button>
          </div>
        }
      />
      {error ? <Notice kind="error">Error loading loop events: {error}</Notice> : null}
      {loading ? (
        <Spinner label="Loading loop trace..." />
      ) : events.length === 0 ? (
        <EmptyState title="No activity yet" body="No loop events for this session. Send a chat message, or pick another session above." />
      ) : (
        <div className="timeline">
          {events.map((ev, idx) => (
            <div key={idx} className="step">
              <div className="step-rail">
                <div className="step-dot" />
                {idx < events.length - 1 ? <div className="step-line" /> : null}
              </div>
              <div className="glass-card">
                <div className="actions" style={{ justifyContent: "space-between", marginBottom: 6 }}>
                  <strong>Step #{idx + 1} — {ev.step_type || ev.sender || "EVENT"}</strong>
                  <div className="actions">
                    {ev.tool_name ? <Badge value={ev.tool_name} /> : null}
                    {ev.created_at ? <span className="lede">{ev.created_at}</span> : null}
                  </div>
                </div>
                <div>{ev.reasoning || ev.content || ev.text}</div>
                {ev.tool_result ? <pre className="json-block">{String(ev.tool_result).slice(0, 800)}</pre> : null}
              </div>
            </div>
          ))}
        </div>
      )}
    </div>
  );
}

if (typeof window !== "undefined") {
  window.LoopCockpit = LoopCockpit;
}
