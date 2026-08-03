import re
from pathlib import Path
from typing import Any, Dict, List, Optional

from src.config import SKILL_PATH
from src.memory.skill_files import GENERATED_SKILL_INDEX_MARKER, render_active_skill_index
from src.memory.skill_store import SkillVersionStore, SkillVersionWrite


def _store(db_path: Optional[Path] = None, skill_path: Optional[Path] = None) -> SkillVersionStore:
    return SkillVersionStore(db_path=db_path, skill_path=skill_path)


def add_procedural_skill(
    name: str,
    description: str,
    trigger_keywords: str,
    execution_steps: str,
    db_path: Optional[Path] = None,
    skill_path: Optional[Path] = None,
) -> None:
    """Create a new immutable versioned procedural skill and keep legacy callers working."""
    _store(db_path, skill_path).create_version(
        SkillVersionWrite(
            name=name,
            description=description,
            trigger_keywords=trigger_keywords,
            execution_steps=execution_steps,
            author="api",
            activate=True,
        )
    )
    sync_skill_md(db_path=db_path, skill_path=skill_path)


def update_procedural_skill(
    name: str,
    execution_steps: str,
    db_path: Optional[Path] = None,
    skill_path: Optional[Path] = None,
) -> None:
    """Create a new version for an existing procedural skill instead of mutating old files."""
    store = _store(db_path, skill_path)
    skills = store.list_legacy_compatible_skills()
    existing = next((skill for skill in skills if str(skill.get("name", "")).lower() == name.lower()), None)
    if existing is None:
        description = name
        trigger_keywords = name
        skill_id = None
    else:
        description = str(existing.get("description") or name)
        trigger_keywords = str(existing.get("trigger_keywords") or name)
        skill_id = existing.get("skill_id")
    store.create_version(
        SkillVersionWrite(
            name=name,
            description=description,
            trigger_keywords=trigger_keywords,
            execution_steps=execution_steps,
            skill_id=str(skill_id) if skill_id else None,
            author="api",
            activate=True,
        )
    )
    sync_skill_md(db_path=db_path, skill_path=skill_path)


def delete_procedural_skill(
    name: str, db_path: Optional[Path] = None, skill_path: Optional[Path] = None) -> None:
    """Disable/archive the active generated version; immutable files remain on disk."""
    store = _store(db_path, skill_path)
    skill_id = None
    for skill in store.list_legacy_compatible_skills():
        if str(skill.get("name", "")).lower() == name.lower():
            skill_id = str(skill.get("skill_id") or name)
            break
    store.disable_skill(skill_id or name, reason="deleted via procedural compatibility API")
    sync_skill_md(db_path=db_path, skill_path=skill_path)


def get_all_procedural_skills(db_path: Optional[Path] = None) -> List[Dict[str, Any]]:
    """Return active enabled procedural skills in the legacy-compatible shape."""
    return _store(db_path).list_legacy_compatible_skills()


def sync_skill_md(db_path: Optional[Path] = None, skill_path: Optional[Path] = None) -> str:
    """Render a safe compatibility index from active versioned skills."""
    target_path = skill_path or SKILL_PATH
    skills = _store(db_path, skill_path).list_legacy_compatible_skills()
    content = render_active_skill_index(skills)

    if target_path.exists() and skill_path is None:
        existing = target_path.read_text(encoding="utf-8")
        if GENERATED_SKILL_INDEX_MARKER not in existing:
            return existing

    target_path.parent.mkdir(parents=True, exist_ok=True)
    target_path.write_text(content, encoding="utf-8")
    return content


def sync_skills_from_md(skill_path: Optional[Path] = None, db_path: Optional[Path] = None) -> None:
    """Conservatively import an explicit Markdown catalog without overwriting user-authored files."""
    target_path = skill_path or SKILL_PATH
    if not target_path.exists():
        return

    content = target_path.read_text(encoding="utf-8")
    sections = re.findall(r"###\s+\d+\.\s+(.*?)\n(.*?)(?=\n###|\Z)", content, re.DOTALL)
    for name, body in sections:
        clean_name = name.strip()
        if not clean_name:
            continue
        trigger_match = re.search(r"-\s+\*\*(?:Trigger Keywords|Trigger)\*\*:\s*(.*)", body)
        action_match = re.search(r"-\s+\*\*(?:Action Steps|Action)\*\*:\s*(.*)", body)
        description_match = re.search(r"-\s+\*\*Description\*\*:\s*(.*)", body)
        trigger_keywords = trigger_match.group(1).strip() if trigger_match else clean_name
        execution_steps = action_match.group(1).strip() if action_match else body.strip()
        description = description_match.group(1).strip() if description_match else clean_name
        _store(db_path, skill_path).create_version(
            SkillVersionWrite(
                name=clean_name,
                description=description,
                trigger_keywords=trigger_keywords,
                execution_steps=execution_steps,
                author="api",
                activate=True,
            )
        )


def match_procedural_skills(query: str, db_path: Optional[Path] = None) -> List[Dict[str, Any]]:
    """Keyword-match active enabled procedural skills without changing retrieval behavior."""
    if not query.strip():
        return []
    matched: List[Dict[str, Any]] = []
    query_lower = query.lower()
    for skill in get_all_procedural_skills(db_path=db_path):
        keywords = [keyword.strip().lower() for keyword in str(skill.get("trigger_keywords", "")).split(",")]
        keywords.append(str(skill.get("name", "")).lower())
        if any(keyword in query_lower for keyword in keywords if len(keyword) > 2):
            matched.append(skill)
    return matched
