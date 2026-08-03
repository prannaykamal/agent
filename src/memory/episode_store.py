import json
import re
import uuid
from dataclasses import dataclass
from pathlib import Path
from typing import Any, List, Literal, Optional, Sequence

from src.db import get_connection


EpisodeAction = Literal["CREATE", "UPDATE", "MERGE", "SPLIT"]
VALID_EPISODE_ACTIONS = {"CREATE", "UPDATE", "MERGE", "SPLIT"}
JSON_ARRAY_FIELDS = ("participants", "goals", "decisions", "artifacts", "topics")


class StructuredEpisodeValidationError(ValueError):
    def __init__(self, field: str, message: str):
        self.field = field
        self.message = message
        super().__init__(f"{field}: {message}")


@dataclass(frozen=True)
class StructuredEpisodeWrite:
    session_id: str
    title: str
    summary: str
    participants: List[str]
    goals: List[str]
    decisions: List[str]
    artifacts: List[str]
    topics: List[str]
    importance: float
    start_message_id: str
    end_message_id: str
    source: str
    action: EpisodeAction = "CREATE"
    id: Optional[str] = None
    parent_episode_id: Optional[str] = None
    source_job_id: Optional[str] = None
    search_text: Optional[str] = None


@dataclass(frozen=True)
class StructuredEpisodeRecord:
    id: str
    session_id: str
    title: str
    summary: str
    participants: List[str]
    goals: List[str]
    decisions: List[str]
    artifacts: List[str]
    topics: List[str]
    importance: float
    start_message_id: str
    end_message_id: str
    source: str
    action: EpisodeAction
    parent_episode_id: Optional[str]
    source_job_id: Optional[str]
    search_text: str
    created_at: str
    updated_at: Optional[str]


def _normalize_whitespace(value: str) -> str:
    return re.sub(r"\s+", " ", value).strip()


def _require_non_empty_string(value: Any, field: str) -> str:
    if not isinstance(value, str):
        raise StructuredEpisodeValidationError(field, "must be a string")
    normalized = _normalize_whitespace(value)
    if not normalized:
        raise StructuredEpisodeValidationError(field, "must be non-empty")
    return normalized


def _normalize_optional_string(value: Optional[str], field: str) -> Optional[str]:
    if value is None:
        return None
    if not isinstance(value, str):
        raise StructuredEpisodeValidationError(field, "must be a string")
    normalized = _normalize_whitespace(value)
    return normalized or None


def normalize_string_list(values: Any, field: str, *, require_non_empty: bool = False) -> List[str]:
    if not isinstance(values, list):
        raise StructuredEpisodeValidationError(field, "must be a list of strings")

    normalized: List[str] = []
    for index, value in enumerate(values):
        if not isinstance(value, str):
            raise StructuredEpisodeValidationError(field, f"item {index} must be a string")
        item = _normalize_whitespace(value)
        if item:
            normalized.append(item)

    if require_non_empty and not normalized:
        raise StructuredEpisodeValidationError(field, "must contain at least one non-empty string")
    return normalized


def canonical_json_array(values: Sequence[str]) -> str:
    return json.dumps(list(values), ensure_ascii=False, sort_keys=True, separators=(",", ":"))


def parse_json_array(value: str, field: str) -> List[str]:
    try:
        parsed = json.loads(value)
    except Exception as exc:
        raise StructuredEpisodeValidationError(field, "must be valid JSON") from exc
    return normalize_string_list(parsed, field)


def build_structured_episode_search_text(episode: StructuredEpisodeWrite) -> str:
    validated = validate_structured_episode_write(episode)
    lines = [
        f"Title: {validated.title}",
        f"Summary: {validated.summary}",
        f"Participants: {', '.join(validated.participants)}",
    ]
    if validated.goals:
        lines.append(f"Goals: {'; '.join(validated.goals)}")
    if validated.decisions:
        lines.append(f"Decisions: {'; '.join(validated.decisions)}")
    if validated.artifacts:
        lines.append(f"Artifacts: {'; '.join(validated.artifacts)}")
    lines.append(f"Topics: {', '.join(validated.topics)}")
    lines.append(f"Action: {validated.action}")
    lines.append(f"Source: {validated.source}")
    return "\n".join(lines)


