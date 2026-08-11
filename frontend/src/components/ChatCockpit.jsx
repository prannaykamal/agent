import React, { useState, useEffect } from 'react';
import { api } from '../api/client.js';

export default function ChatCockpit({ activeSessionId, onNewSession, onSessionChanged }) {
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
    setHistoryLoading(true);
    setError(null);
    try {
      const data = await api.get(`/api/history/${sessId}`);
      const loaded = (data.turns || []).map(t => ({
        id: t.id,
        sender: t.sender,
        text: t.content,
        created_at: t.created_at
      }));
      setMessages(loaded);
    } catch (e) {
      console.error(e);
      setError(e.message || "Failed to load conversation history.");
    } finally {
      setHistoryLoading(false);
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

  const handleSendMessage = async () => {
    if (!inputMessage.trim() || loading) return;

    const userText = inputMessage;
    setInputMessage("");
    setMessages(prev => [...prev, { sender: "user", text: userText }]);
    setLoading(true);
    setError(null);

    try {
      const data = await api.post("/api/chat", {
        message: userText,
        session_id: currentSession,
        provider: provider,
        model_name: modelName,
        secondary_provider: secondaryProvider,
        secondary_model_name: secondaryModelName
      });

      const inlineToolEvents = (data.loop_trace || []).filter(e => e.step_type === "TOOL_REQUESTED" || e.step_type === "TOOL_EXECUTED");

      const newMessages = [
        ...inlineToolEvents.map(e => {
          const isFailed = e.tool_result && (e.tool_result.includes("FAILED") || e.tool_result.includes("Error") || e.tool_result.includes("blocked") || e.tool_result.includes("failed"));
          let toolText = `⚙️ Tool Requested: ${e.tool_name}`;
          if (e.step_type === "TOOL_EXECUTED") {
            toolText = isFailed ? `⚠️ Tool Execution Failed (${e.tool_name}): ${e.tool_result.slice(0, 100)}` : `✓ Tool Executed: ${e.tool_name}`;
          }
          return {
            sender: "system_tool",
            text: toolText,
            isFailed: isFailed
          };
        })
      ];

      if (data.response) {
        newMessages.push({
          sender: "assistant",
          text: data.response,
          retrievalTriggered: data.retrieval_triggered,
          retrievedMemoriesCount: (data.retrieved_memories || []).length
        });
      }

      if (data.pending_approval_id || data.approval_status === "PENDING" || data.approval_status === "APPROVAL_REQUIRED") {
        newMessages.push({
          sender: "system_approval_pending",
          text: `🛡️ HITL Approval Pending: Execution paused waiting for human decision.`,
          pendingApprovalId: data.pending_approval_id,
          approvalStatus: data.approval_status || "PENDING"
        });
      }

      setMessages(prev => [...prev, ...newMessages]);

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

  const currentPrimaryObj = modelCatalog.providers?.[provider] || {
    name: provider,
    models: [modelName]
  };
  const availablePrimaryModels = currentPrimaryObj.models || [modelName];

  const currentSecondaryObj = modelCatalog.providers?.[secondaryProvider] || {
    name: secondaryProvider,
    models: [secondaryModelName]
  };
  const availableSecondaryModels = currentSecondaryObj.models || [secondaryModelName];

  const handleProviderChange = (newProvider) => {
    setProvider(newProvider);
    const provObj = modelCatalog.providers?.[newProvider];
    if (provObj && provObj.models && provObj.models.length > 0) {
      const defaultMod = provObj.default || provObj.models[0];
      setModelName(defaultMod);
    }
  };

  const handleSecondaryProviderChange = (newProvider) => {
    setSecondaryProvider(newProvider);
    const provObj = modelCatalog.providers?.[newProvider];
    if (provObj && provObj.models && provObj.models.length > 0) {
      const defaultMod = provObj.default || provObj.models[0];
      setSecondaryModelName(defaultMod);
    }
  };

  const handleRenameSession = async () => {
    if (!renameInput.trim()) return;
    try {
      const res = await fetch(`/api/history/${currentSession}`, {
        method: "PUT",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ new_session_id: renameInput.trim() })
      });
      if (res.ok) {
        const newSess = renameInput.trim();
        setCurrentSession(newSess);
        setIsRenaming(false);
        setRenameInput("");
        setToastMessage(`Session successfully renamed to '${newSess}'`);
        setTimeout(() => setToastMessage(""), 3000);
        loadSessions();
        if (onSessionChanged) onSessionChanged(newSess);
      }
    } catch (e) {
      console.error(e);
      setError("Failed to rename session");
    }
  };

  const handleDeleteSession = async () => {
    if (!window.confirm(`Are you sure you want to delete session '${currentSession}'?`)) return;
    try {
      const res = await fetch(`/api/history/${currentSession}`, { method: "DELETE" });
      if (res.ok) {
        setToastMessage(`Session '${currentSession}' deleted`);
        setTimeout(() => setToastMessage(""), 3000);
        loadSessions();
        onNewSession();
      }
    } catch (e) {
      console.error(e);
      setError("Failed to delete session");
    }
  };

  return (
    <div style={{ display: "grid", gridTemplateColumns: "260px 1fr", gap: "20px", height: "calc(100vh - 160px)" }}>
      {/* Session History Sidebar */}
      <div className="glass-card" style={{ display: "flex", flexDirection: "column", gap: "12px", padding: "16px" }}>
        <button
          onClick={onNewSession}
          style={{ padding: "10px", background: "var(--primary-glow)", border: "none", borderRadius: "8px", color: "white", fontWeight: "600", cursor: "pointer" }}
        >
          + New Chat
        </button>

        <h4 style={{ fontFamily: "var(--font-heading)", margin: "8px 0 0 0", color: "var(--text-secondary)" }}>Chat Threads</h4>
        <div style={{ display: "flex", flexDirection: "column", gap: "6px", overflowY: "auto", flex: 1 }}>
          {sessions.length === 0 ? (
            <div style={{ fontSize: "12px", color: "var(--text-secondary)", fontStyle: "italic" }}>No prior sessions.</div>
          ) : (
            sessions.map(s => (
              <div
                key={s}
                onClick={() => { setCurrentSession(s); loadHistory(s); if (onSessionChanged) onSessionChanged(s); }}
                style={{
                  padding: "8px 12px",
                  borderRadius: "6px",
                  cursor: "pointer",
                  fontSize: "13px",
                  background: s === currentSession ? "rgba(255,255,255,0.08)" : "transparent",
                  border: s === currentSession ? "1px solid var(--border-glass)" : "1px solid transparent"
                }}
              >
                💬 {s}
              </div>
            ))
          )}
        </div>
      </div>

      {/* Main Chat Conversation Area */}
      <div className="glass-card" style={{ display: "flex", flexDirection: "column", height: "100%", padding: "16px" }}>
        {/* Top Controls Header with Dual LLM Selection */}
        <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center", borderBottom: "1px solid var(--border-glass)", paddingBottom: "12px", marginBottom: "12px", flexWrap: "wrap", gap: "12px" }}>
          <div>
            {isRenaming ? (
              <div style={{ display: "flex", gap: "8px" }}>
                <input
                  type="text"
                  value={renameInput}
                  onChange={e => setRenameInput(e.target.value)}
                  placeholder="New session name"
                  style={{ padding: "4px 8px", background: "rgba(0,0,0,0.2)", border: "1px solid var(--border-glass)", borderRadius: "4px", color: "white" }}
                />
                <button onClick={handleRenameSession} style={{ padding: "4px 8px", background: "var(--primary-glow)", border: "none", borderRadius: "4px", color: "white", cursor: "pointer" }}>Save</button>
                <button onClick={() => setIsRenaming(false)} style={{ padding: "4px 8px", background: "#666", border: "none", borderRadius: "4px", color: "white", cursor: "pointer" }}>Cancel</button>
              </div>
            ) : (
              <div style={{ display: "flex", alignItems: "center", gap: "10px" }}>
                <strong style={{ fontFamily: "var(--font-heading)", fontSize: "16px" }}>Session: {currentSession}</strong>
                <button onClick={() => { setIsRenaming(true); setRenameInput(currentSession); }} style={{ background: "none", border: "none", cursor: "pointer", fontSize: "14px" }} title="Rename Session">✏️</button>
                <button onClick={handleDeleteSession} style={{ background: "none", border: "none", cursor: "pointer", fontSize: "14px" }} title="Delete Session">🗑️</button>
              </div>
            )}
          </div>

          <div style={{ display: "flex", gap: "16px", alignItems: "center", flexWrap: "wrap" }}>
            {/* Primary LLM Selection */}
            <div style={{ display: "flex", alignItems: "center", gap: "6px", background: "rgba(255,255,255,0.05)", padding: "6px 10px", borderRadius: "8px", border: "1px solid var(--border-glass)" }}>
              <span style={{ fontSize: "12px", color: "var(--text-secondary)", fontWeight: "600" }}>🧠 Primary:</span>
              <select
                value={provider}
                onChange={e => handleProviderChange(e.target.value)}
                style={{ padding: "4px 8px", background: "rgba(0,0,0,0.4)", border: "1px solid var(--border-glass)", borderRadius: "4px", color: "white", fontSize: "12px" }}
              >
                {availableProviders.map(pKey => {
                  const pObj = modelCatalog.providers?.[pKey];
                  const label = pObj?.name || pKey.toUpperCase();
                  return <option key={pKey} value={pKey}>{label}</option>;
                })}
              </select>
              <select
                value={modelName}
                onChange={e => setModelName(e.target.value)}
                style={{ padding: "4px 8px", background: "rgba(0,0,0,0.4)", border: "1px solid var(--border-glass)", borderRadius: "4px", color: "white", fontSize: "12px" }}
              >
                {availablePrimaryModels.map(m => (
                  <option key={m} value={m}>{m}</option>
                ))}
              </select>
            </div>

            {/* Secondary LLM Selection */}
            <div style={{ display: "flex", alignItems: "center", gap: "6px", background: "rgba(255,255,255,0.05)", padding: "6px 10px", borderRadius: "8px", border: "1px solid var(--border-glass)" }}>
              <span style={{ fontSize: "12px", color: "var(--text-secondary)", fontWeight: "600" }}>⚡ Secondary:</span>
              <select
                value={secondaryProvider}
                onChange={e => handleSecondaryProviderChange(e.target.value)}
                style={{ padding: "4px 8px", background: "rgba(0,0,0,0.4)", border: "1px solid var(--border-glass)", borderRadius: "4px", color: "white", fontSize: "12px" }}
              >
                {availableProviders.map(pKey => {
                  const pObj = modelCatalog.providers?.[pKey];
                  const label = pObj?.name || pKey.toUpperCase();
                  return <option key={pKey} value={pKey}>{label}</option>;
                })}
              </select>
              <select
                value={secondaryModelName}
                onChange={e => setSecondaryModelName(e.target.value)}
                style={{ padding: "4px 8px", background: "rgba(0,0,0,0.4)", border: "1px solid var(--border-glass)", borderRadius: "4px", color: "white", fontSize: "12px" }}
              >
                {availableSecondaryModels.map(m => (
                  <option key={m} value={m}>{m}</option>
                ))}
              </select>
            </div>
          </div>
        </div>


        {toastMessage && (


          <div style={{ padding: "8px 14px", background: "rgba(46, 204, 113, 0.2)", border: "1px solid rgba(46, 204, 113, 0.4)", borderRadius: "6px", color: "#2ecc71", fontSize: "13px" }}>
            ✓ {toastMessage}
          </div>
        )}


        {error && (
          <div style={{ padding: "10px", background: "rgba(255,50,50,0.15)", borderRadius: "6px", color: "#ff6b6b", marginBottom: "12px", fontSize: "13px" }}>
            ⚠️ {error}
          </div>
        )}

        {/* Message Stream */}
        <div style={{ flex: 1, overflowY: "auto", display: "flex", flexDirection: "column", gap: "12px", paddingRight: "8px" }}>
          {historyLoading ? (
            <div style={{ textAlign: "center", padding: "32px", color: "var(--text-secondary)" }}>🌀 Loading history...</div>
          ) : messages.length === 0 ? (
            <div style={{ textAlign: "center", padding: "48px", color: "var(--text-secondary)", fontStyle: "italic" }}>
              💬 Send a message to begin conversation with 24x7 Personal AI Assistant.
            </div>
          ) : (
            messages.map((m, idx) => {
              if (m.sender === "system_approval_pending") {
                return (
                  <div
                    key={idx}
                    style={{
                      alignSelf: "center",
                      width: "90%",
                      padding: "14px 18px",
                      borderRadius: "12px",
                      background: "rgba(243, 156, 18, 0.12)",
                      border: "1px solid rgba(243, 156, 18, 0.4)",
                      color: "#f39c12",
                      fontSize: "14px",
                      display: "flex",
                      flexDirection: "column",
                      gap: "8px",
                      boxShadow: "0 4px 12px rgba(243, 156, 18, 0.1)"
                    }}
                  >
                    <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center" }}>
                      <strong style={{ display: "flex", alignItems: "center", gap: "6px" }}>
                        🛡️ Human Approval Pending
                      </strong>
                      <span style={{ fontSize: "11px", background: "rgba(243, 156, 18, 0.25)", padding: "2px 8px", borderRadius: "4px", fontWeight: "600" }}>
                        STATUS: {m.approvalStatus || "PENDING"}
                      </span>
                    </div>
                    <div>{m.text}</div>
                    {m.pendingApprovalId && (
                      <div style={{ fontSize: "12px", color: "var(--text-secondary)", display: "flex", gap: "8px", alignItems: "center" }}>
                        <span>Request ID: <code>{m.pendingApprovalId}</code></span>
                        <span>• Go to <strong>🛡️ Approvals</strong> tab to decide.</span>
                      </div>
                    )}
                  </div>
                );
              }

              return (
                <div
                  key={idx}
                  style={{
                    alignSelf: m.sender === "user" ? "flex-end" : m.sender === "system_tool" ? "center" : "flex-start",
                    maxWidth: m.sender === "system_tool" ? "90%" : "75%",
                    padding: m.sender === "system_tool" ? "4px 12px" : "12px 16px",
                    borderRadius: "12px",
                    fontSize: m.sender === "system_tool" ? "12px" : "14px",
                    background: m.sender === "user" ? "var(--primary-glow)" : m.sender === "system_tool" ? "rgba(255,255,255,0.04)" : "rgba(255,255,255,0.06)",
                    border: m.sender === "system_tool" ? "1px dashed var(--border-glass)" : "1px solid var(--border-glass)",
                    color: m.sender === "system_tool" ? "var(--text-secondary)" : "var(--text-primary)"
                  }}
                >
                  {m.text}
                  {m.sender === "assistant" && m.retrievalTriggered && (
                    <div style={{ marginTop: "6px", fontSize: "11px", color: "#4ecdc4", display: "flex", alignItems: "center", gap: "4px" }}>
                      <span>🧠 Memory Retrieved ({m.retrievedMemoriesCount || 0} facts)</span>
                    </div>
                  )}
                </div>
              );
            })
          )}

          {loading && (
            <div style={{ alignSelf: "flex-start", padding: "12px 16px", borderRadius: "12px", background: "rgba(255,255,255,0.04)", fontSize: "14px", color: "var(--text-secondary)" }}>
              ⚡ Thinking & running tools...
            </div>
          )}
        </div>

        {/* Message Input Box */}
        <div style={{ display: "flex", gap: "12px", marginTop: "16px" }}>
          <input
            type="text"
            value={inputMessage}
            onChange={e => setInputMessage(e.target.value)}
            onKeyDown={e => e.key === "Enter" && handleSendMessage()}
            placeholder="Type your message or command..."
            style={{ flex: 1, padding: "12px 16px", background: "rgba(0,0,0,0.3)", border: "1px solid var(--border-glass)", borderRadius: "8px", color: "white", outline: "none" }}
          />
          <button
            onClick={handleSendMessage}
            disabled={loading}
            style={{ padding: "12px 24px", background: "var(--primary-glow)", border: "none", borderRadius: "8px", color: "white", fontWeight: "600", cursor: "pointer", opacity: loading ? 0.6 : 1 }}
          >
            Send
          </button>
        </div>
      </div>
    </div>
  );
}

if (typeof window !== "undefined") {
  window.ChatCockpit = ChatCockpit;
}
