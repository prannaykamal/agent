import React, { useState, useEffect } from 'react';
import { api } from '../api/client.js';

export default function MemoryCockpit({ onRefresh }) {
  const [activeSubTab, setActiveSubTab] = useState("semantic");
  const [memoryData, setMemoryData] = useState(null);
  const [skillsList, setSkillsList] = useState([]);
  const [searchQuery, setSearchQuery] = useState("");
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState(null);
  const [successNotice, setSuccessNotice] = useState(null);

  // Permanent Fact Form State
  const [factCategory, setFactCategory] = useState("user_preference");
  const [factText, setFactText] = useState("");
  const [submittingFact, setSubmittingFact] = useState(false);

  // Skill Creation Form State
  const [showSkillModal, setShowSkillModal] = useState(false);
  const [skillName, setSkillName] = useState("");
  const [skillDescription, setSkillDescription] = useState("");
  const [skillKeywords, setSkillKeywords] = useState("");
  const [skillSteps, setSkillSteps] = useState("");
  const [submittingSkill, setSubmittingSkill] = useState(false);

  const fetchMemory = async (q = "") => {
    setLoading(true);
    setError(null);
    try {
      const url = q ? `/api/memory/full?query=${encodeURIComponent(q)}` : "/api/memory/full";
      const data = await api.get(url);
      setMemoryData(data);
    } catch (e) {
      console.error(e);
      setError(e.message || "Failed to load memory data");
    } finally {
      setLoading(false);
    }
  };

  const fetchSkills = async () => {
    try {
      const data = await api.get("/api/skills");
      setSkillsList(data.skills || []);
    } catch (e) {
      console.error("Failed to load active skills:", e);
    }
  };

  useEffect(() => {
    fetchMemory();
    fetchSkills();
  }, []);

  const handleAddFact = async (e) => {
    e.preventDefault();
    if (!factCategory.trim() || !factText.trim()) {
      setError("Category and fact text must not be empty.");
      return;
    }

    setSubmittingFact(true);
    setError(null);
    setSuccessNotice(null);
    try {
      await api.post("/api/memory/fact", {
        category: factCategory.trim(),
        fact_text: factText.trim()
      });
      setSuccessNotice(`Fact persisted under '${factCategory.trim()}'.`);
      setFactText("");
      fetchMemory(searchQuery);
      if (onRefresh) onRefresh();
    } catch (e) {
      setError(`Failed to add fact: ${e.message}`);
    } finally {
      setSubmittingFact(false);
    }
  };

  const handleCreateSkill = async (e) => {
    e.preventDefault();
    if (!skillName.trim() || !skillDescription.trim()) {
      setError("Skill name and description must not be empty.");
      return;
    }

    setSubmittingSkill(true);
    setError(null);
    setSuccessNotice(null);
    try {
      const trigger_keywords = skillKeywords
        .split(",")
        .map(k => k.trim())
        .filter(Boolean);
      const execution_steps = skillSteps
        .split("\n")
        .map(s => s.trim())
        .filter(Boolean);

      await api.post("/api/skills", {
        name: skillName.trim(),
        description: skillDescription.trim(),
        trigger_keywords,
        execution_steps
      });

      setSuccessNotice(`Active skill '${skillName.trim()}' created successfully.`);
      setSkillName("");
      setSkillDescription("");
      setSkillKeywords("");
      setSkillSteps("");
      setShowSkillModal(false);
      fetchSkills();
    } catch (e) {
      setError(`Failed to create skill: ${e.message}`);
    } finally {
      setSubmittingSkill(false);
    }
  };

  const handleDeleteSkill = async (name) => {
    if (!window.confirm(`Are you sure you want to delete/archive skill '${name}'?`)) return;
    setError(null);
    setSuccessNotice(null);
    try {
      await api.delete(`/api/skills/${encodeURIComponent(name)}`);
      setSuccessNotice(`Active skill '${name}' deleted successfully.`);
      fetchSkills();
    } catch (e) {
      setError(`Failed to delete skill '${name}': ${e.message}`);
    }
  };

  return (
    <div style={{ display: "flex", flexDirection: "column", gap: "20px" }}>
      {/* Top Header */}
      <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center" }}>
        <div>
          <h2 style={{ fontFamily: "var(--font-heading)", margin: 0 }}>🧠 Long-Term Memory & Active Skills</h2>
          <span style={{ fontSize: "12px", color: "var(--text-secondary)" }}>
            Persist permanent facts, manage system skills, and inspect identity subsystems.
          </span>
        </div>
        <button
          onClick={() => { fetchMemory(searchQuery); fetchSkills(); if (onRefresh) onRefresh(); }}
          style={{ padding: "8px 16px", background: "var(--primary-glow)", border: "none", borderRadius: "6px", color: "white", cursor: "pointer" }}
        >
          🔄 Refresh
        </button>
      </div>

      {/* Global Notices */}
      {successNotice && (
        <div style={{ padding: "10px 16px", background: "rgba(46, 204, 113, 0.15)", border: "1px solid rgba(46, 204, 113, 0.3)", borderRadius: "8px", color: "#2ecc71", fontSize: "13px" }}>
          ✅ {successNotice}
        </div>
      )}
      {error && (
        <div style={{ padding: "12px", background: "rgba(255, 50, 50, 0.15)", borderRadius: "8px", color: "#ff6b6b", fontSize: "13px" }}>
          ⚠️ Error: {error}
        </div>
      )}

      {/* Search Bar */}
      <div style={{ display: "flex", gap: "12px" }}>
        <input
          type="text"
          value={searchQuery}
          onChange={e => setSearchQuery(e.target.value)}
          onKeyDown={e => e.key === "Enter" && fetchMemory(searchQuery)}
          placeholder="Search semantic facts or past episodes..."
          style={{ flex: 1, padding: "10px 16px", background: "rgba(0,0,0,0.3)", border: "1px solid var(--border-glass)", borderRadius: "8px", color: "white" }}
        />
        <button onClick={() => fetchMemory(searchQuery)} style={{ padding: "10px 20px", background: "var(--primary-glow)", border: "none", borderRadius: "8px", color: "white", cursor: "pointer" }}>
          Search
        </button>
      </div>

      {/* Sub tabs */}
      <div style={{ display: "flex", gap: "10px", borderBottom: "1px solid var(--border-glass)", paddingBottom: "8px", flexWrap: "wrap" }}>
        {[
          { id: "semantic", label: "Semantic Facts" },
          { id: "active_skills", label: "Active Skills" },
          { id: "episodic", label: "Past Episodes" },
          { id: "soul", label: "SOUL.md" },
          { id: "skill_md", label: "SKILL.md Catalog" },
          { id: "memory_md", label: "MEMORY.md Mirror" }
        ].map(tab => (
          <button
            key={tab.id}
            onClick={() => setActiveSubTab(tab.id)}
            style={{
              padding: "8px 16px",
              background: activeSubTab === tab.id ? "rgba(255,255,255,0.1)" : "transparent",
              border: activeSubTab === tab.id ? "1px solid var(--border-glass)" : "none",
              borderRadius: "6px",
              color: activeSubTab === tab.id ? "white" : "var(--text-secondary)",
              cursor: "pointer",
              fontWeight: activeSubTab === tab.id ? "600" : "normal"
            }}
          >
            {tab.label}
          </button>
        ))}
      </div>

      {loading ? (
        <div style={{ padding: "32px", textAlign: "center", color: "var(--text-secondary)" }}>🌀 Loading memory data...</div>
      ) : (
        <>
          {/* Sub-Tab 1: Semantic Facts */}
          {activeSubTab === "semantic" && (
            <div style={{ display: "flex", flexDirection: "column", gap: "16px" }}>
              {/* Add Fact Entry Form Card */}
              <div className="glass-card" style={{ background: "rgba(0,0,0,0.3)" }}>
                <h3 style={{ margin: "0 0 12px 0", fontFamily: "var(--font-heading)", fontSize: "15px" }}>➕ Add Permanent Semantic Fact</h3>
                <form onSubmit={handleAddFact} style={{ display: "flex", flexDirection: "column", gap: "12px" }}>
                  <div style={{ display: "grid", gridTemplateColumns: "1fr 3fr", gap: "12px" }}>
                    <div>
                      <label style={{ fontSize: "12px", color: "var(--text-secondary)", display: "block", marginBottom: "4px" }}>Category</label>
                      <input
                        type="text"
                        value={factCategory}
                        onChange={e => setFactCategory(e.target.value)}
                        placeholder="e.g. user_preference"
                        style={{ width: "100%", padding: "8px 12px", background: "rgba(255,255,255,0.05)", border: "1px solid var(--border-glass)", borderRadius: "6px", color: "white", fontSize: "13px" }}
                      />
                    </div>
                    <div>
                      <label style={{ fontSize: "12px", color: "var(--text-secondary)", display: "block", marginBottom: "4px" }}>Fact Text</label>
                      <input
                        type="text"
                        value={factText}
                        onChange={e => setFactText(e.target.value)}
                        placeholder="e.g. User prefers concise bullet points for summaries."
                        style={{ width: "100%", padding: "8px 12px", background: "rgba(255,255,255,0.05)", border: "1px solid var(--border-glass)", borderRadius: "6px", color: "white", fontSize: "13px" }}
                      />
                    </div>
                  </div>
                  <div style={{ display: "flex", justifyContent: "flex-end" }}>
                    <button
                      type="submit"
                      disabled={submittingFact}
                      style={{ padding: "8px 18px", background: "var(--primary-glow)", border: "none", borderRadius: "6px", color: "white", cursor: "pointer", fontSize: "13px", fontWeight: "600" }}
                    >
                      {submittingFact ? "Saving..." : "Save Permanent Fact"}
                    </button>
                  </div>
                </form>
              </div>

              {/* Facts List */}
              <div className="glass-card">
                <h3 style={{ margin: "0 0 12px 0", fontFamily: "var(--font-heading)" }}>Semantic Facts ({memoryData?.facts?.length || 0})</h3>
                {(!memoryData?.facts || memoryData.facts.length === 0) ? (
                  <div style={{ color: "var(--text-secondary)", fontStyle: "italic", padding: "16px 0" }}>📭 No semantic facts registered yet.</div>
                ) : (
                  memoryData.facts.map((f, i) => (
                    <div key={i} style={{ padding: "10px 0", borderBottom: "1px solid var(--border-glass)", display: "flex", gap: "10px", alignItems: "baseline" }}>
                      <span style={{ padding: "2px 8px", background: "rgba(255,255,255,0.08)", borderRadius: "4px", fontSize: "11px", color: "var(--text-secondary)", fontWeight: "600" }}>
                        [{f.category}]
                      </span>
                      <span style={{ fontSize: "13px" }}>{f.fact_text}</span>
                    </div>
                  ))
                )}
              </div>
            </div>
          )}

          {/* Sub-Tab 2: Active Skills Management */}
          {activeSubTab === "active_skills" && (
            <div style={{ display: "flex", flexDirection: "column", gap: "16px" }}>
              <div className="glass-card" style={{ background: "rgba(0,0,0,0.2)" }}>
                <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center", marginBottom: "10px" }}>
                  <div>
                    <h3 style={{ margin: 0, fontFamily: "var(--font-heading)" }}>🛠️ Active System Skills</h3>
                    <span style={{ fontSize: "12px", color: "var(--text-secondary)" }}>
                      ℹ️ Active Skill Management: Manage live system skills. Memory Ops provides procedural candidate tracking & versioning.
                    </span>
                  </div>
                  <button
                    onClick={() => setShowSkillModal(true)}
                    style={{ padding: "8px 16px", background: "var(--primary-glow)", border: "none", borderRadius: "6px", color: "white", cursor: "pointer", fontSize: "13px", fontWeight: "600" }}
                  >
                    ➕ Create Active Skill
                  </button>
                </div>

                {/* Create Skill Form Card/Modal */}
                {showSkillModal && (
                  <div style={{ marginTop: "12px", padding: "16px", background: "rgba(0,0,0,0.4)", border: "1px solid var(--primary-glow)", borderRadius: "8px" }}>
                    <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center", marginBottom: "12px" }}>
                      <h4 style={{ margin: 0 }}>Create New Active Skill</h4>
                      <button onClick={() => setShowSkillModal(false)} style={{ background: "none", border: "none", color: "var(--text-secondary)", cursor: "pointer" }}>✖</button>
                    </div>
                    <form onSubmit={handleCreateSkill} style={{ display: "flex", flexDirection: "column", gap: "12px" }}>
                      <div style={{ display: "grid", gridTemplateColumns: "1fr 2fr", gap: "12px" }}>
                        <div>
                          <label style={{ fontSize: "12px", color: "var(--text-secondary)", display: "block", marginBottom: "4px" }}>Skill Name</label>
                          <input
                            type="text"
                            value={skillName}
                            onChange={e => setSkillName(e.target.value)}
                            placeholder="e.g. summarize_email"
                            style={{ width: "100%", padding: "8px 12px", background: "rgba(255,255,255,0.05)", border: "1px solid var(--border-glass)", borderRadius: "6px", color: "white", fontSize: "13px" }}
                          />
                        </div>
                        <div>
                          <label style={{ fontSize: "12px", color: "var(--text-secondary)", display: "block", marginBottom: "4px" }}>Description</label>
                          <input
                            type="text"
                            value={skillDescription}
                            onChange={e => setSkillDescription(e.target.value)}
                            placeholder="e.g. Summarizes email threads into key bullet points"
                            style={{ width: "100%", padding: "8px 12px", background: "rgba(255,255,255,0.05)", border: "1px solid var(--border-glass)", borderRadius: "6px", color: "white", fontSize: "13px" }}
                          />
                        </div>
                      </div>

                      <div>
                        <label style={{ fontSize: "12px", color: "var(--text-secondary)", display: "block", marginBottom: "4px" }}>Trigger Keywords (comma separated)</label>
                        <input
                          type="text"
                          value={skillKeywords}
                          onChange={e => setSkillKeywords(e.target.value)}
                          placeholder="e.g. summarize, email, inbox, digest"
                          style={{ width: "100%", padding: "8px 12px", background: "rgba(255,255,255,0.05)", border: "1px solid var(--border-glass)", borderRadius: "6px", color: "white", fontSize: "13px" }}
                        />
                      </div>

                      <div>
                        <label style={{ fontSize: "12px", color: "var(--text-secondary)", display: "block", marginBottom: "4px" }}>Execution Steps (one per line)</label>
                        <textarea
                          rows={3}
                          value={skillSteps}
                          onChange={e => setSkillSteps(e.target.value)}
                          placeholder="Step 1: Fetch recent unread emails&#10;Step 2: Extract top 3 key action items&#10;Step 3: Format summary"
                          style={{ width: "100%", padding: "8px 12px", background: "rgba(255,255,255,0.05)", border: "1px solid var(--border-glass)", borderRadius: "6px", color: "white", fontSize: "13px" }}
                        />
                      </div>

                      <div style={{ display: "flex", justifyContent: "flex-end", gap: "8px" }}>
                        <button type="button" onClick={() => setShowSkillModal(false)} style={{ padding: "8px 14px", background: "transparent", border: "1px solid var(--border-glass)", borderRadius: "6px", color: "var(--text-secondary)", cursor: "pointer", fontSize: "13px" }}>
                          Cancel
                        </button>
                        <button type="submit" disabled={submittingSkill} style={{ padding: "8px 16px", background: "var(--primary-glow)", border: "none", borderRadius: "6px", color: "white", cursor: "pointer", fontSize: "13px", fontWeight: "600" }}>
                          {submittingSkill ? "Creating..." : "Save Active Skill"}
                        </button>
                      </div>
                    </form>
                  </div>
                )}
              </div>

              {/* Skills List */}
              <div className="glass-card">
                {skillsList.length === 0 ? (
                  <div style={{ color: "var(--text-secondary)", fontStyle: "italic", padding: "16px 0" }}>📭 No active skills registered in backend registry.</div>
                ) : (
                  <div style={{ display: "grid", gap: "12px" }}>
                    {skillsList.map(s => (
                      <div key={s.name} style={{ padding: "12px", background: "rgba(255,255,255,0.03)", border: "1px solid var(--border-glass)", borderRadius: "8px", display: "flex", justifyContent: "space-between", gap: "12px" }}>
                        <div style={{ flex: 1 }}>
                          <div style={{ display: "flex", gap: "8px", alignItems: "center" }}>
                            <strong style={{ fontSize: "14px" }}>{s.name}</strong>
                          </div>
                          <p style={{ margin: "4px 0 8px 0", fontSize: "13px", color: "var(--text-secondary)" }}>{s.description}</p>
                          {s.trigger_keywords && s.trigger_keywords.length > 0 && (
                            <div style={{ display: "flex", gap: "6px", flexWrap: "wrap", marginBottom: "6px" }}>
                              {s.trigger_keywords.map((k, idx) => (
                                <span key={idx} style={{ padding: "2px 6px", background: "rgba(52, 152, 219, 0.18)", color: "#3498db", borderRadius: "4px", fontSize: "11px" }}>
                                  #{k}
                                </span>
                              ))}
                            </div>
                          )}
                          {s.execution_steps && s.execution_steps.length > 0 && (
                            <ol style={{ margin: "4px 0 0 16px", padding: 0, fontSize: "12px", color: "var(--text-secondary)" }}>
                              {s.execution_steps.map((step, idx) => <li key={idx}>{step}</li>)}
                            </ol>
                          )}
                        </div>
                        <div>
                          <button
                            onClick={() => handleDeleteSkill(s.name)}
                            style={{ padding: "6px 12px", background: "rgba(255,71,87,0.15)", border: "1px solid rgba(255,71,87,0.3)", borderRadius: "6px", color: "#ff6b6b", cursor: "pointer", fontSize: "12px" }}
                          >
                            🗑️ Delete
                          </button>
                        </div>
                      </div>
                    ))}
                  </div>
                )}
              </div>
            </div>
          )}

          {/* Sub-Tab 3: Past Episodes */}
          {activeSubTab === "episodic" && (
            <div className="glass-card">
              <h3>Past Episodes ({memoryData?.episodes?.length || 0})</h3>
              {(!memoryData?.episodes || memoryData.episodes.length === 0) ? (
                <div style={{ color: "var(--text-secondary)", fontStyle: "italic", padding: "16px 0" }}>📭 No past episodes recorded.</div>
              ) : (
                memoryData.episodes.map((ep, i) => (
                  <div key={i} style={{ padding: "10px 0", borderBottom: "1px solid var(--border-glass)" }}>
                    <div><strong>{ep.timestamp}</strong> - <code>{ep.session_id}</code></div>
                    <div style={{ color: "var(--text-secondary)", fontSize: "13px", marginTop: "4px" }}>{ep.content}</div>
                  </div>
                ))
              )}
            </div>
          )}

          {/* Sub-Tab 4: SOUL.md */}
          {activeSubTab === "soul" && (
            <div className="glass-card">
              <h3>SOUL.md Identity Master Prompt</h3>
              <pre style={{ whiteSpace: "pre-wrap", fontFamily: "monospace", fontSize: "13px", background: "rgba(0,0,0,0.3)", padding: "14px", borderRadius: "6px" }}>
                {memoryData?.soul_md || "(Empty SOUL.md)"}
              </pre>
            </div>
          )}

          {/* Sub-Tab 5: SKILL.md Catalog */}
          {activeSubTab === "skill_md" && (
            <div className="glass-card">
              <h3>SKILL.md Procedural Knowledge Catalog</h3>
              <pre style={{ whiteSpace: "pre-wrap", fontFamily: "monospace", fontSize: "13px", background: "rgba(0,0,0,0.3)", padding: "14px", borderRadius: "6px" }}>
                {memoryData?.skill_md || "(Empty SKILL.md)"}
              </pre>
            </div>
          )}

          {/* Sub-Tab 6: MEMORY.md Mirror */}
          {activeSubTab === "memory_md" && (
            <div className="glass-card">
              <h3>MEMORY.md Auto-Synced Fact Mirror</h3>
              <pre style={{ whiteSpace: "pre-wrap", fontFamily: "monospace", fontSize: "13px", background: "rgba(0,0,0,0.3)", padding: "14px", borderRadius: "6px" }}>
                {memoryData?.memory_md || "(Empty MEMORY.md)"}
              </pre>
            </div>
          )}
        </>
      )}
    </div>
  );
}

if (typeof window !== "undefined") {
  window.MemoryCockpit = MemoryCockpit;
}