def validate_structured_episode_write(episode: StructuredEpisodeWrite) -> StructuredEpisodeWrite:
    try:
        importance = float(episode.importance)
    except (TypeError, ValueError) as exc:
        raise StructuredEpisodeValidationError("importance", "must be a number") from exc
    if importance < 0 or importance > 1:
        raise StructuredEpisodeValidationError("importance", "must be between 0 and 1")

    action = _require_non_empty_string(episode.action, "action")
    if action not in VALID_EPISODE_ACTIONS:
        raise StructuredEpisodeValidationError("action", "must be CREATE, UPDATE, MERGE, or SPLIT")

    return StructuredEpisodeWrite(
        id=_normalize_optional_string(episode.id, "id"),
        session_id=_require_non_empty_string(episode.session_id, "session_id"),
        title=_require_non_empty_string(episode.title, "title"),
        summary=_require_non_empty_string(episode.summary, "summary"),
        participants=normalize_string_list(episode.participants, "participants", require_non_empty=True),
        goals=normalize_string_list(episode.goals, "goals"),
        decisions=normalize_string_list(episode.decisions, "decisions"),
        artifacts=normalize_string_list(episode.artifacts, "artifacts"),
        topics=normalize_string_list(episode.topics, "topics", require_non_empty=True),
        importance=importance,
        start_message_id=_require_non_empty_string(episode.start_message_id, "start_message_id"),
        end_message_id=_require_non_empty_string(episode.end_message_id, "end_message_id"),
        source=_require_non_empty_string(episode.source, "source"),
        action=action,  # type: ignore[arg-type]
        parent_episode_id=_normalize_optional_string(episode.parent_episode_id, "parent_episode_id"),
        source_job_id=_normalize_optional_string(episode.source_job_id, "source_job_id"),
        search_text=_normalize_optional_string(episode.search_text, "search_text"),
    )


