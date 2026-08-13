import React, { useEffect, useRef, useState } from "react";
import { api } from "../api/client.js";
import PageHeader from "./ui/PageHeader.jsx";
import Notice from "./ui/Notice.jsx";
import Spinner from "./ui/Spinner.jsx";
import Badge from "./ui/Badge.jsx";

export default function ChatCockpit({ activeSessionId, onNewSession, onSessionChanged, onOpenApprovals }) {
  const [messages, setMessages] = useState([]);
  const [inputMessage, setInputMessage] = useState("");
  const [sessions, setSessions] = useState([]);
  const [currentSession, setCurrentSession] = useState(activeSessionId || "default_session");
  const [provider, setProvider] = useState("openai");
  const [modelName, setModelName] = useState("gpt-4o-mini");
  const [secondaryProvider, setSecondaryProvider] = useState("openai");
  const [secondaryModelName, setSecondaryModelName] = useState("gpt-4o-mini");
  const [modelCatalog, setModelCatalog] = useState({});
  const [loading, setLoading] = useState(false);
  const [historyLoading, setHistoryLoading] = useState(false);
  const [error, setError] = useState(null);
  const [isRenaming, setIsRenaming] = useState(false);
  const [renameInput, setRenameInput] = useState("");
  const [toastMessage, setToastMessage] = useState("");
  const scrollerRef = useRef(null);
  const historyReq = useRef(0);

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
      setModelCatalog(data.catalog || {});
    } catch (e) {
      console.error("Failed to load models:", e);
    }
  };

  const loadHistory = async (sessId) => {
    const req = ++historyReq.current;
    setHistoryLoading(true);
    setError(null);
    setMessages([]);
    try {
      const data = await api.get(`/api/history/${sessId}`);
      if (req !== historyReq.current) return;
      const loaded = (data.turns || []).map((t) => ({
        id: t.id,
        sender: t.sender,
        text: t.content,
        created_at: t.created_at,
      }));
      setMessages(loaded);
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
    if (activeSessionId) {
      setCurrentSession(activeSessionId);
      loadHistory(activeSessionId);
    }
  }, [activeSessionId]);

  useEffect(() => {
    if (scrollerRef.current) {
      scrollerRef.current.scrollTop = scrollerRef.current.scrollHeight;
    }
  }, [messages, loading]);

  const handleSendMessage = async () => {
    if (!inputMessage.trim() || loading) return;
    const userText = inputMessage;
    setInputMessage("");
    setMessages((prev) => [...prev, { sender: "user", text: userText }]);
    setLoading(true);
    setError(null);

    try {
      const data = await api.post("/api/chat", {
        message: userText,
        session_id: currentSession,
        provider,
        model_name: modelName,
        secondary_provider: secondaryProvider,
        secondary_model_name: secondaryModelName,
      });

      const inlineToolEvents = (data.loop_trace || []).filter(
        (e) => e.step_type === "TOOL_REQUESTED" || e.step_type === "TOOL_EXECUTED"
      );

      const newMessages = inlineToolEvents.map((e) => {
        const isFailed =
          e.tool_result &&
          (e.tool_result.includes("FAILED") ||
            e.tool_result.includes("Error") ||
            e.tool_result.includes("blocked") ||
            e.tool_result.includes("failed"));
        let toolText = `Tool requested: ${e.tool_name}`;
        if (e.step_type === "TOOL_EXECUTED") {
          toolText = isFailed
            ? `Tool execution failed (${e.tool_name}): ${String(e.tool_result).slice(0, 140)}`
            : `Tool executed: ${e.tool_name}`;
        }
        return { sender: "system_tool", text: toolText, isFailed };
      });

      if (data.response) {
        newMessages.push({
          sender: "assistant",
          text: data.response,
          retrievalTriggered: data.retrieval_triggered,
          retrievedMemoriesCount: (data.retrieved_memories || []).length,
          retrievedMemories: data.retrieved_memories || [],
          toolsUsed: data.tools_used || [],
        });
        if (String(data.response).includes("Primary LLM (Offline)")) {
          setError("The model did not run. The API is up, but no LLM client was created. Check the provider API key in .env and restart the backend.");
        }
      }

      if (
        data.pending_approval_id ||
        data.approval_status === "PENDING" ||
        data.approval_status === "APPROVAL_REQUIRED"
      ) {
        newMessages.push({
          sender: "system_approval_pending",
          text: "This action is waiting for approval.",
          pendingApprovalId: data.pending_approval_id,
          approvalStatus: data.approval_status || "PENDING",
        });
      }

      setMessages((prev) => [...prev, ...newMessages]);

      if (data.session_id && data.session_id !== currentSession) {
        setCurrentSession(data.session_id);
        if (onSessionChanged) onSessionChanged(data.session_id);
      }
      loadSessions();
    } catch (e) {
      console.error(e);
      setError(e.message || "Failed to send message.");
    } finally {
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
          {threads.length === 0 ? (
            <div className="lede">No prior sessions.</div>
          ) : (
            threads.map((s) => (
              <button
                key={s}
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
          {error ? <Notice kind="error">{error}</Notice> : null}

          <div className="messages" ref={scrollerRef}>
            {historyLoading ? (
              <Spinner label="Loading history..." />
            ) : messages.length === 0 ? (
              <div className="empty">
                <h3>No messages yet</h3>
                <div>Write something to start this thread.</div>
              </div>
            ) : (
              messages.map((m, idx) => {
                if (m.sender === "system_approval_pending") {
                  return (
                    <div key={idx} className="msg approval">
                      <div className="msg-meta">Approval</div>
                      <div className="actions" style={{ marginBottom: 8 }}>
                        <strong>Waiting for approval</strong>
                        <Badge value={m.approvalStatus || "PENDING"} />
                      </div>
                      <div>{m.text}</div>
                      {m.pendingApprovalId ? (
                        <div className="lede" style={{ marginTop: 8 }}>
                          Request ID: <code>{m.pendingApprovalId}</code>
                          {" · "}
                          <button className="btn btn-sm" onClick={onOpenApprovals}>Open Approvals</button>
                        </div>
                      ) : null}
                    </div>
                  );
                }
                const cls = m.sender === "user" ? "user" : m.sender === "system_tool" ? "tool" : "assistant";
                const role = cls === "user" ? "You" : cls === "tool" ? "Tool" : "Astra";
                return (
                  <div key={idx} className={`msg ${cls}`}>
                    <div className="msg-meta">{role}</div>
                    {m.text}
                    {m.sender === "assistant" && m.retrievalTriggered ? (
                      <div className="lede" style={{ marginTop: 8 }}>
                        Memory retrieved ({m.retrievedMemoriesCount || 0} facts)
                      </div>
                    ) : null}
                  </div>
                );
              })
            )}
            {loading ? <div className="msg assistant"><div className="msg-meta">Astra</div>Working…</div> : null}
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
            />
            <button className="btn btn-primary" onClick={handleSendMessage} disabled={loading || !inputMessage.trim()}>
              Send
            </button>
          </div>
        </section>
      </div>
    </div>
  );
}

if (typeof window !== "undefined") {
  window.ChatCockpit = ChatCockpit;
}
