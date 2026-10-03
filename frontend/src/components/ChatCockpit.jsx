import React, { useEffect, useRef, useState } from "react";
import { api } from "../api/client.js";
import PageHeader from "./ui/PageHeader.jsx";
import Notice from "./ui/Notice.jsx";
import Spinner from "./ui/Spinner.jsx";
import Badge from "./ui/Badge.jsx";
import { groupLoopTrace, readSseStream, stepFailed, stepTitle, visibleSteps } from "../lib/chatActivity.js";

const CHAT_TIMEOUT_MS = 180000;

function ActivityCard({ steps, live, defaultOpen }) {
  const shown = visibleSteps(steps);
  const [open, setOpen] = useState(Boolean(defaultOpen || live));
  useEffect(() => {
    if (live) setOpen(true);
  }, [live, shown.length]);
  const current = live ? shown[shown.length - 1] : null;
  const failed = shown.some(stepFailed);
  return (
    <div className={`activity-card ${live ? "is-live" : ""} ${failed ? "is-failed" : ""}`}>
      <button type="button" className="activity-toggle" onClick={() => setOpen((value) => !value)}>
        <span className={`activity-chevron ${open ? "open" : ""}`}>▸</span>
        <span className="activity-title">{live ? "Activity" : "Steps"}</span>
        <span className="lede">
          {live && current ? stepTitle(current) : `${shown.length} step${shown.length === 1 ? "" : "s"}`}
        </span>
        {live ? <span className="activity-pulse" /> : null}
      </button>
      {open ? (
        <ol className="activity-steps">
          {shown.map((step, index) => {
            const running = live && index === shown.length - 1;
            const failedStep = stepFailed(step);
            const result = String(step.tool_result || "").trim();
            const detail = String(step.reasoning || "").trim();
            return (
              <li key={step.id || `${step.step_type}-${index}`} className={`activity-step ${running ? "is-running" : "is-done"} ${failedStep ? "is-failed" : ""}`}>
                <span className="activity-marker">{running ? <span className="spinner spinner-sm" /> : failedStep ? "!" : "✓"}</span>
                <div>
                  <div className="activity-step-title">{stepTitle(step)}</div>
                  {detail && detail !== stepTitle(step) ? <div className="lede">{detail.slice(0, 220)}</div> : null}
                  {result && String(step.step_type).toUpperCase() === "TOOL_EXECUTED" ? (
                    <pre className="activity-result">{result.slice(0, 400)}</pre>
                  ) : null}
                </div>
              </li>
            );
          })}
        </ol>
      ) : null}
    </div>
  );
}

function transcriptFromHistory(turns, loopTrace) {
  const groups = groupLoopTrace(loopTrace);
  const items = [];
  let groupIndex = 0;
  for (const turn of turns || []) {
    if (turn.sender === "user") {
      items.push({ id: turn.id || `user-${items.length}`, type: "user", text: turn.content, created_at: turn.created_at });
      const steps = groups[groupIndex] || [];
      groupIndex += 1;
      if (steps.length) {
        items.push({ id: `activity-${turn.id || items.length}`, type: "activity", steps, live: false });
      }
    } else if (turn.sender === "assistant") {
      items.push({
        id: turn.id || `assistant-${items.length}`,
        type: "assistant",
        text: turn.content,
        created_at: turn.created_at,
      });
    }
  }
  return items;
}

