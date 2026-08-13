import React, { useEffect, useState } from "react";
import { api } from "../api/client.js";
import PageHeader from "./ui/PageHeader.jsx";
import Notice from "./ui/Notice.jsx";
import Spinner from "./ui/Spinner.jsx";
import Badge from "./ui/Badge.jsx";
import { asList } from "../lib/format.js";

export default function MemoryCockpit({ onRefresh }) {
  const [activeSubTab, setActiveSubTab] = useState("semantic");
  const [memoryData, setMemoryData] = useState(null);
  const [skillsList, setSkillsList] = useState([]);
  const [searchQuery, setSearchQuery] = useState("");
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState(null);
  const [successNotice, setSuccessNotice] = useState(null);
  const [factCategory, setFactCategory] = useState("user_preference");
  const [factText, setFactText] = useState("");
  const [submittingFact, setSubmittingFact] = useState(false);
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
      await api.post("/api/memory/fact", { category: factCategory.trim(), fact_text: factText.trim() });
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
      await api.post("/api/skills", {
        name: skillName.trim(),
        description: skillDescription.trim(),
        trigger_keywords: skillKeywords.trim(),
        execution_steps: skillSteps.trim(),
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

  const getKeywordsList = (val) => asList(val, ",");
  const getStepsList = (val) => asList(val, "\n");

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
    <div className="page">
      <PageHeader
        title="Memory"
        subtitle="Facts, skills, and identity files."
        actions={<button className="btn btn-primary" onClick={() => { fetchMemory(searchQuery); fetchSkills(); if (onRefresh) onRefresh(); }}>Refresh</button>}
      />

      {successNotice ? <Notice kind="ok">{successNotice}</Notice> : null}
      {error ? <Notice kind="error">Error: {error}</Notice> : null}

      <div className="actions">
        <input
          value={searchQuery}
          onChange={(e) => setSearchQuery(e.target.value)}
          onKeyDown={(e) => e.key === "Enter" && fetchMemory(searchQuery)}
          placeholder="Search semantic facts or past episodes..."
        />
        <button className="btn btn-primary" onClick={() => fetchMemory(searchQuery)}>Search</button>
      </div>

      <div className="tabs">
        {[
          { id: "semantic", label: "Semantic Facts" },
          { id: "active_skills", label: "Active Skills" },
          { id: "episodic", label: "Past Episodes" },
          { id: "soul", label: "SOUL.md" },
          { id: "skill_md", label: "SKILL.md Catalog" },
          { id: "memory_md", label: "MEMORY.md Mirror" },
        ].map((tab) => (
          <button key={tab.id} className={`tab ${activeSubTab === tab.id ? "active" : ""}`} onClick={() => setActiveSubTab(tab.id)}>
            {tab.label}
          </button>
        ))}
      </div>

      {loading ? (
        <Spinner label="Loading memory data..." />
      ) : (
        <>
          {activeSubTab === "semantic" && (
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
                    {submittingFact ? "Saving..." : "Save Permanent Fact"}
                  </button>
                </form>
              </section>
              <section className="glass-card">
                <h3>Semantic Facts ({memoryData?.facts?.length || 0})</h3>
                {(!memoryData?.facts || memoryData.facts.length === 0) ? (
                  <div className="lede">No semantic facts registered yet.</div>
                ) : (
                  memoryData.facts.map((f, i) => (
                    <div key={i} className="row-card">
                      <span><Badge value={f.category} /> {f.fact_text}</span>
                    </div>
                  ))
                )}
              </section>
            </>
          )}

          {activeSubTab === "active_skills" && (
            <>
              <section className="glass-card">
                <div className="card-head">
                  <div>
                    <h3>Skills</h3>
                    <p className="lede">Live skills. Memory Ops tracks candidates and versions.</p>
                  </div>
                  <button className="btn btn-primary" onClick={() => setShowSkillModal(true)}>Create Active Skill</button>
                </div>
                {showSkillModal ? (
                  <form onSubmit={handleCreateSkill} style={{ display: "flex", flexDirection: "column", gap: 12 }}>
                    <div className="form-grid">
                      <label className="field">Skill Name<input value={skillName} onChange={(e) => setSkillName(e.target.value)} placeholder="e.g. summarize_email" /></label>
                      <label className="field">Description<input value={skillDescription} onChange={(e) => setSkillDescription(e.target.value)} placeholder="Summarizes email threads into key bullet points" /></label>
                    </div>
                    <label className="field">Trigger Keywords (comma separated)
                      <input value={skillKeywords} onChange={(e) => setSkillKeywords(e.target.value)} placeholder="summarize, email, inbox, digest" />
                    </label>
                    <label className="field">Execution Steps (one per line)
                      <textarea rows={3} value={skillSteps} onChange={(e) => setSkillSteps(e.target.value)} placeholder={"Step 1: Fetch recent unread emails\nStep 2: Extract top 3 key action items\nStep 3: Format summary"} />
                    </label>
                    <div className="actions" style={{ justifyContent: "flex-end" }}>
                      <button type="button" className="btn btn-ghost" onClick={() => setShowSkillModal(false)}>Cancel</button>
                      <button type="submit" className="btn btn-primary" disabled={submittingSkill}>{submittingSkill ? "Creating..." : "Save Active Skill"}</button>
                    </div>
                  </form>
                ) : null}
              </section>
              <section className="glass-card">
                {skillsList.length === 0 ? (
                  <div className="lede">No active skills registered in backend registry.</div>
                ) : (
                  skillsList.map((s) => {
                    const keywords = getKeywordsList(s.trigger_keywords);
                    const steps = getStepsList(s.execution_steps);
                    return (
                      <div key={s.name} className="provider-card" style={{ marginBottom: 10 }}>
                        <div className="row-card" style={{ border: 0, padding: 0 }}>
                          <div>
                            <strong>{s.name}</strong>
                            <p className="lede">{s.description}</p>
                            <div className="chip-row">
                              {keywords.map((k, idx) => <Badge key={idx} value={k} />)}
                            </div>
                            {steps.length > 0 ? (
                              <ol style={{ margin: "8px 0 0 18px", color: "var(--text-secondary)", fontSize: 12 }}>
                                {steps.map((step, idx) => <li key={idx}>{step}</li>)}
                              </ol>
                            ) : null}
                          </div>
                          <button className="btn btn-danger btn-sm" onClick={() => handleDeleteSkill(s.name)}>Delete</button>
                        </div>
                      </div>
                    );
                  })
                )}
              </section>
            </>
          )}

          {activeSubTab === "episodic" && (
            <section className="glass-card">
              <h3>Past Episodes ({memoryData?.episodes?.length || 0})</h3>
              {(!memoryData?.episodes || memoryData.episodes.length === 0) ? (
                <div className="lede">No past episodes recorded.</div>
              ) : (
                memoryData.episodes.map((ep, i) => (
                  <div key={i} className="row-card">
                    <div>
                      <strong>{ep.timestamp}</strong> — <code>{ep.session_id}</code>
                      <div className="lede">{ep.content}</div>
                    </div>
                  </div>
                ))
              )}
            </section>
          )}

          {activeSubTab === "soul" && (
            <section className="glass-card">
              <h3>SOUL.md</h3>
              <pre className="md-block">{memoryData?.soul_md || "(Empty SOUL.md)"}</pre>
            </section>
          )}
          {activeSubTab === "skill_md" && (
            <section className="glass-card">
              <h3>SKILL.md</h3>
              <pre className="md-block">{memoryData?.skill_md || "(Empty SKILL.md)"}</pre>
            </section>
          )}
          {activeSubTab === "memory_md" && (
            <section className="glass-card">
              <h3>MEMORY.md</h3>
              <pre className="md-block">{memoryData?.memory_md || "(Empty MEMORY.md)"}</pre>
            </section>
          )}
        </>
      )}
    </div>
  );
}

if (typeof window !== "undefined") {
  window.MemoryCockpit = MemoryCockpit;
}