class StructuredEpisodeRepository:
    def __init__(self, db_path: Optional[Path] = None):
        self.db_path = db_path

    def append_episode(self, episode: StructuredEpisodeWrite) -> StructuredEpisodeRecord:
        validated = validate_structured_episode_write(episode)
        if validated.source_job_id:
            existing = self.get_by_source_job_id(validated.source_job_id)
            if existing is not None:
                return existing

        episode_id = validated.id or f"structured_episode_{uuid.uuid4().hex}"
        search_text = validated.search_text or build_structured_episode_search_text(validated)

        conn = get_connection(self.db_path)
        try:
            conn.execute(
                """
                INSERT INTO structured_episodes (
                    id, session_id, title, summary, participants_json, goals_json,
                    decisions_json, artifacts_json, topics_json, importance,
                    start_message_id, end_message_id, source, action,
                    parent_episode_id, source_job_id, search_text
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    episode_id,
                    validated.session_id,
                    validated.title,
                    validated.summary,
                    canonical_json_array(validated.participants),
                    canonical_json_array(validated.goals),
                    canonical_json_array(validated.decisions),
                    canonical_json_array(validated.artifacts),
                    canonical_json_array(validated.topics),
                    validated.importance,
                    validated.start_message_id,
                    validated.end_message_id,
                    validated.source,
                    validated.action,
                    validated.parent_episode_id,
                    validated.source_job_id,
                    search_text,
                ),
            )
            conn.commit()
        except Exception:
            conn.rollback()
            raise
        finally:
            conn.close()

        record = self.get_by_id(episode_id)
        if record is None:
            raise RuntimeError("Structured episode insert succeeded but record could not be read")
        return record

    def get_by_id(self, episode_id: str) -> Optional[StructuredEpisodeRecord]:
        conn = get_connection(self.db_path)
        try:
            row = conn.execute(
                "SELECT * FROM structured_episodes WHERE id = ?",
                (episode_id,),
            ).fetchone()
            return _row_to_record(row) if row is not None else None
        finally:
            conn.close()

    def get_by_source_job_id(self, source_job_id: str) -> Optional[StructuredEpisodeRecord]:
        normalized = _require_non_empty_string(source_job_id, "source_job_id")
        conn = get_connection(self.db_path)
        try:
            row = conn.execute(
                """
                SELECT * FROM structured_episodes
                WHERE source_job_id = ?
                ORDER BY created_at ASC, id ASC
                LIMIT 1
                """,
                (normalized,),
            ).fetchone()
            return _row_to_record(row) if row is not None else None
        finally:
            conn.close()

    def list_by_session(
        self,
        session_id: str,
        *,
        limit: Optional[int] = None,
        newest_first: bool = False,
    ) -> List[StructuredEpisodeRecord]:
        normalized_session_id = _require_non_empty_string(session_id, "session_id")
        if limit is not None and limit <= 0:
            raise ValueError("limit must be positive")

        order = "DESC" if newest_first else "ASC"
        sql = (
            "SELECT * FROM structured_episodes WHERE session_id = ? "
            f"ORDER BY created_at {order}, id {order}"
        )
        params: list[Any] = [normalized_session_id]
        if limit is not None:
            sql += " LIMIT ?"
            params.append(limit)

        conn = get_connection(self.db_path)
        try:
            rows = conn.execute(sql, tuple(params)).fetchall()
            return [_row_to_record(row) for row in rows]
        finally:
            conn.close()

    def search_text(
        self,
        query: str,
        *,
        session_id: Optional[str] = None,
        limit: int = 10,
    ) -> List[StructuredEpisodeRecord]:
        normalized_query = _normalize_whitespace(query)
        if not normalized_query:
            return []
        if limit <= 0:
            raise ValueError("limit must be positive")
        capped_limit = min(limit, 100)

        like_query = f"%{normalized_query}%"
        params: list[Any] = [like_query, like_query, like_query]
        session_clause = ""
        if session_id is not None:
            session_clause = " AND session_id = ?"
            params.append(_require_non_empty_string(session_id, "session_id"))
        params.append(capped_limit)

        conn = get_connection(self.db_path)
        try:
            rows = conn.execute(
                f"""
                SELECT * FROM structured_episodes
                WHERE (search_text LIKE ? OR title LIKE ? OR summary LIKE ?){session_clause}
                ORDER BY importance DESC, created_at DESC, id DESC
                LIMIT ?
                """,
                tuple(params),
            ).fetchall()
            return [_row_to_record(row) for row in rows]
        finally:
            conn.close()

    def count_by_session(self, session_id: str) -> int:
        normalized_session_id = _require_non_empty_string(session_id, "session_id")
        conn = get_connection(self.db_path)
        try:
            row = conn.execute(
                "SELECT COUNT(*) FROM structured_episodes WHERE session_id = ?",
                (normalized_session_id,),
            ).fetchone()
            return int(row[0])
        finally:
            conn.close()

    def to_legacy_episode_dict(self, episode: StructuredEpisodeRecord) -> dict[str, Any]:
        structured_fields = {
            "title": episode.title,
            "summary": episode.summary,
            "participants": episode.participants,
            "goals": episode.goals,
            "decisions": episode.decisions,
            "artifacts": episode.artifacts,
            "topics": episode.topics,
            "importance": episode.importance,
            "action": episode.action,
            "parent_episode_id": episode.parent_episode_id,
            "source_job_id": episode.source_job_id,
        }
        return {
            "id": episode.id,
            "session_id": episode.session_id,
            "timestamp": episode.created_at,
            "content": episode.search_text,
            "tool_calls": json.dumps(structured_fields, ensure_ascii=False, sort_keys=True, separators=(",", ":")),
            "outcome": "success",
        }


def _row_to_record(row: Any) -> StructuredEpisodeRecord:
    return StructuredEpisodeRecord(
        id=str(row["id"]),
        session_id=str(row["session_id"]),
        title=str(row["title"]),
        summary=str(row["summary"]),
        participants=parse_json_array(row["participants_json"], "participants_json"),
        goals=parse_json_array(row["goals_json"], "goals_json"),
        decisions=parse_json_array(row["decisions_json"], "decisions_json"),
        artifacts=parse_json_array(row["artifacts_json"], "artifacts_json"),
        topics=parse_json_array(row["topics_json"], "topics_json"),
        importance=float(row["importance"]),
        start_message_id=str(row["start_message_id"]),
        end_message_id=str(row["end_message_id"]),
        source=str(row["source"]),
        action=str(row["action"]),  # type: ignore[arg-type]
        parent_episode_id=row["parent_episode_id"],
        source_job_id=row["source_job_id"],
        search_text=str(row["search_text"] or ""),
        created_at=str(row["created_at"]),
        updated_at=row["updated_at"],
    )