function itemsFromChatResult(data, liveSteps) {
  const items = [];
  const steps = (data.loop_trace || data.loop_events || []).length
    ? groupLoopTrace(data.loop_trace || data.loop_events).slice(-1)[0] || liveSteps
    : liveSteps;
  if (steps?.length) {
    items.push({ id: `activity-${Date.now()}`, type: "activity", steps, live: false, defaultOpen: true });
  }
  if (data.response) {
    items.push({
      id: `assistant-${Date.now()}`,
      type: "assistant",
      text: data.response,
      retrievalTriggered: data.retrieval_triggered,
      retrievedMemoriesCount: (data.retrieved_memories || []).length,
    });
  }
  if (data.pending_approval_id || data.approval_status === "PENDING" || data.approval_status === "APPROVAL_REQUIRED") {
    items.push({
      id: `approval-${data.pending_approval_id || Date.now()}`,
      type: "approval",
      text: "Reply yes in this chat to approve, or use the buttons below.",
      pendingApprovalId: data.pending_approval_id,
      approvalStatus: data.approval_status || "PENDING",
    });
  }
  return items;
}

export default function ChatCockpit({ activeSessionId, onNewSession, onSessionChanged, onOpenApprovals }) {
  const [items, setItems] = useState([]);
  const [inputMessage, setInputMessage] = useState("");
  const [sessions, setSessions] = useState([]);
  const [currentSession, setCurrentSession] = useState(activeSessionId || "default_session");
  const [provider, setProvider] = useState("openai");
  const [modelName, setModelName] = useState("GPT-5.5");
  const [secondaryProvider, setSecondaryProvider] = useState("openai");
  const [secondaryModelName, setSecondaryModelName] = useState("gpt-4o-mini");
  const [modelCatalog, setModelCatalog] = useState({});
  const [loading, setLoading] = useState(false);
  const [historyLoading, setHistoryLoading] = useState(false);
  const [error, setError] = useState(null);
  const [isRenaming, setIsRenaming] = useState(false);
  const [renameInput, setRenameInput] = useState("");
  const [toastMessage, setToastMessage] = useState("");
  const [memoryNotice, setMemoryNotice] = useState(null);
  const [savingMemory, setSavingMemory] = useState(false);
  const scrollerRef = useRef(null);
  const historyReq = useRef(0);
  const abortRef = useRef(null);
  const skipHistorySession = useRef(null);
  const sendingRef = useRef(false);

  const loadSessions = async () => {
    try {
      const data = await api.get("/api/sessions");
      setSessions(data.sessions || []);
    } catch (e) {
      console.error("Failed to load sessions:", e);
    }
  };

  const loadModels = async () => {
    try {
      const data = await api.get("/api/models");
      const catalog = data.catalog || {};
      setModelCatalog(catalog);
      // Start on the server's AI_PROVIDER and its default primary/secondary models.
      const active = catalog.active_provider || "openai";
      const pair = catalog.pairs?.[active] || {};
      setProvider(active);
      setSecondaryProvider(active);
      const primaryDefault = pair.primary || catalog.providers?.[active]?.default;
      if (primaryDefault) setModelName(primaryDefault);
      if (pair.secondary) setSecondaryModelName(pair.secondary);
    } catch (e) {
      console.error("Failed to load models:", e);
    }
  };

  const loadHistory = async (sessId) => {
    const req = ++historyReq.current;
    setHistoryLoading(true);
    setError(null);
    setItems([]);
    try {
      const data = await api.get(`/api/history/${sessId}`);
      if (req !== historyReq.current) return;
      setItems(transcriptFromHistory(data.turns || [], data.loop_trace || data.loop_events || []));
    } catch (e) {
      if (req !== historyReq.current) return;
      console.error(e);
      setError(e.message || "Failed to load conversation history.");
    } finally {
      if (req === historyReq.current) setHistoryLoading(false);
    }
  };

  useEffect(() => {
    loadSessions();
    loadModels();
  }, []);

  useEffect(() => {
    if (!activeSessionId) return;
    setCurrentSession(activeSessionId);
    if (skipHistorySession.current === activeSessionId) {
      skipHistorySession.current = null;
      return;
    }
    loadHistory(activeSessionId);
  }, [activeSessionId]);

  useEffect(() => {
    if (scrollerRef.current) {
      scrollerRef.current.scrollTop = scrollerRef.current.scrollHeight;
    }
  }, [items, loading]);

  const stopRun = () => {
    abortRef.current?.abort();
  };

  const applyFinished = (data, liveSteps, userText) => {
    setItems((prev) => {
      const withoutLive = prev.filter((item) => !(item.type === "activity" && item.live));
      let lastUserIdx = -1;
      withoutLive.forEach((item, index) => {
        if (item.type === "user" && item.text === userText) lastUserIdx = index;
      });
      const head = lastUserIdx >= 0 ? withoutLive.slice(0, lastUserIdx + 1) : withoutLive;
      return [...head, ...itemsFromChatResult(data, liveSteps)];
    });
    if (data.session_id && data.session_id !== currentSession) {
      skipHistorySession.current = data.session_id;
      setCurrentSession(data.session_id);
      if (onSessionChanged) onSessionChanged(data.session_id);
    }
    const responseText = String(data.response || "");
    if (responseText.includes("Primary LLM (Offline)")) {
      const detail = responseText.split("Model call failed:")[1]?.trim();
      setError(detail || "The model call failed. Open a new chat and try again.");
    }
    loadSessions();
  };

  const handleApprovalDecision = async (requestId, decision) => {
    if (!requestId || loading || sendingRef.current) return;
    sendingRef.current = true;
    setLoading(true);
    setError(null);
    try {
      const data = await api.post(`/api/approvals/${requestId}/decision`, { decision });
      setItems((prev) => [
        ...prev.map((item) => (
          item.pendingApprovalId === requestId
            ? { ...item, approvalStatus: data.status || decision, text: decision === "APPROVED" ? "Approved." : "Rejected." }
            : item
        )),
        {
          id: `assistant-${Date.now()}`,
          type: "assistant",
          text: data.response || data.message || (decision === "APPROVED" ? "Approved." : "Rejected."),
        },
      ]);
      loadSessions();
    } catch (e) {
      setError(e.message || "Failed to submit approval.");
    } finally {
      sendingRef.current = false;
      setLoading(false);
    }
  };

  const handleSendMessage = async () => {
    if (!inputMessage.trim() || loading || sendingRef.current) return;
    const userText = inputMessage;
    sendingRef.current = true;
    const activityId = `activity-live-${Date.now()}`;
    setInputMessage("");
    setItems((prev) => [
      ...prev,
      { id: `user-${Date.now()}`, type: "user", text: userText },
      { id: activityId, type: "activity", live: true, steps: [{ id: "queued", step_type: "QUEUED", reasoning: "Starting…" }] },
    ]);
    setLoading(true);
    setError(null);

    const controller = new AbortController();
    abortRef.current = controller;
    const timeout = setTimeout(() => controller.abort(), CHAT_TIMEOUT_MS);
    const body = {
      message: userText,
      session_id: currentSession,
      provider,
      model_name: modelName,
      secondary_provider: secondaryProvider,
      secondary_model_name: secondaryModelName,
    };
    let liveSteps = [{ id: "queued", step_type: "QUEUED", reasoning: "Starting…" }];

    const patchLive = (steps) => {
      liveSteps = steps;
      setItems((prev) => prev.map((item) => (item.id === activityId ? { ...item, steps } : item)));
    };

    try {
      const response = await fetch("/api/chat/stream", {
        method: "POST",
        headers: { "Content-Type": "application/json", Accept: "text/event-stream" },
        body: JSON.stringify(body),
        signal: controller.signal,
      });
      if (response.status === 404) {
        const data = await api.post("/api/chat", body);
        applyFinished(data, liveSteps, userText);
        return;
      }
      if (!response.ok) {
        let detail = `HTTP Error ${response.status}`;
        try {
          const payload = await response.json();
          if (typeof payload.detail === "string") detail = payload.detail;
        } catch {
          /* use status text */
        }
        throw new Error(detail);
      }

      let finished = null;
      await readSseStream(response, (event) => {
        if (event.type === "step") {
          patchLive([...liveSteps.filter((step) => step.step_type !== "QUEUED"), event]);
        } else if (event.type === "run_finished") {
          finished = event;
        } else if (event.type === "run_error") {
          throw new Error(event.error || "Chat failed.");
        }
      });
      if (finished) {
        applyFinished(finished, liveSteps, userText);
      } else {
        throw new Error("The chat stream ended before a reply arrived.");
      }
    } catch (e) {
      if (e?.name === "AbortError") {
        setItems((prev) => prev.map((item) => (
          item.id === activityId
            ? { ...item, live: false, steps: [...liveSteps, { id: "stopped", step_type: "HITL_BLOCKED", reasoning: "Stopped." }] }
            : item
        )));
        setError("Stopped.");
      } else {
        console.error(e);
        setError(e.message || "Failed to send message.");
        setItems((prev) => prev.map((item) => (item.id === activityId ? { ...item, live: false } : item)));
      }
    } finally {
      clearTimeout(timeout);
      abortRef.current = null;
      sendingRef.current = false;
      setLoading(false);
    }
  };

  const availableProviders = modelCatalog.providers
    ? Object.keys(modelCatalog.providers)
    : ["openai", "anthropic", "gemini", "grok"];

  const currentPrimaryObj = modelCatalog.providers?.[provider] || { name: provider, models: [modelName] };
  const availablePrimaryModels = currentPrimaryObj.models || [modelName];
  const currentSecondaryObj = modelCatalog.providers?.[secondaryProvider] || {
    name: secondaryProvider,
    models: [secondaryModelName],
  };
  const availableSecondaryModels = currentSecondaryObj.models || [secondaryModelName];

  const handleProviderChange = (newProvider) => {
    setProvider(newProvider);
    const provObj = modelCatalog.providers?.[newProvider];
    if (provObj?.models?.length) setModelName(provObj.default || provObj.models[0]);
  };

  const handleSecondaryProviderChange = (newProvider) => {
    setSecondaryProvider(newProvider);
    const provObj = modelCatalog.providers?.[newProvider];
    if (provObj?.models?.length) setSecondaryModelName(provObj.default || provObj.models[0]);
  };

  const handleRenameSession = async () => {
    if (!renameInput.trim()) return;
    try {
      await api.put(`/api/history/${currentSession}`, { new_session_id: renameInput.trim() });
      const newSess = renameInput.trim();
      setCurrentSession(newSess);
      setIsRenaming(false);
      setRenameInput("");
      setToastMessage(`Session successfully renamed to '${newSess}'`);
      setTimeout(() => setToastMessage(""), 3000);
      loadSessions();
      if (onSessionChanged) onSessionChanged(newSess);
    } catch (e) {
      setError(e.message || "Failed to rename session");
    }
  };

  const handleDeleteSession = async () => {
    if (!window.confirm(`Are you sure you want to delete session '${currentSession}'?`)) return;
    try {
      await api.delete(`/api/history/${currentSession}`);
      setToastMessage(`Session '${currentSession}' deleted`);
      setTimeout(() => setToastMessage(""), 3000);
      loadSessions();
      onNewSession();
    } catch (e) {
      setError(e.message || "Failed to delete session");
    }
  };

  // A save result belongs to the chat it was run in.
  useEffect(() => {
    setMemoryNotice(null);
  }, [currentSession]);

  // Merge this chat's long-term memory session into the main graph now, instead of after the idle timeout.
  const handleSaveMemoryNow = async () => {
    const sessionId = currentSession;
    setSavingMemory(true);
    setMemoryNotice({ kind: "info", text: "Saving this chat to long-term memory…" });
    try {
      const queued = await api.post(`/api/memory/sessions/${encodeURIComponent(sessionId)}/merge`, {});
      const deadline = Date.now() + 180000;
      while (Date.now() < deadline) {
        await new Promise((resolve) => setTimeout(resolve, 2000));
        const job = await api.get(`/api/memory/observability/jobs/${encodeURIComponent(queued.job_id)}`);
        if (job.status === "SUCCEEDED") {
          const result = job.result || {};
          setMemoryNotice(
            result.merged
              ? { kind: "ok", text: "Saved. This chat's memories are now in the main graph." }
              : { kind: "info", text: "Nothing new to save. Jev hasn't marked anything in this chat as worth remembering since the last save." }
          );
          return;
        }
        if (job.status === "DEAD_LETTERED" || job.status === "FAILED") {
          setMemoryNotice({ kind: "error", text: `Saving failed: ${job.last_error || job.status}` });
          return;
        }
        if (job.status === "RETRYING") {
          setMemoryNotice({ kind: "info", text: `Saving hit an error and will retry (attempt ${job.attempt_count}/${job.max_attempts})…` });
        }
      }
      setMemoryNotice({ kind: "info", text: "Still saving in the background. Check Memory Ops for progress." });
    } catch (e) {
      setMemoryNotice({ kind: "error", text: `Saving failed: ${e.message}` });
    } finally {
      setSavingMemory(false);
    }
  };

  const threads = Array.from(new Set([currentSession, ...sessions].filter(Boolean)));

  return (
    <div className="page page-fill">
      <PageHeader
        title="Chat"
        subtitle="Primary model runs tools. Secondary handles summaries and memory."
        actions={<button className="btn btn-primary" onClick={onNewSession}>New chat</button>}
      />

      <div className="chat-layout">
        <aside className="glass-card thread-list">
          <div className="card-head"><h3>Threads</h3></div>
          <div className="thread-scroll">
            {threads.length === 0 ? (
              <div className="lede">No prior sessions.</div>
            ) : (
              threads.map((s) => (
                <button
                  key={s}
                  type="button"
                  className={`thread ${s === currentSession ? "active" : ""}`}
                  title={s}
                  onClick={() => {
                    setCurrentSession(s);
                    loadHistory(s);
                    if (onSessionChanged) onSessionChanged(s);
                  }}
                >
                  {s}
                </button>
              ))
            )}
          </div>
        </aside>

        <section className="glass-card chat-pane">
          <div className="chat-toolbar">
            {isRenaming ? (
              <div className="actions">
                <input value={renameInput} onChange={(e) => setRenameInput(e.target.value)} placeholder="New session name" />
                <button className="btn btn-primary btn-sm" onClick={handleRenameSession}>Save</button>
                <button className="btn btn-ghost btn-sm" onClick={() => setIsRenaming(false)}>Cancel</button>
              </div>
            ) : (
              <div className="actions">
                <strong>Session: {currentSession}</strong>
                <button className="btn btn-ghost btn-sm" onClick={() => { setIsRenaming(true); setRenameInput(currentSession); }}>Rename</button>
                <button className="btn btn-danger btn-sm" onClick={handleDeleteSession}>Delete</button>
                <button
                  className="btn btn-primary btn-sm"
                  onClick={handleSaveMemoryNow}
                  disabled={savingMemory}
                  title="Merge this chat into long-term memory now instead of waiting for it to go idle"
                >
                  {savingMemory ? "Saving…" : "Save to memory now"}
                </button>
              </div>
            )}

            <div className="actions">
              <label className="field">
                Primary
                <div className="model-selects">
                  <select value={provider} onChange={(e) => handleProviderChange(e.target.value)}>
                    {availableProviders.map((pKey) => (
                      <option key={pKey} value={pKey}>{modelCatalog.providers?.[pKey]?.name || pKey.toUpperCase()}</option>
                    ))}
                  </select>
                  <select value={modelName} onChange={(e) => setModelName(e.target.value)}>
                    {availablePrimaryModels.map((m) => <option key={m} value={m}>{m}</option>)}
                  </select>
                </div>
              </label>
              <label className="field">
                Secondary
                <div className="model-selects">
                  <select value={secondaryProvider} onChange={(e) => handleSecondaryProviderChange(e.target.value)}>
                    {availableProviders.map((pKey) => (
                      <option key={pKey} value={pKey}>{modelCatalog.providers?.[pKey]?.name || pKey.toUpperCase()}</option>
                    ))}
                  </select>
                  <select value={secondaryModelName} onChange={(e) => setSecondaryModelName(e.target.value)}>
                    {availableSecondaryModels.map((m) => <option key={m} value={m}>{m}</option>)}
                  </select>
                </div>
              </label>
            </div>
          </div>

          {toastMessage ? <Notice kind="ok">{toastMessage}</Notice> : null}
          {memoryNotice ? <Notice kind={memoryNotice.kind}>{memoryNotice.text}</Notice> : null}
          {error ? <Notice kind="error">{error}</Notice> : null}

          <div className="messages" ref={scrollerRef}>
            {historyLoading ? (
              <Spinner label="Loading history..." />
            ) : items.length === 0 ? (
              <div className="empty">
                <h3>No messages yet</h3>
                <div>Write something to start this thread.</div>
              </div>
            ) : (
              items.map((item) => {
                if (item.type === "activity") {
                  return <ActivityCard key={item.id} steps={item.steps} live={item.live} defaultOpen={item.live || item.defaultOpen} />;
                }
                if (item.type === "approval") {
                  return (
                    <div key={item.id} className="msg approval">
                      <div className="msg-meta">Approval</div>
                      <div className="actions" style={{ marginBottom: 8 }}>
                        <strong>Waiting for approval</strong>
                        <Badge value={item.approvalStatus || "PENDING"} />
                      </div>
                      <div>{item.text}</div>
                      {item.pendingApprovalId ? (
                        <div className="actions" style={{ marginTop: 10 }}>
                          {item.approvalStatus === "PENDING" || item.approvalStatus === "APPROVAL_REQUIRED" ? (
                            <>
                              <button
                                className="btn btn-ok"
                                disabled={loading}
                                onClick={() => handleApprovalDecision(item.pendingApprovalId, "APPROVED")}
                              >
                                Approve & send
                              </button>
                              <button
                                className="btn btn-danger"
                                disabled={loading}
                                onClick={() => handleApprovalDecision(item.pendingApprovalId, "REJECTED")}
                              >
                                Reject
                              </button>
                            </>
                          ) : null}
                          <button className="btn btn-sm" onClick={onOpenApprovals}>Open Approvals</button>
                        </div>
                      ) : null}
                    </div>
                  );
                }
                const cls = item.type === "user" ? "user" : "assistant";
                const role = cls === "user" ? "You" : "Ivo";
                return (
                  <div key={item.id} className={`msg ${cls}`}>
                    <div className="msg-meta">{role}</div>
                    {item.text}
                    {item.type === "assistant" && item.retrievalTriggered ? (
                      <div className="lede" style={{ marginTop: 8 }}>
                        Memory retrieved ({item.retrievedMemoriesCount || 0} facts)
                      </div>
                    ) : null}
                  </div>
                );
              })
            )}
          </div>

          <div className="composer">
            <textarea
              value={inputMessage}
              onChange={(e) => setInputMessage(e.target.value)}
              onKeyDown={(e) => {
                if (e.key === "Enter" && !e.shiftKey) {
                  e.preventDefault();
                  handleSendMessage();
                }
              }}
              placeholder="Write a message"
              rows={2}
              disabled={loading}
            />
            {loading ? (
              <button className="btn btn-ghost" onClick={stopRun}>Stop</button>
            ) : (
              <button className="btn btn-primary" onClick={handleSendMessage} disabled={!inputMessage.trim()}>
                Send
              </button>
            )}
          </div>
        </section>
      </div>
    </div>
  );
}

if (typeof window !== "undefined") {
  window.ChatCockpit = ChatCockpit;
}
