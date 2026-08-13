"""Write-path entity index for durable semantic facts.

Retrieval may look entities up; it must not insert, update, or rebuild.
"""

from __future__ import annotations

import re
import sqlite3
from pathlib import Path
from typing import List, Optional, Sequence, Tuple

from src.db import get_connection
from src.memory.retrieval_ranker import STOP_WORDS, tokenize_retrieval_text


EMAIL_RE = re.compile(r"[A-Za-z0-9._%+\-]+@[A-Za-z0-9.\-]+\.[A-Za-z]{2,}")
NAME_RE = re.compile(r"\b([A-Z][a-zA-Z0-9.\-]{1,40}(?:\s+[A-Z][a-zA-Z0-9.\-]{1,40}){0,2})\b")
KIND_EMAIL = "email"
KIND_NAME = "name"
KIND_TOKEN = "token"
LEADING_NAME_SKIP = STOP_WORDS | {
    "send",
    "draft",
    "please",
    "remember",
    "forget",
    "tell",
    "ask",
    "create",
    "schedule",
    "search",
    "find",
    "look",
    "email",
    "mail",
    "text",
    "message",
    "call",
    "remind",
    "what",
    "who",
    "when",
    "where",
    "why",
    "how",
    "which",
    "hello",
    "thanks",
    "thank",
    "user",
}


def _normalize_entity(value: str) -> str:
    return " ".join(str(value or "").lower().split())


def extract_emails(text: str) -> Tuple[str, ...]:
    seen = set()
    emails = []
    for match in EMAIL_RE.findall(str(text or "")):
        normalized = _normalize_entity(match)
        if normalized and normalized not in seen:
            seen.add(normalized)
            emails.append(normalized)
    return tuple(emails)


def _leading_name_candidate(text: str) -> Optional[str]:
    first = re.split(r"\s+", str(text or "").strip(), maxsplit=1)[0]
    first = re.sub(r"['’]s$", "", first.strip("\"'.,:;!?"))
    normalized = _normalize_entity(first)
    if len(normalized) < 4:
        return None
    if normalized in LEADING_NAME_SKIP:
        return None
    return normalized


def extract_proper_names(text: str) -> Tuple[str, ...]:
    """Names including a leading proper name; skip only closed function words."""
    raw = str(text or "").strip()
    if not raw:
        return tuple()
    seen = set()
    names = []
    leading = _leading_name_candidate(raw)
    if leading:
        seen.add(leading)
        names.append(leading)
    for match in NAME_RE.finditer(raw):
        value = match.group(1)
        if value.lower() in LEADING_NAME_SKIP:
            continue
        normalized = _normalize_entity(value)
        if len(normalized) < 4 or normalized in seen:
            continue
        seen.add(normalized)
        names.append(normalized)
    return tuple(names)


def extract_fact_entities(text: str) -> Tuple[Tuple[str, str], ...]:
    """Entities stored for a permanent fact: emails, names, distinctive tokens."""
    seen = set()
    entities: List[Tuple[str, str]] = []
    for email in extract_emails(text):
        key = (email, KIND_EMAIL)
        if key not in seen:
            seen.add(key)
            entities.append(key)
    for name in extract_proper_names(text):
        key = (name, KIND_NAME)
        if key not in seen:
            seen.add(key)
            entities.append(key)
        for token in name.split():
            if len(token) >= 4 and token not in STOP_WORDS:
                token_key = (token, KIND_TOKEN)
                if token_key not in seen:
                    seen.add(token_key)
                    entities.append(token_key)
    for token in tokenize_retrieval_text(text):
        if len(token) < 4:
            continue
        key = (token, KIND_TOKEN)
        if key not in seen:
            seen.add(key)
            entities.append(key)
    return tuple(entities)


def extract_query_entities(text: str) -> Tuple[str, ...]:
    """Query-side lookup keys: emails, mid-sentence names, distinctive tokens."""
    seen = set()
    values = []
    for email in extract_emails(text):
        if email not in seen:
            seen.add(email)
            values.append(email)
    for name in extract_proper_names(text):
        if name not in seen:
            seen.add(name)
            values.append(name)
        for token in name.split():
            if len(token) >= 4 and token not in seen:
                seen.add(token)
                values.append(token)
    for token in tokenize_retrieval_text(text):
        if len(token) < 4 or token in seen:
            continue
        seen.add(token)
        values.append(token)
    return tuple(values)


