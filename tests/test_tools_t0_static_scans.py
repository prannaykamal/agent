from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[1]
SCAN_ROOTS = [
    REPO_ROOT / "src",
    REPO_ROOT / "frontend",
    REPO_ROOT / "tests",
    REPO_ROOT / "docs",
]
SCAN_FILES = [
    REPO_ROOT / "README.md",
    REPO_ROOT / "pyproject.toml",
    REPO_ROOT / "requirements.txt",
]

BASELINE_REFERENCES_TO_REMOVE_LATER = [
    "browser_sandbox",
    "code_sandbox",
    "safe_browse_url",
    "capture_screenshot",
    "run_code",
    "github_clone",
    "github_commit_and_push",
    "github_merge",
    "/api/browser",
    "/api/github",
]


def _iter_text_files():
    for root in SCAN_ROOTS:
        if not root.exists():
            continue
        for path in root.rglob("*"):
            if path.is_file() and "__pycache__" not in path.parts:
                yield path

    for path in SCAN_FILES:
        if path.exists():
            yield path


def _repo_text_corpus() -> str:
    chunks = []
    for path in _iter_text_files():
        try:
            chunks.append(path.read_text(encoding="utf-8", errors="ignore"))
        except OSError:
            continue
    return "\n".join(chunks)


def test_t0_migration_baseline_static_scan_confirms_current_sandbox_references_exist():
    corpus = _repo_text_corpus()

    missing = [needle for needle in BASELINE_REFERENCES_TO_REMOVE_LATER if needle not in corpus]

    # Expected current-state baseline only. Phase T3 should invert this test.
    assert missing == []


def test_t0_migration_baseline_static_scan_can_name_reference_sources():
    reference_sources = {}
    for needle in BASELINE_REFERENCES_TO_REMOVE_LATER:
        matches = []
        for path in _iter_text_files():
            try:
                text = path.read_text(encoding="utf-8", errors="ignore")
            except OSError:
                continue
            if needle in text:
                matches.append(path.relative_to(REPO_ROOT).as_posix())
        reference_sources[needle] = matches

    assert all(reference_sources[needle] for needle in BASELINE_REFERENCES_TO_REMOVE_LATER)
    assert "src/mcp_gateway/sandboxes/browser_sandbox.py" in reference_sources["safe_browse_url"]
    assert "src/mcp_gateway/sandboxes/code_sandbox.py" in reference_sources["run_code"]
