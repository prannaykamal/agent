from pathlib import Path


DOCS = [
    "docs/tools-architecture.md",
    "docs/tools-operator-runbook.md",
    "docs/tools-mcp-wiring.md",
    "docs/tools-security-policy.md",
    "docs/tools-cron-jobs.md",
    "docs/tools-personal-os.md",
    "docs/tools-mcp-provider-validation.md",
]


def _doc_text():
    return "\n".join(Path(path).read_text(encoding="utf-8").lower() for path in DOCS)


def test_t10_required_tools_docs_exist():
    for path in DOCS:
        assert Path(path).exists(), path


def test_t10_docs_describe_final_architecture_boundaries():
    text = _doc_text()
    required_phrases = [
        "provider-managed mcp",
        "manual validation",
        "do not add local duplicate implementations",
        "cron is the local durable scheduler",
        "google calendar",
        "personal os is the bounded local",
        "hitl",
        "approval resume",
        "redaction",
        "secondary memory llm",
    ]
    for phrase in required_phrases:
        assert phrase in text


def test_t10_docs_do_not_advertise_removed_sandbox_as_current_feature():
    text = _doc_text()
    assert "browser sandbox and code/github sandbox are removed" in text
    assert "removed browser/code sandbox" in text
    prohibited_current_claims = [
        "browser sandbox is available",
        "code sandbox is available",
        "run_code is available",
        "use /api/browser",
        "use /api/github",
    ]
    for phrase in prohibited_current_claims:
        assert phrase not in text