class EntityIndexStore:
    def __init__(self, db_path: Optional[Path] = None):
        self.db_path = db_path

    def index_fact(self, fact_rowid: int, fact_text: str, *, conn: Optional[sqlite3.Connection] = None) -> int:
        rowid = int(fact_rowid)
        entities = extract_fact_entities(fact_text)
        owns_conn = conn is None
        active = conn if conn is not None else get_connection(self.db_path)
        try:
            active.execute("DELETE FROM memory_entities WHERE fact_rowid = ?", (rowid,))
            for entity_norm, kind in entities:
                active.execute(
                    """
                    INSERT OR IGNORE INTO memory_entities (entity_norm, fact_rowid, kind)
                    VALUES (?, ?, ?)
                    """,
                    (entity_norm, rowid, kind),
                )
            if owns_conn:
                active.commit()
            return len(entities)
        except Exception:
            if owns_conn:
                active.rollback()
            raise
        finally:
            if owns_conn:
                active.close()

    def delete_fact(self, fact_rowid: int, *, conn: Optional[sqlite3.Connection] = None) -> None:
        owns_conn = conn is None
        active = conn if conn is not None else get_connection(self.db_path)
        try:
            active.execute("DELETE FROM memory_entities WHERE fact_rowid = ?", (int(fact_rowid),))
            if owns_conn:
                active.commit()
        except Exception:
            if owns_conn:
                active.rollback()
            raise
        finally:
            if owns_conn:
                active.close()

    def lookup_fact_ids(self, entities: Sequence[str], *, limit: int = 40) -> List[int]:
        keys = [_normalize_entity(value) for value in entities if _normalize_entity(value)]
        if not keys or limit <= 0:
            return []
        placeholders = ",".join("?" for _ in keys)
        conn = get_connection(self.db_path)
        try:
            rows = conn.execute(
                f"""
                SELECT fact_rowid, COUNT(*) AS hits
                FROM memory_entities
                WHERE entity_norm IN ({placeholders})
                GROUP BY fact_rowid
                ORDER BY hits DESC, fact_rowid DESC
                LIMIT ?
                """,
                tuple(keys) + (int(limit),),
            ).fetchall()
            return [int(row["fact_rowid"]) for row in rows]
        except sqlite3.OperationalError:
            return []
        finally:
            conn.close()

    def query_hits_index(self, query: str) -> bool:
        entities = extract_query_entities(query)
        if not entities:
            return False
        return bool(self.lookup_fact_ids(entities, limit=1))

    def rebuild(self, *, conn: Optional[sqlite3.Connection] = None) -> int:
        owns_conn = conn is None
        active = conn if conn is not None else get_connection(self.db_path)
        try:
            active.execute("DELETE FROM memory_entities")
            rows = active.execute("SELECT rowid AS id, fact_text FROM facts").fetchall()
            count = 0
            for row in rows:
                if isinstance(row, sqlite3.Row):
                    fact_id = int(row["id"])
                    fact_text = str(row["fact_text"])
                else:
                    fact_id = int(row[0])
                    fact_text = str(row[1])
                count += self.index_fact(fact_id, fact_text, conn=active)
            if owns_conn:
                active.commit()
            return count
        except sqlite3.OperationalError:
            if owns_conn:
                active.rollback()
            return 0
        except Exception:
            if owns_conn:
                active.rollback()
            raise
        finally:
            if owns_conn:
                active.close()


def index_semantic_fact(fact_rowid: int, fact_text: str, db_path: Optional[Path] = None) -> int:
    return EntityIndexStore(db_path=db_path).index_fact(fact_rowid, fact_text)


def delete_semantic_fact_entities(fact_rowid: int, db_path: Optional[Path] = None) -> None:
    EntityIndexStore(db_path=db_path).delete_fact(fact_rowid)


def lookup_facts_for_query(query: str, *, db_path: Optional[Path] = None, limit: int = 40) -> List[int]:
    store = EntityIndexStore(db_path=db_path)
    return store.lookup_fact_ids(extract_query_entities(query), limit=limit)


def query_hits_entity_index(query: str, *, db_path: Optional[Path] = None) -> bool:
    return EntityIndexStore(db_path=db_path).query_hits_index(query)
