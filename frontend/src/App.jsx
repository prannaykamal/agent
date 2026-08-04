import React, { useState } from 'react';
import OverviewCockpit from './components/OverviewCockpit.jsx';
import ChatCockpit from './components/ChatCockpit.jsx';
import LoopCockpit from './components/LoopCockpit.jsx';
import MemoryCockpit from './components/MemoryCockpit.jsx';
import MemoryObservabilityCockpit from './components/MemoryObservabilityCockpit.jsx';
import ApprovalInbox from './components/ApprovalInbox.jsx';
import ToolsCockpit from './components/ToolsCockpit.jsx';
import ScheduledCockpit from './components/ScheduledCockpit.jsx';
import DataCockpit from './components/DataCockpit.jsx';
import TaskBoard from './components/TaskBoard.jsx';

export default function App() {
  const [activeTab, setActiveTab] = useState("overview");
  const [currentSessionId, setCurrentSessionId] = useState("sess_" + Math.random().toString(36).substring(2, 9));

  const handleNewSession = () => {
    const newId = "sess_" + Math.random().toString(36).substring(2, 9);
    setCurrentSessionId(newId);
  };

  return (
    <div style={{ display: "flex", minHeight: "100vh", background: "var(--bg-dark)", color: "var(--text-primary)" }}>
      {/* Sidebar Navigation */}
      <div style={{ width: "240px", background: "rgba(255,255,255,0.02)", borderRight: "1px solid var(--border-glass)", padding: "20px 16px", display: "flex", flexDirection: "column", gap: "16px" }}>
        <div style={{ display: "flex", alignItems: "center", gap: "10px", paddingBottom: "16px", borderBottom: "1px solid var(--border-glass)" }}>
          <div style={{ width: "32px", height: "32px", borderRadius: "8px", background: "var(--primary-glow)", display: "flex", alignItems: "center", justifyContent: "center", fontWeight: "700" }}>🚀</div>
          <div>
            <strong style={{ fontFamily: "var(--font-heading)", fontSize: "16px", display: "block" }}>ASTRA</strong>
            <span style={{ fontSize: "10px", color: "var(--text-secondary)" }}>Autonomous AI Cockpit</span>
          </div>
        </div>


        <nav style={{ display: "flex", flexDirection: "column", gap: "8px" }}>
          {[
            { id: "overview", label: "📊 Overview", component: OverviewCockpit },
            { id: "chat", label: "💬 Chat", component: ChatCockpit },
            { id: "loop", label: "🔁 Loop Timeline", component: LoopCockpit },
            { id: "tasks", label: "📋 Task & Sub-Agents", component: TaskBoard },
            { id: "memory", label: "🧠 Memory", component: MemoryCockpit },
            { id: "memory_ops", label: "Memory Ops", component: MemoryObservabilityCockpit },
            { id: "approvals", label: "🛡️ Approvals", component: ApprovalInbox },
            { id: "tools", label: "🧰 Tools Catalog", component: ToolsCockpit },
            { id: "scheduled", label: "⏱️ Scheduled Jobs", component: ScheduledCockpit },
            { id: "data", label: "🗄️ Data Inspector", component: DataCockpit }
          ].map(tab => (
            <button
              key={tab.id}
              onClick={() => setActiveTab(tab.id)}
              style={{
                display: "flex",
                alignItems: "center",
                padding: "10px 14px",
                borderRadius: "8px",
                border: "none",
                background: activeTab === tab.id ? "var(--primary-glow)" : "transparent",
                color: activeTab === tab.id ? "white" : "var(--text-secondary)",
                fontFamily: "var(--font-body)",
                fontSize: "14px",
                fontWeight: activeTab === tab.id ? "600" : "400",
                cursor: "pointer",
                textAlign: "left"
              }}
            >
              {tab.label}
            </button>
          ))}
        </nav>
      </div>

      {/* Main Content Area */}
      <div style={{ flex: 1, padding: "24px", overflowY: "auto" }}>
        {activeTab === "overview" && <OverviewCockpit activeSessionId={currentSessionId} />}
        {activeTab === "chat" && <ChatCockpit activeSessionId={currentSessionId} onNewSession={handleNewSession} onSessionChanged={setCurrentSessionId} />}
        {activeTab === "loop" && <LoopCockpit activeSessionId={currentSessionId} />}
        {activeTab === "tasks" && <TaskBoard />}
        {activeTab === "memory" && <MemoryCockpit />}
        {activeTab === "memory_ops" && <MemoryObservabilityCockpit />}
        {activeTab === "approvals" && <ApprovalInbox />}
        {activeTab === "tools" && <ToolsCockpit />}
        {activeTab === "scheduled" && <ScheduledCockpit />}
        {activeTab === "data" && <DataCockpit />}
      </div>
    </div>
  );
}

if (typeof window !== "undefined") {
  window.App = App;
}
