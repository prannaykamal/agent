import React, { useEffect, useState } from "react";
import OverviewCockpit from "./components/OverviewCockpit.jsx";
import ChatCockpit from "./components/ChatCockpit.jsx";
import LoopCockpit from "./components/LoopCockpit.jsx";
import MemoryCockpit from "./components/MemoryCockpit.jsx";
import MemoryObservabilityCockpit from "./components/MemoryObservabilityCockpit.jsx";
import ApprovalInbox from "./components/ApprovalInbox.jsx";
import ToolsCockpit from "./components/ToolsCockpit.jsx";
import ToolsOpsCockpit from "./components/ToolsOpsCockpit.jsx";
import ScheduledCockpit from "./components/ScheduledCockpit.jsx";
import DataCockpit from "./components/DataCockpit.jsx";
import TaskBoard from "./components/TaskBoard.jsx";
import WorkspaceCockpit from "./components/WorkspaceCockpit.jsx";
import Icon from "./components/ui/Icon.jsx";
import ErrorBoundary from "./components/ui/ErrorBoundary.jsx";
import ThemeToggle from "./components/ui/ThemeToggle.jsx";
import { api } from "./api/client.js";

const NAV_GROUPS = [
  {
    label: "Operate",
    items: [
      { id: "overview", label: "Overview", icon: "overview", component: OverviewCockpit },
      { id: "chat", label: "Chat", icon: "chat", component: ChatCockpit },
      { id: "loop", label: "Loop", icon: "loop", component: LoopCockpit },
      { id: "approvals", label: "Approvals", icon: "approvals", component: ApprovalInbox },
    ],
  },
  {
    label: "Work",
    items: [
      { id: "tasks", label: "Tasks", icon: "tasks", component: TaskBoard },
      { id: "memory", label: "Memory", icon: "memory", component: MemoryCockpit },
      { id: "memory_ops", label: "Memory Ops", icon: "ops", component: MemoryObservabilityCockpit },
    ],
  },
  {
    label: "Tools",
    items: [
      { id: "tools", label: "Catalog", icon: "tools", component: ToolsCockpit },
      { id: "tools_ops", label: "Tools Ops", icon: "ops", component: ToolsOpsCockpit },
      { id: "scheduled", label: "Scheduled", icon: "scheduled", component: ScheduledCockpit },
    ],
  },
  {
    label: "Connect",
    items: [
      { id: "workspace", label: "Workspace", icon: "workspace", component: WorkspaceCockpit },
    ],
  },
  {
    label: "Inspect",
    items: [
      { id: "data", label: "Data", icon: "data", component: DataCockpit },
    ],
  },
];

function createSessionId() {
  return "sess_new_" + Math.random().toString(36).substring(2, 9);
}

function healthToneFor(label) {
  const s = String(label || "").toLowerCase();
  if (["online", "ok", "healthy", "alive", "running"].some((k) => s.includes(k))) return "ok";
  if (["offline", "fail", "error"].some((k) => s.includes(k))) return "danger";
  return "warn";
}

