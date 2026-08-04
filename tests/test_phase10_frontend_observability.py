from pathlib import Path


def test_observability_component_exists_and_exports():
    path = Path("frontend/src/components/MemoryObservabilityCockpit.jsx")
    text = path.read_text(encoding="utf-8")

    assert path.exists()
    assert "export default function MemoryObservabilityCockpit" in text
    assert "window.MemoryObservabilityCockpit" in text


def test_memory_ops_tab_is_wired_in_app():
    text = Path("frontend/src/App.jsx").read_text(encoding="utf-8")

    assert "MemoryObservabilityCockpit" in text
    assert 'id: "memory_ops"' in text
    assert "Memory Ops" in text
    assert 'activeTab === "memory_ops"' in text


def test_component_fetches_observability_endpoints_only():
    text = Path("frontend/src/components/MemoryObservabilityCockpit.jsx").read_text(encoding="utf-8")

    expected = [
        "/api/memory/observability/overview",
        "/api/memory/observability/health",
        "/api/memory/observability/jobs",
        "/api/memory/observability/workers",
        "/api/memory/observability/dead-letter",
        "/api/memory/observability/retrieval/trace",
        "/api/memory/observability/semantic",
        "/api/memory/observability/procedural",
        "/api/memory/observability/skills",
    ]
    for endpoint in expected:
        assert endpoint in text
    assert "/api/chat" not in text
    assert "/api/skills" not in text
    assert "/api/approvals" not in text
    assert "/api/memory/fact" not in text


def test_empty_and_error_states_rendered_in_component():
    text = Path("frontend/src/components/MemoryObservabilityCockpit.jsx").read_text(encoding="utf-8")

    assert "No memory jobs found." in text
    assert "No worker heartbeats recorded" in text
    assert "No dead-lettered memory jobs." in text
    assert "No semantic candidates." in text
    assert "No procedural candidates." in text
    assert "No active skill versions." in text
    assert "Failed to load memory observability" in text
    assert "Trace failed" in text


def test_prompt_block_hidden_by_default_and_trace_is_explicit():
    text = Path("frontend/src/components/MemoryObservabilityCockpit.jsx").read_text(encoding="utf-8")

    assert "useState(false)" in text
    assert "include_prompt_block: showPromptBlock" in text
    assert "Show redacted prompt block" in text
    assert "method: 'POST'" in text
