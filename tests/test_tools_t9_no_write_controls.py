from pathlib import Path

FRONTEND_FILES = list(Path("frontend/src").rglob("*.jsx")) + list(Path("frontend/src").rglob("*.js"))


def test_t9_frontend_does_not_call_removed_routes():
    combined = "\n".join(path.read_text(encoding="utf-8") for path in FRONTEND_FILES)
    assert "/api/browser" not in combined
    assert "/api/github" not in combined


def test_t9_tools_ops_adds_no_unsafe_write_controls():
    text = Path("frontend/src/components/ToolsOpsCockpit.jsx").read_text(encoding="utf-8")
    forbidden = ["method: 'POST'", 'method: "POST"', "method: 'PATCH'", 'method: "PATCH"', "method: 'DELETE'", 'method: "DELETE"']
    for marker in forbidden:
        assert marker not in text
    assert "create_approval_request" not in text
    assert "tools/call" not in text


def test_t9_frontend_source_does_not_contain_raw_secret_literals():
    combined = "\n".join(path.read_text(encoding="utf-8") for path in FRONTEND_FILES)
    for marker in ["api_key", "access_token", "refresh_token", "chain_of_thought", "scratchpad"]:
        assert marker not in combined.lower()