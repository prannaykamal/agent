from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[1]
RUNTIME_SCAN_ROOTS = [REPO_ROOT / "src", REPO_ROOT / "frontend"]
TEST_SCAN_ROOT = REPO_ROOT / "tests"

DELETED_MODULE_REFERENCES = [
    "src.mcp_gateway." + "sand" + "boxes.browser_" + "sandbox",
    "src.mcp_gateway." + "sand" + "boxes.code_" + "sandbox",
]
REMOVED_ROUTE_REFERENCES = ["/api/" + "browser", "/api/" + "github"]


def _iter_text_files(root: Path):
    if not root.exists():
        return
    for path in root.rglob("*"):
        if path.is_file() and "__pycache__" not in path.parts:
            yield path


def test_t0_static_scan_runtime_no_longer_imports_deleted_sandbox_modules():
    violations = []
    for root in RUNTIME_SCAN_ROOTS:
        for path in _iter_text_files(root):
            text = path.read_text(encoding="utf-8", errors="ignore")
            for needle in DELETED_MODULE_REFERENCES:
                if needle in text:
                    violations.append((path.relative_to(REPO_ROOT).as_posix(), needle))
    assert violations == []


def test_t0_static_scan_frontend_has_no_removed_route_calls():
    violations = []
    for root in [REPO_ROOT / "frontend" / "src"]:
        for path in _iter_text_files(root):
            text = path.read_text(encoding="utf-8", errors="ignore")
            for needle in REMOVED_ROUTE_REFERENCES:
                if needle in text:
                    violations.append((path.relative_to(REPO_ROOT).as_posix(), needle))
    assert violations == []


def test_t0_static_scan_tests_do_not_import_deleted_sandbox_modules():
    violations = []
    for path in _iter_text_files(TEST_SCAN_ROOT):
        text = path.read_text(encoding="utf-8", errors="ignore")
        for needle in DELETED_MODULE_REFERENCES:
            if needle in text:
                violations.append((path.relative_to(REPO_ROOT).as_posix(), needle))
    assert violations == []