export default function App() {
  const [activeTab, setActiveTab] = useState("overview");
  const [currentSessionId, setCurrentSessionId] = useState(createSessionId());
  const [health, setHealth] = useState(null);
  const [pendingApprovals, setPendingApprovals] = useState(0);

  const handleNewSession = () => {
    const newId = createSessionId();
    setCurrentSessionId(newId);
    setActiveTab("chat");
  };

  useEffect(() => {
    let cancelled = false;
    const tick = async () => {
      const [healthData, approvalData] = await Promise.allSettled([
        api.get("/api/health"),
        api.get("/api/approvals"),
      ]);
      if (cancelled) return;
      if (healthData.status === "fulfilled") {
        setHealth(healthData.value);
      } else {
        setHealth({ status: "offline" });
      }
      if (approvalData.status === "fulfilled") {
        setPendingApprovals((approvalData.value.approval_requests || []).length);
      }
    };
    tick();
    const timer = setInterval(tick, 15000);
    return () => {
      cancelled = true;
      clearInterval(timer);
    };
  }, []);

  const healthLabel = health?.status || "connecting";
  const llmAvailable = health?.llm_available !== false;
  const healthTone = !llmAvailable && healthToneFor(healthLabel) === "ok" ? "warn" : healthToneFor(healthLabel);
  const healthText = !llmAvailable && health?.status ? "model offline" : String(healthLabel);
  const navItems = NAV_GROUPS.flatMap((group) => group.items);

  return (
    <div className="app-shell app-container">
      <aside className="sidebar">
        <div className="brand">
          <span className="brand-mark" aria-hidden="true">
            <Icon name="spark" />
          </span>
          <strong className="brand-title">Ivo</strong>
          <span className="brand-sub">local</span>
        </div>

        <div className="nav-scroll">
          {NAV_GROUPS.map((group) => (
            <div key={group.label}>
              <div className="nav-group-label">{group.label}</div>
              <nav className="nav-list">
                {group.items.map((tab) => (
                  <button
                    key={tab.id}
                    className={`nav-item ${activeTab === tab.id ? "active" : ""}`}
                    onClick={() => setActiveTab(tab.id)}
                  >
                    <Icon name={tab.icon} />
                    <span>{tab.label}</span>
                    {tab.id === "approvals" && pendingApprovals > 0 ? (
                      <span className="nav-badge">{pendingApprovals}</span>
                    ) : null}
                  </button>
                ))}
              </nav>
            </div>
          ))}
        </div>

        <div className="sidebar-foot">
          <div className="session-chip">
            <span>Session</span>
            <code title={currentSessionId}>{currentSessionId}</code>
          </div>
          <button className="btn btn-ghost btn-sm" onClick={handleNewSession}>New chat</button>
        </div>
      </aside>

      <div className="workspace">
        <header className="topbar">
          <div className="topbar-left">
            <h1 className="page-title">{navItems.find((tab) => tab.id === activeTab)?.label || "Overview"}</h1>
          </div>
          <div className="topbar-right">
            <ThemeToggle />
            <div className="status-pill">
              <span className={`status-dot ${healthTone === "ok" ? "" : healthTone}`} />
              {healthText}
            </div>
            {pendingApprovals > 0 ? (
              <button className="btn btn-sm" onClick={() => setActiveTab("approvals")}>
                {pendingApprovals} pending approvals
              </button>
            ) : null}
          </div>
        </header>

        <div className="mobile-nav" aria-label="Mobile navigation">
          {navItems.map((tab) => (
            <button
              key={tab.id}
              className={`tab ${activeTab === tab.id ? "active" : ""}`}
              onClick={() => setActiveTab(tab.id)}
            >
              {tab.label}
              {tab.id === "approvals" && pendingApprovals > 0 ? ` (${pendingApprovals})` : ""}
            </button>
          ))}
        </div>

        <main className={`view ${activeTab === "chat" ? "view-fill" : ""}`}>
          <ErrorBoundary key={activeTab}>
            {activeTab === "overview" && <OverviewCockpit activeSessionId={currentSessionId} />}
            {activeTab === "chat" && <ChatCockpit activeSessionId={currentSessionId} onNewSession={handleNewSession} onSessionChanged={setCurrentSessionId} onOpenApprovals={() => setActiveTab("approvals")} />}
            {activeTab === "loop" && <LoopCockpit activeSessionId={currentSessionId} />}
            {activeTab === "tasks" && <TaskBoard />}
            {activeTab === "memory" && <MemoryCockpit />}
            {activeTab === "memory_ops" && <MemoryObservabilityCockpit />}
            {activeTab === "approvals" && <ApprovalInbox />}
            {activeTab === "tools" && <ToolsCockpit />}
            {activeTab === "tools_ops" && <ToolsOpsCockpit />}
            {activeTab === "scheduled" && <ScheduledCockpit />}
            {activeTab === "workspace" && <WorkspaceCockpit onOpenApprovals={() => setActiveTab("approvals")} />}
            {activeTab === "data" && <DataCockpit />}
          </ErrorBoundary>
        </main>
      </div>
    </div>
  );
}

if (typeof window !== "undefined") {
  window.App = App;
}
