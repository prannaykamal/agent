from pathlib import Path
from typing import Any, Dict, List, Optional

from src.db import get_connection
from src.memory.semantic_candidates import PendingFactCandidateStore, PendingFactCandidateWrite
from src.memory.semantic_store import (
    SemanticFactStore,
    SemanticFactValidationError,
    SemanticFactWrite,
)


def add_semantic_fact(
    category: str,
    fact_text: str,
    source: str = "user",
    confidence: float = 1.0,
    db_path: Optional[Path] = None,
    memory_path: Optional[Path] = None,
) -> None:
    """Store an explicit permanent semantic fact and sync MEMORY.md."""
    store = SemanticFactStore(db_path=db_path, memory_path=memory_path)
    store.add_explicit_fact(
        SemanticFactWrite(
            category=category,
            fact_text=fact_text,
            source=source,
            confidence=confidence,
            explicit=True,
        )
    )
    store.sync_memory_md()


def process_fact_candidates(
    session_id: str,
    candidates: List[Dict[str, Any]],
    db_path: Optional[Path] = None,
    memory_path: Optional[Path] = None,
) -> None:
    """
    Compatibility helper for legacy callers.

    Phase 7A routes candidates to the additive pending_fact_candidates table instead
    of promoting high-confidence inferred facts directly to permanent memory.
    """
    store = PendingFactCandidateStore(db_path=db_path)
    writes: List[PendingFactCandidateWrite] = []
    for candidate in candidates:
        fact = str(candidate.get("fact") or candidate.get("fact_text") or "").strip()
        if not fact:
            continue
        metadata = dict(candidate.get("metadata") or {})
        metadata.setdefault("compatibility_source", "process_fact_candidates")
        writes.append(
            PendingFactCandidateWrite(
                session_id=session_id,
                fact=fact,
                category=str(candidate.get("category") or "user_preference"),
                confidence=float(candidate.get("confidence", 0.8)),
                explicit=bool(candidate.get("explicit", False)),
                source=str(candidate.get("source") or "conversation"),
                source_message_id=candidate.get("source_message_id"),
                source_episode_id=candidate.get("source_episode_id"),
                batch_id=candidate.get("batch_id"),
                metadata=metadata,
            )
        )
    if writes:
        store.add_candidates(writes)


def get_pending_facts(db_path: Optional[Path] = None) -> List[Dict[str, Any]]:
    """Return pending legacy and Phase 7A candidate facts in the legacy dict shape."""
    conn = get_connection(db_path)
    try:
        legacy_rows = conn.execute(
            """
            SELECT id, session_id, category, fact_text, source, confidence, explicit, created_at
            FROM pending_facts
            ORDER BY created_at DESC
            """
        ).fetchall()
    finally:
        conn.close()

    rows = [dict(row) for row in legacy_rows]
    for record in PendingFactCandidateStore(db_path=db_path).list_pending(limit=1000):
        rows.append(
            {
                "id": record.id,
                "session_id": record.session_id,
                "category": record.category,
                "fact_text": record.fact,
                "source": record.source,
                "confidence": record.confidence,
                "explicit": 1 if record.explicit else 0,
                "created_at": record.created_at,
            }
        )
    return rows


def should_run_periodic_consolidation(db_path: Optional[Path] = None) -> bool:
    """Checks if total legacy episode count is a multiple of 10."""
    conn = get_connection(db_path)
    try:
        row = conn.execute("SELECT COUNT(*) as count FROM episodes").fetchone()
        total_episodes = row["count"] if row else 0
        return total_episodes > 0 and total_episodes % 10 == 0
    finally:
        conn.close()


def run_periodic_consolidation(
    provider: str = "openai",
    db_path: Optional[Path] = None,
    memory_path: Optional[Path] = None,
) -> Dict[str, Any]:
    """
    Legacy compatibility shim.

    Real semantic consolidation is out of scope for Phase 7A. This helper does
    not call an LLM and does not promote pending candidates to permanent facts.
    """
    conn = get_connection(db_path)
    try:
        conn.execute("DELETE FROM pending_facts")
        conn.execute(
            """
            UPDATE pending_fact_candidates
            SET status = 'DEFERRED', updated_at = datetime('now')
            WHERE status = 'PENDING'
            """
        )
        conn.commit()
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()

    sync_memory_md(db_path=db_path, memory_path=memory_path)
    return {"status": "success", "promoted_facts": 0}


def get_all_semantic_facts(db_path: Optional[Path] = None) -> List[Dict[str, Any]]:
    """Retrieves all permanent semantic facts from legacy SQLite FTS table `facts`."""
    return [record.to_dict() for record in SemanticFactStore(db_path=db_path).list_facts()]


def search_facts_top_k(
    query: str,
    k: int = 5,
    db_path: Optional[Path] = None,
) -> List[Dict[str, Any]]:
    """Performs Top-K keyword search over permanent semantic facts."""
    if not str(query or "").strip():
        return []
    return SemanticFactStore(db_path=db_path).search_facts(query=query, limit=k)


def sync_memory_md(
    db_path: Optional[Path] = None,
    memory_path: Optional[Path] = None,
) -> str:
    """Render permanent semantic facts from SQLite into MEMORY.md."""
    return SemanticFactStore(db_path=db_path, memory_path=memory_path).sync_memory_md()


def extract_and_save_facts(
    user_input: str,
    assistant_output: str,
    db_path: Optional[Path] = None,
    memory_path: Optional[Path] = None,
) -> None:
    """Legacy post-turn helper: deterministic explicit facts become pending candidates."""
    from src.memory.explicit_facts import extract_explicit_facts_from_user_text

    extracted = extract_explicit_facts_from_user_text(user_input)
    candidates = [
        {
            "fact": fact.fact_text,
            "confidence": fact.confidence,
            "category": fact.category,
            "source": fact.source,
            "explicit": True,
        }
        for fact in extracted
    ]
    if candidates:
        process_fact_candidates("default_session", candidates, db_path=db_path, memory_path=memory_path)


def persist_explicit_facts_from_user_text(
    user_text: str,
    db_path: Optional[Path] = None,
    memory_path: Optional[Path] = None,
) -> int:
    """Write deterministic explicit facts immediately via the dedup-aware store.

    Does not call an LLM. LLM-inferred facts still wait for background consolidation.
    """
    from src.memory.explicit_facts import extract_explicit_facts_from_user_text

    extracted = extract_explicit_facts_from_user_text(user_text)
    if not extracted:
        return 0
    store = SemanticFactStore(db_path=db_path, memory_path=memory_path)
    written = 0
    for fact in extracted:
        store.add_explicit_fact(fact)
        written += 1
    if written:
        store.sync_memory_md()
    return written


__all__ = [
    "SemanticFactValidationError",
    "add_semantic_fact",
    "process_fact_candidates",
    "get_pending_facts",
    "should_run_periodic_consolidation",
    "run_periodic_consolidation",
    "get_all_semantic_facts",
    "search_facts_top_k",
    "sync_memory_md",
    "extract_and_save_facts",
    "persist_explicit_facts_from_user_text",
]
