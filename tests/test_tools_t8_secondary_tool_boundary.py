from pathlib import Path


def test_t8_memory_and_router_paths_do_not_bind_user_facing_tools():
    roots = [Path("src/memory"), Path("src/harness/llm_router.py")]
    forbidden = ["get_all_personal_os_tools", "get_all_mcp_tools", "get_registered_tools", ".bind_tools("]
    offenders = []
    for root in roots:
        files = root.rglob("*.py") if root.is_dir() else [root]
        for file in files:
            text = file.read_text(encoding="utf-8")
            for marker in forbidden:
                if marker in text:
                    offenders.append(f"{file}:{marker}")
    assert offenders == []


def test_t8_secondary_llm_helpers_do_not_expose_tool_registry():
    text = Path("src/harness/llm_router.py").read_text(encoding="utf-8")
    assert "get_secondary_llm" in text or "resolve_secondary_llm" in text
    assert "bind_tools" not in text
    assert "get_registered_tools" not in text