from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[1]

BOUNDARY_SCAN_FILES = [
    *sorted((REPO_ROOT / "src" / "memory").glob("*.py")),
    REPO_ROOT / "src" / "memory" / "job_handlers.py",
    REPO_ROOT / "src" / "memory" / "worker.py",
    REPO_ROOT / "src" / "memory" / "job_router.py",
    REPO_ROOT / "src" / "harness" / "llm_router.py",
]

FORBIDDEN_USER_FACING_TOOL_BOUNDARY_REFERENCES = [
    "get_all_personal_os_tools",
    "get_all_mcp_tools",
    "get_registered_tools",
    ".bind_tools",
]


def _read_existing_scan_files():
    for path in BOUNDARY_SCAN_FILES:
        if path.exists() and path.is_file():
            yield path, path.read_text(encoding="utf-8", errors="ignore")


def test_t0_migration_baseline_memory_side_modules_do_not_bind_user_facing_tools():
    violations = []

    for path, text in _read_existing_scan_files():
        for forbidden in FORBIDDEN_USER_FACING_TOOL_BOUNDARY_REFERENCES:
            if forbidden in text:
                violations.append((path.relative_to(REPO_ROOT).as_posix(), forbidden))

    assert violations == []


def test_t0_migration_baseline_secondary_llm_router_does_not_import_tool_registries():
    llm_router_path = REPO_ROOT / "src" / "harness" / "llm_router.py"
    text = llm_router_path.read_text(encoding="utf-8", errors="ignore")

    assert "src.personal_os.registry" not in text
    assert "src.mcp_gateway.registry" not in text
    assert "get_registered_tools" not in text
