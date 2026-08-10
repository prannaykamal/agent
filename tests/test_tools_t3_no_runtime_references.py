from pathlib import Path

from src.hitl.classifier import classify_tool_risk
from src.tools.registry import get_bindable_tool_metadata, get_removed_tool_metadata
from src.tools.registry_types import ImplementationType

REPO_ROOT = Path(__file__).resolve().parents[1]
REMOVED_TOOLS = {
    "safe_browse_url",
    "capture_screenshot",
    "run_code",
    "github_clone",
    "github_commit_and_push",
    "github_merge",
}
FORBIDDEN_RUNTIME_REFERENCES = [
    "src.mcp_gateway." + "sand" + "boxes.browser_" + "sandbox",
    "src.mcp_gateway." + "sand" + "boxes.code_" + "sandbox",
    "/api/" + "browser",
    "/api/" + "github",
]


def _iter_text_files(root: Path):
    if not root.exists():
        return
    for path in root.rglob("*"):
        if path.is_file() and "__pycache__" not in path.parts:
            yield path


def test_t3_removed_tools_not_bindable_but_metadata_remains():
    bindable_names = {item.legacy_name for item in get_bindable_tool_metadata()}
    assert bindable_names.isdisjoint(REMOVED_TOOLS)

    removed = {item.legacy_name: item for item in get_removed_tool_metadata()}
    assert REMOVED_TOOLS <= set(removed)
    for name in REMOVED_TOOLS:
        assert removed[name].implementation_type == ImplementationType.REMOVED
        assert removed[name].enabled is False


def test_t3_removed_tools_remain_blocked_by_hitl_policy():
    for name in REMOVED_TOOLS:
        risk, reason = classify_tool_risk(name)
        assert risk == "Blocked"
        assert reason


def test_t3_runtime_no_deleted_module_or_removed_route_references():
    violations = []
    for root in [REPO_ROOT / "src", REPO_ROOT / "frontend" / "src"]:
        for path in _iter_text_files(root):
            text = path.read_text(encoding="utf-8", errors="ignore")
            for needle in FORBIDDEN_RUNTIME_REFERENCES:
                if needle in text:
                    violations.append((path.relative_to(REPO_ROOT).as_posix(), needle))
    assert violations == []


def test_t3_tests_do_not_import_deleted_sandbox_modules():
    violations = []
    for path in _iter_text_files(REPO_ROOT / "tests"):
        text = path.read_text(encoding="utf-8", errors="ignore")
        for needle in [
            "src.mcp_gateway." + "sand" + "boxes.browser_" + "sandbox",
            "src.mcp_gateway." + "sand" + "boxes.code_" + "sandbox",
        ]:
            if needle in text:
                violations.append((path.relative_to(REPO_ROOT).as_posix(), needle))
    assert violations == []
