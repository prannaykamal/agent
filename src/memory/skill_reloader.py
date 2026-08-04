from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import List, Optional, Tuple

from src.memory.skill_files import parse_skill_markdown, validate_generated_skill_path
from src.memory.skill_store import SkillUsageStatsRecord, SkillVersionStore


@dataclass(frozen=True)
class ActiveSkillSnapshot:
    version_id: str
    skill_id: str
    name: str
    description: str
    file_path: str
    content_hash: str
    trigger_keywords: List[str]
    preferred_tools: List[str]
    tags: List[str]
    execution_steps: str


@dataclass(frozen=True)
class SkillRuntimeSnapshot:
    loaded_at: str
    skills: Tuple[ActiveSkillSnapshot, ...]


def _now_iso() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")


class SkillRuntimeReloader:
    def __init__(self, db_path: Optional[Path] = None, skill_path: Optional[Path] = None):
        self.db_path = db_path
        self.skill_path = skill_path
        self._store = SkillVersionStore(db_path=db_path, skill_path=skill_path)
        self._snapshot = SkillRuntimeSnapshot(loaded_at="", skills=tuple())
        self.last_error: Optional[str] = None

    def reload_active_skills(self) -> SkillRuntimeSnapshot:
        previous = self._snapshot
        try:
            records = self._store.list_active_versions()
            loaded: List[ActiveSkillSnapshot] = []
            for record in records:
                path = validate_generated_skill_path(Path(record.file_path), self.skill_path)
                content = path.read_text(encoding="utf-8")
                frontmatter, body = parse_skill_markdown(content)
                if frontmatter.skill_id != record.skill_id:
                    raise ValueError(f"skill_id mismatch for {record.id}")
                if frontmatter.version != record.version:
                    raise ValueError(f"version mismatch for {record.id}")
                if frontmatter.content_hash != record.content_hash:
                    raise ValueError(f"content_hash mismatch for {record.id}")
                loaded.append(
                    ActiveSkillSnapshot(
                        version_id=record.id,
                        skill_id=record.skill_id,
                        name=record.name,
                        description=record.description,
                        file_path=str(path),
                        content_hash=record.content_hash,
                        trigger_keywords=list(frontmatter.trigger_keywords),
                        preferred_tools=list(frontmatter.preferred_tools),
                        tags=list(frontmatter.tags),
                        execution_steps=body.strip(),
                    )
                )
            for item in loaded:
                self._store.record_loaded(item.skill_id, item.version_id)
            self._snapshot = SkillRuntimeSnapshot(loaded_at=_now_iso(), skills=tuple(loaded))
            self.last_error = None
            return self._snapshot
        except Exception as exc:
            self.last_error = f"{type(exc).__name__}: {exc}"
            return previous

    def get_snapshot(self) -> SkillRuntimeSnapshot:
        return self._snapshot

    def record_skill_used(self, skill_id: str) -> Optional[SkillUsageStatsRecord]:
        active = self._store.get_active_version(skill_id)
        if active is None:
            return None
        return self._store.record_used(active.skill_id, active.id)