import json
import sqlite3
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Dict, List, Mapping, Optional, Sequence

from src.db import get_connection
from src.memory.skill_files import (
    SkillFileFrontmatter,
    SkillFileValidationError,
    generated_skill_file_path,
    render_skill_markdown,
    slugify_skill_id,
    validate_generated_skill_path,
    write_immutable_skill_file,
)


@dataclass(frozen=True)
class SkillVersionWrite:
    name: str
    description: str
    trigger_keywords: Sequence[str] | str
    execution_steps: str
    preferred_tools: Sequence[str] = field(default_factory=list)
    tags: Sequence[str] = field(default_factory=list)
    skill_id: Optional[str] = None
    candidate_id: Optional[str] = None
    author: str = "api"
    approval_required: bool = False
    approval_id: Optional[str] = None
    confidence: Optional[float] = None
    enabled: bool = True
    activate: bool = True


@dataclass(frozen=True)
class SkillVersionRecord:
    id: str
    skill_id: str
    candidate_id: Optional[str]
    version: int
    name: str
    description: str
    file_path: str
    content_hash: str
    frontmatter: Dict[str, Any]
    workflow: Dict[str, Any]
    preferred_tools: List[str]
    tags: List[str]
    enabled: bool
    active: bool
    author: str
    approval_required: bool
    approval_id: Optional[str]
    confidence: Optional[float]
    created_at: str
    updated_at: str
    approved_at: Optional[str]
    archived_at: Optional[str]

    def to_legacy_dict(self) -> Dict[str, Any]:
        return {
            "id": self.id,
            "name": self.name,
            "description": self.description,
            "trigger_keywords": ", ".join(self.frontmatter.get("trigger_keywords", [])),
            "execution_steps": str(self.workflow.get("execution_steps") or ""),
            "skill_id": self.skill_id,
            "version_id": self.id,
            "version": self.version,
            "active": self.active,
            "enabled": self.enabled,
            "file_path": self.file_path,
            "content_hash": self.content_hash,
            "author": self.author,
        }


@dataclass(frozen=True)
class SkillUsageStatsRecord:
    skill_id: str
    active_version_id: Optional[str]
    times_loaded: int
    times_used: int
    last_loaded: Optional[str]
    last_used: Optional[str]
    last_updated: str
    created_at: str


def _canonical_json(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))


def _parse_json(value: Any, default: Any) -> Any:
    if value is None or value == "":
        return default
    try:
        return json.loads(str(value))
    except Exception:
        return default


def _normalize_non_empty(value: Any, field: str) -> str:
    normalized = " ".join(str(value or "").split())
    if not normalized:
        raise SkillFileValidationError(field, "must be non-empty")
    return normalized


def _normalize_keywords(value: Sequence[str] | str) -> List[str]:
    if isinstance(value, str):
        items = value.split(",")
    else:
        items = [str(item) for item in value]
    return [item.strip() for item in items if item.strip()]


def _version_id(skill_id: str, version: int) -> str:
    return f"skillver_{skill_id}_v{int(version):04d}"


