"""One-time import of pre-cognee memory tables into the cognee dataset.

Reads the legacy ``facts``, ``structured_episodes``, ``episodes``, ``skills`` and
active ``skill_versions`` rows and enqueues them as ``cognee_ingest`` jobs, which
write straight into the main graph (no session, no Jev decision). It
never runs automatically and never deletes legacy rows. Re-running is safe:
ingest jobs are keyed by content hash, so identical batches are not re-queued.

Usage:
    python -m src.memory.cognee_backfill --dry-run
    python -m src.memory.cognee_backfill
"""

import argparse
import json
import sqlite3
from pathlib import Path
from typing import Any, Dict, Iterator, List, Optional

from src.db import get_connection

BACKFILL_SOURCE = "memory.legacy_backfill"
BATCH_SIZE = 20


def _tables(conn: sqlite3.Connection) -> set:
    rows = conn.execute("SELECT name FROM sqlite_master WHERE type IN ('table', 'view')").fetchall()
    return {row[0] for row in rows}


def _json_list(value: Any) -> List[str]:
    try:
        parsed = json.loads(value) if isinstance(value, str) else value
    except Exception:
        return []
    return [str(item) for item in parsed] if isinstance(parsed, list) else []


def _fact_documents(conn: sqlite3.Connection) -> Iterator[str]:
    for row in conn.execute("SELECT category, fact_text FROM facts"):
        text = str(row["fact_text"] or "").strip()
        if text:
            category = str(row["category"] or "general")
            yield f"Fact about the user ({category}): {text}"


def _structured_episode_documents(conn: sqlite3.Connection) -> Iterator[str]:
    query = "SELECT title, summary, decisions_json, topics_json, created_at FROM structured_episodes"
    for row in conn.execute(query):
        lines = [f"Past episode ({row['created_at']}): {row['title']}", str(row["summary"])]
        decisions = _json_list(row["decisions_json"])
        topics = _json_list(row["topics_json"])
        if decisions:
            lines.append("Decisions: " + "; ".join(decisions))
        if topics:
            lines.append("Topics: " + ", ".join(topics))
        yield "\n".join(lines)


def _legacy_episode_documents(conn: sqlite3.Connection) -> Iterator[str]:
    for row in conn.execute("SELECT timestamp, content FROM episodes"):
        content = str(row["content"] or "").strip()
        if content:
            yield f"Past conversation ({row['timestamp']}): {content}"


def _legacy_skill_documents(conn: sqlite3.Connection) -> Iterator[str]:
    for row in conn.execute("SELECT name, description, trigger_keywords, execution_steps FROM skills"):
        lines = [f"Procedure: {row['name']}", f"Purpose: {row['description'] or ''}"]
        if row["trigger_keywords"]:
            lines.append(f"Use when: {row['trigger_keywords']}")
        lines.append(f"Steps: {row['execution_steps'] or ''}")
        yield "\n".join(lines)


def _skill_version_documents(conn: sqlite3.Connection) -> Iterator[str]:
    query = (
        "SELECT name, description, file_path, workflow_json FROM skill_versions "
        "WHERE active = 1 AND enabled = 1 AND archived_at IS NULL"
    )
    for row in conn.execute(query):
        path = Path(str(row["file_path"]))
        body = ""
        try:
            if path.is_file():
                body = path.read_text(encoding="utf-8")
        except OSError:
            body = ""
        if not body:
            steps = _json_list(row["workflow_json"])
            body = f"Procedure: {row['name']}\nPurpose: {row['description']}\nSteps: " + "; ".join(steps)
        yield body.strip()


_SOURCES = (
    ("facts", _fact_documents),
    ("structured_episodes", _structured_episode_documents),
    ("episodes", _legacy_episode_documents),
    ("skills", _legacy_skill_documents),
    ("skill_versions", _skill_version_documents),
)


def collect_legacy_documents(db_path: Optional[Path] = None) -> Dict[str, List[str]]:
    conn = get_connection(db_path)
    conn.row_factory = sqlite3.Row
    try:
        present = _tables(conn)
        collected: Dict[str, List[str]] = {}
        for table, reader in _SOURCES:
            if table in present:
                collected[table] = list(reader(conn))
        return collected
    finally:
        conn.close()


def backfill_legacy_memory(db_path: Optional[Path] = None, *, dry_run: bool = False) -> Dict[str, Any]:
    from src.memory.jobs import SQLiteMemoryJobQueue, build_cognee_ingest_job_spec

    collected = collect_legacy_documents(db_path)
    documents = [document for docs in collected.values() for document in docs]
    report: Dict[str, Any] = {
        "dry_run": dry_run,
        "documents_by_table": {table: len(docs) for table, docs in collected.items()},
        "documents_total": len(documents),
        "jobs_queued": 0,
        "jobs_already_present": 0,
    }
    if dry_run or not documents:
        return report

    queue = SQLiteMemoryJobQueue()
    for start in range(0, len(documents), BATCH_SIZE):
        spec = build_cognee_ingest_job_spec(
            documents=documents[start : start + BATCH_SIZE],
            source=BACKFILL_SOURCE,
        )
        result = queue.enqueue_spec(spec)
        report["jobs_queued" if result.inserted else "jobs_already_present"] += 1
    return report


def main(argv: Optional[List[str]] = None) -> int:
    parser = argparse.ArgumentParser(description="Import legacy memory tables into cognee.")
    parser.add_argument("--dry-run", action="store_true", help="Count documents without queueing jobs.")
    args = parser.parse_args(argv)
    print(json.dumps(backfill_legacy_memory(dry_run=args.dry_run), indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
