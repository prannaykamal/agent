from src.startup import ensure_system_initialized


def test_startup_creates_skill_directories_without_overwriting_skill_md(tmp_path, monkeypatch):
    agent_dir = tmp_path / ".agent"
    skill_path = agent_dir / "SKILL.md"
    skill_path.parent.mkdir(parents=True, exist_ok=True)
    skill_path.write_text("user-authored index", encoding="utf-8")
    monkeypatch.setattr("src.startup.AGENT_DIR", agent_dir)
    monkeypatch.setattr("src.startup.SKILL_PATH", skill_path)
    monkeypatch.setattr("src.startup.MEMORY_PATH", agent_dir / "MEMORY.md")
    monkeypatch.setattr("src.startup.SOUL_PATH", agent_dir / "SOUL.md")
    monkeypatch.setattr("src.startup.DB_PATH", agent_dir / "state.db")

    result = ensure_system_initialized()

    assert (agent_dir / "skills" / "generated").exists()
    assert (agent_dir / "skills" / "user").exists()
    assert skill_path.read_text(encoding="utf-8") == "user-authored index"
    assert result["generated_skill_dir_exists"] is True
    assert result["user_skill_dir_exists"] is True


def test_startup_creates_compatibility_index_only_when_missing(tmp_path, monkeypatch):
    agent_dir = tmp_path / ".agent"
    skill_path = agent_dir / "SKILL.md"
    monkeypatch.setattr("src.startup.AGENT_DIR", agent_dir)
    monkeypatch.setattr("src.startup.SKILL_PATH", skill_path)
    monkeypatch.setattr("src.startup.MEMORY_PATH", agent_dir / "MEMORY.md")
    monkeypatch.setattr("src.startup.SOUL_PATH", agent_dir / "SOUL.md")
    monkeypatch.setattr("src.startup.DB_PATH", agent_dir / "state.db")

    result = ensure_system_initialized()

    assert skill_path.exists()
    assert "generated-by: personal-agent-skill-index v1" in skill_path.read_text(encoding="utf-8")
    assert result["skill_exists"] is True