class SkillVersionStore:
    def __init__(self, db_path: Optional[Path] = None, skill_path: Optional[Path] = None):
        self.db_path = db_path
        self.skill_path = skill_path

    def create_version(self, write: SkillVersionWrite) -> SkillVersionRecord:
        name = _normalize_non_empty(write.name, "name")
        description = _normalize_non_empty(write.description, "description")
        execution_steps = _normalize_non_empty(write.execution_steps, "execution_steps")
        keywords = _normalize_keywords(write.trigger_keywords)
        if not keywords:
            raise SkillFileValidationError("trigger_keywords", "must contain at least one keyword")
        skill_id = slugify_skill_id(write.skill_id or name)
        version = self._next_version(skill_id)
        version_id = _version_id(skill_id, version)
        target_path = generated_skill_file_path(skill_id, version, self.skill_path)
        validate_generated_skill_path(target_path, self.skill_path)

        frontmatter = SkillFileFrontmatter(
            schema_version=1,
            skill_id=skill_id,
            version=version,
            name=name,
            description=description,
            author=_normalize_non_empty(write.author, "author"),
            namespace="generated",
            enabled=bool(write.enabled),
            active=bool(write.activate),
            created_at="1970-01-01T00:00:00Z",
            content_hash="pending",
            trigger_keywords=keywords,
            preferred_tools=[str(tool).strip() for tool in write.preferred_tools if str(tool).strip()],
            tags=[str(tag).strip() for tag in write.tags if str(tag).strip()],
            approval_required=bool(write.approval_required),
            approval_id=write.approval_id,
            candidate_id=write.candidate_id,
            confidence=write.confidence,
        )
        content = render_skill_markdown(frontmatter, execution_steps)
        write_immutable_skill_file(target_path, content, self.skill_path)
        parsed_frontmatter, _ = __import__(
            "src.memory.skill_files",
            fromlist=["parse_skill_markdown"],
        ).parse_skill_markdown(content)

        workflow = {"execution_steps": execution_steps}
        conn = get_connection(self.db_path)
        try:
            cursor = conn.cursor()
            cursor.execute(
                """
                INSERT INTO skill_versions (
                    id, skill_id, candidate_id, version, name, description, file_path,
                    content_hash, frontmatter_json, workflow_json, preferred_tools_json,
                    tags_json, enabled, active, author, approval_required, approval_id,
                    confidence, created_at, updated_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 0, ?, ?, ?, ?, datetime('now'), datetime('now'))
                """,
                (
                    version_id,
                    skill_id,
                    write.candidate_id,
                    version,
                    name,
                    description,
                    str(target_path),
                    parsed_frontmatter.content_hash,
                    _canonical_json(parsed_frontmatter.to_dict()),
                    _canonical_json(workflow),
                    _canonical_json(parsed_frontmatter.preferred_tools),
                    _canonical_json(parsed_frontmatter.tags),
                    1 if write.enabled else 0,
                    parsed_frontmatter.author,
                    1 if write.approval_required else 0,
                    write.approval_id,
                    write.confidence,
                ),
            )
            if write.activate and write.enabled:
                cursor.execute("UPDATE skill_versions SET active = 0, updated_at = datetime('now') WHERE skill_id = ?", (skill_id,))
                cursor.execute("UPDATE skill_versions SET active = 1, updated_at = datetime('now') WHERE id = ?", (version_id,))
                self._upsert_usage_stats(cursor, skill_id, version_id)
            else:
                self._upsert_usage_stats(cursor, skill_id, None)
            conn.commit()
        except Exception:
            conn.rollback()
            raise
        finally:
            conn.close()

        record = self.get_version(version_id)
        if record is None:
            raise RuntimeError("Inserted skill version could not be read back")
        if record.active:
            self._sync_legacy_row(record)
        return record

    def get_version(self, version_id: str) -> Optional[SkillVersionRecord]:
        conn = get_connection(self.db_path)
        try:
            row = conn.execute("SELECT * FROM skill_versions WHERE id = ?", (version_id,)).fetchone()
            return self._row_to_record(row) if row is not None else None
        finally:
            conn.close()

    def get_active_version(self, skill_id: str) -> Optional[SkillVersionRecord]:
        normalized_skill_id = slugify_skill_id(skill_id)
        conn = get_connection(self.db_path)
        try:
            row = conn.execute(
                """
                SELECT * FROM skill_versions
                WHERE skill_id = ? AND active = 1 AND enabled = 1
                ORDER BY version DESC
                LIMIT 1
                """,
                (normalized_skill_id,),
            ).fetchone()
            return self._row_to_record(row) if row is not None else None
        finally:
            conn.close()

    def list_active_versions(self, include_disabled: bool = False) -> List[SkillVersionRecord]:
        clause = "active = 1" if include_disabled else "active = 1 AND enabled = 1"
        conn = get_connection(self.db_path)
        try:
            rows = conn.execute(
                f"SELECT * FROM skill_versions WHERE {clause} ORDER BY name ASC, version DESC"
            ).fetchall()
            return [self._row_to_record(row) for row in rows]
        finally:
            conn.close()

    def list_versions(self, skill_id: str) -> List[SkillVersionRecord]:
        normalized_skill_id = slugify_skill_id(skill_id)
        conn = get_connection(self.db_path)
        try:
            rows = conn.execute(
                """
                SELECT * FROM skill_versions
                WHERE skill_id = ?
                ORDER BY version ASC
                """,
                (normalized_skill_id,),
            ).fetchall()
            return [self._row_to_record(row) for row in rows]
        finally:
            conn.close()

    def rollback_to_version(self, skill_id: str, version: int) -> SkillVersionRecord:
        normalized_skill_id = slugify_skill_id(skill_id)
        target = self._get_by_skill_and_version(normalized_skill_id, int(version))
        if target is None:
            raise SkillFileValidationError("version", "skill version does not exist")
        if not target.enabled or target.archived_at is not None:
            raise SkillFileValidationError("version", "cannot activate disabled or archived version")
        conn = get_connection(self.db_path)
        try:
            cursor = conn.cursor()
            cursor.execute("UPDATE skill_versions SET active = 0, updated_at = datetime('now') WHERE skill_id = ?", (normalized_skill_id,))
            cursor.execute("UPDATE skill_versions SET active = 1, updated_at = datetime('now') WHERE id = ?", (target.id,))
            self._upsert_usage_stats(cursor, normalized_skill_id, target.id)
            conn.commit()
        except Exception:
            conn.rollback()
            raise
        finally:
            conn.close()
        record = self.get_version(target.id)
        if record is None:
            raise RuntimeError("Rolled back skill version could not be read")
        self._sync_legacy_row(record)
        return record

    def disable_skill(self, skill_id: str, reason: Optional[str] = None) -> Optional[SkillVersionRecord]:
        normalized_skill_id = slugify_skill_id(skill_id)
        active = self.get_active_version(normalized_skill_id)
        if active is None:
            active = self._get_active_by_name(skill_id)
        if active is None:
            return None
        record = self.archive_version(active.id, reason=reason)
        self._delete_legacy_row(record.name)
        return record

    def archive_version(self, version_id: str, reason: Optional[str] = None) -> SkillVersionRecord:
        existing = self.get_version(version_id)
        if existing is None:
            raise SkillFileValidationError("version_id", "skill version does not exist")
        metadata = dict(existing.frontmatter)
        if reason:
            metadata["archive_reason"] = reason
        conn = get_connection(self.db_path)
        try:
            cursor = conn.cursor()
            cursor.execute(
                """
                UPDATE skill_versions
                SET enabled = 0,
                    active = 0,
                    archived_at = datetime('now'),
                    frontmatter_json = ?,
                    updated_at = datetime('now')
                WHERE id = ?
                """,
                (_canonical_json(metadata), version_id),
            )
            self._upsert_usage_stats(cursor, existing.skill_id, None)
            conn.commit()
        except Exception:
            conn.rollback()
            raise
        finally:
            conn.close()
        record = self.get_version(version_id)
        if record is None:
            raise RuntimeError("Archived skill version could not be read")
        return record

    def record_loaded(self, skill_id: str, version_id: str) -> SkillUsageStatsRecord:
        return self._increment_usage(skill_id, version_id, "times_loaded", "last_loaded")

    def record_used(self, skill_id: str, version_id: str) -> SkillUsageStatsRecord:
        return self._increment_usage(skill_id, version_id, "times_used", "last_used")

    def list_legacy_compatible_skills(self) -> List[Dict[str, Any]]:
        active = [record.to_legacy_dict() for record in self.list_active_versions()]
        active_names = {str(skill["name"]).lower() for skill in active}
        conn = get_connection(self.db_path)
        try:
            legacy_rows = conn.execute(
                "SELECT id, name, description, trigger_keywords, execution_steps FROM skills ORDER BY name ASC"
            ).fetchall()
        finally:
            conn.close()
        for row in legacy_rows:
            row_dict = dict(row)
            if str(row_dict.get("name", "")).lower() not in active_names:
                active.append(row_dict)
        return sorted(active, key=lambda item: str(item.get("name", "")).lower())

    def _next_version(self, skill_id: str) -> int:
        conn = get_connection(self.db_path)
        try:
            row = conn.execute(
                "SELECT MAX(version) FROM skill_versions WHERE skill_id = ?",
                (skill_id,),
            ).fetchone()
            db_version = int(row[0] or 0)
        finally:
            conn.close()

        version = db_version + 1
        while generated_skill_file_path(skill_id, version, self.skill_path).exists():
            version += 1
        return version

    def _get_by_skill_and_version(self, skill_id: str, version: int) -> Optional[SkillVersionRecord]:
        conn = get_connection(self.db_path)
        try:
            row = conn.execute(
                "SELECT * FROM skill_versions WHERE skill_id = ? AND version = ?",
                (skill_id, int(version)),
            ).fetchone()
            return self._row_to_record(row) if row is not None else None
        finally:
            conn.close()

    def _get_active_by_name(self, name: str) -> Optional[SkillVersionRecord]:
        conn = get_connection(self.db_path)
        try:
            row = conn.execute(
                """
                SELECT * FROM skill_versions
                WHERE lower(name) = lower(?) AND active = 1 AND enabled = 1
                ORDER BY version DESC
                LIMIT 1
                """,
                (name,),
            ).fetchone()
            return self._row_to_record(row) if row is not None else None
        finally:
            conn.close()

    @staticmethod
    def _upsert_usage_stats(cursor: sqlite3.Cursor, skill_id: str, active_version_id: Optional[str]) -> None:
        cursor.execute(
            """
            INSERT INTO skill_usage_stats (
                skill_id, active_version_id, times_loaded, times_used, last_updated, created_at
            ) VALUES (?, ?, 0, 0, datetime('now'), datetime('now'))
            ON CONFLICT(skill_id) DO UPDATE SET
                active_version_id = excluded.active_version_id,
                last_updated = datetime('now')
            """,
            (skill_id, active_version_id),
        )

    def _increment_usage(self, skill_id: str, version_id: str, count_column: str, time_column: str) -> SkillUsageStatsRecord:
        normalized_skill_id = slugify_skill_id(skill_id)
        if count_column not in {"times_loaded", "times_used"} or time_column not in {"last_loaded", "last_used"}:
            raise ValueError("invalid usage stat column")
        conn = get_connection(self.db_path)
        try:
            cursor = conn.cursor()
            self._upsert_usage_stats(cursor, normalized_skill_id, version_id)
            cursor.execute(
                f"""
                UPDATE skill_usage_stats
                SET {count_column} = {count_column} + 1,
                    {time_column} = datetime('now'),
                    last_updated = datetime('now'),
                    active_version_id = ?
                WHERE skill_id = ?
                """,
                (version_id, normalized_skill_id),
            )
            conn.commit()
        except Exception:
            conn.rollback()
            raise
        finally:
            conn.close()
        return self._get_usage_stats(normalized_skill_id)

    def _get_usage_stats(self, skill_id: str) -> SkillUsageStatsRecord:
        conn = get_connection(self.db_path)
        try:
            row = conn.execute("SELECT * FROM skill_usage_stats WHERE skill_id = ?", (skill_id,)).fetchone()
            if row is None:
                raise RuntimeError("usage stats row does not exist")
            return SkillUsageStatsRecord(
                skill_id=str(row["skill_id"]),
                active_version_id=row["active_version_id"],
                times_loaded=int(row["times_loaded"]),
                times_used=int(row["times_used"]),
                last_loaded=row["last_loaded"],
                last_used=row["last_used"],
                last_updated=str(row["last_updated"]),
                created_at=str(row["created_at"]),
            )
        finally:
            conn.close()

    def _sync_legacy_row(self, record: SkillVersionRecord) -> None:
        conn = get_connection(self.db_path)
        try:
            conn.execute(
                """
                INSERT OR REPLACE INTO skills (name, description, trigger_keywords, execution_steps)
                VALUES (?, ?, ?, ?)
                """,
                (
                    record.name,
                    record.description,
                    ", ".join(record.frontmatter.get("trigger_keywords", [])),
                    str(record.workflow.get("execution_steps") or ""),
                ),
            )
            conn.commit()
        except Exception:
            conn.rollback()
            raise
        finally:
            conn.close()

    def _delete_legacy_row(self, name: str) -> None:
        conn = get_connection(self.db_path)
        try:
            conn.execute("DELETE FROM skills WHERE name = ?", (name,))
            conn.commit()
        except Exception:
            conn.rollback()
            raise
        finally:
            conn.close()

    @staticmethod
    def _row_to_record(row: Any) -> SkillVersionRecord:
        frontmatter = _parse_json(row["frontmatter_json"], {})
        workflow = _parse_json(row["workflow_json"], {})
        preferred_tools = _parse_json(row["preferred_tools_json"], [])
        tags = _parse_json(row["tags_json"], [])
        return SkillVersionRecord(
            id=str(row["id"]),
            skill_id=str(row["skill_id"]),
            candidate_id=row["candidate_id"],
            version=int(row["version"]),
            name=str(row["name"]),
            description=str(row["description"]),
            file_path=str(row["file_path"]),
            content_hash=str(row["content_hash"]),
            frontmatter=dict(frontmatter) if isinstance(frontmatter, Mapping) else {},
            workflow=dict(workflow) if isinstance(workflow, Mapping) else {},
            preferred_tools=list(preferred_tools) if isinstance(preferred_tools, list) else [],
            tags=list(tags) if isinstance(tags, list) else [],
            enabled=bool(row["enabled"]),
            active=bool(row["active"]),
            author=str(row["author"]),
            approval_required=bool(row["approval_required"]),
            approval_id=row["approval_id"],
            confidence=float(row["confidence"]) if row["confidence"] is not None else None,
            created_at=str(row["created_at"]),
            updated_at=str(row["updated_at"]),
            approved_at=row["approved_at"],
            archived_at=row["archived_at"],
        )

