import os
import pytest
from pathlib import Path
from src.config import BASE_DIR

def test_p8_1_architecture_doc_exists_and_complete():
    """P8 Items 1-8: Verifies docs/ARCHITECTURE.md exists and documents all system subsystems."""
    arch_doc = BASE_DIR / "docs" / "ARCHITECTURE.md"
    assert arch_doc.exists()
    assert arch_doc.is_file()

    content = arch_doc.read_text(encoding="utf-8")
    assert len(content) > 1000

    # Verify required sections
    assert "High-Level System Architecture" in content
    assert "Feature Status & Capability Matrix" in content
    assert "SQLite Database Schema Specification" in content
    assert "Human-In-The-Loop (HITL) Exact Sequence" in content
    assert "System Backup & Restore Lifecycle" in content
    assert "Background Scheduled Worker Behavior" in content
    assert "Provider Setup & Configuration Guide" in content
    assert "Known Limitations & Development Scope" in content

def test_p8_2_architecture_doc_tables_specification():
    """P8 Item 3: Verifies docs/ARCHITECTURE.md documents core database tables."""
    arch_doc = BASE_DIR / "docs" / "ARCHITECTURE.md"
    content = arch_doc.read_text(encoding="utf-8")

    core_tables = [
        "episodes", "facts", "skills", "checkpoints", "approval_requests",
        "audit_logs", "tool_calls", "tool_results", "tasks", "sub_agents",
        "scheduled_jobs", "loop_events", "calendar_events", "emails",
        "whatsapp_messages", "telegram_messages"
    ]
    for table in core_tables:
        assert table in content
