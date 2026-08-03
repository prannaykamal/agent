import hashlib
import json
import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Dict, List, Mapping, Optional, Sequence

from src.config import SKILL_PATH


GENERATED_SKILL_INDEX_MARKER = "<!-- generated-by: personal-agent-skill-index v1 -->"


class SkillFileValidationError(ValueError):
    def __init__(self, field: str, message: str):
        self.field = field
        self.message = message
        super().__init__(f"{field}: {message}")


@dataclass(frozen=True)
class SkillFileFrontmatter:
    schema_version: int
    skill_id: str
    version: int
    name: str
    description: str
    author: str
    namespace: str
    enabled: bool
    active: bool
    created_at: str
    content_hash: str
    trigger_keywords: List[str] = field(default_factory=list)
    preferred_tools: List[str] = field(default_factory=list)
    tags: List[str] = field(default_factory=list)
    approval_required: bool = False
    approval_id: Optional[str] = None
    candidate_id: Optional[str] = None
    confidence: Optional[float] = None
    archived_at: Optional[str] = None

    def to_dict(self) -> Dict[str, Any]:
        return {
            "schema_version": self.schema_version,
            "skill_id": self.skill_id,
            "version": self.version,
            "name": self.name,
            "description": self.description,
            "author": self.author,
            "namespace": self.namespace,
            "enabled": self.enabled,
            "active": self.active,
            "created_at": self.created_at,
            "content_hash": self.content_hash,
            "trigger_keywords": list(self.trigger_keywords),
            "preferred_tools": list(self.preferred_tools),
            "tags": list(self.tags),
            "approval_required": self.approval_required,
            "approval_id": self.approval_id,
            "candidate_id": self.candidate_id,
            "confidence": self.confidence,
            "archived_at": self.archived_at,
        }


def slugify_skill_id(value: str) -> str:
    slug = re.sub(r"[^a-z0-9]+", "-", str(value or "").strip().lower()).strip("-")
    slug = re.sub(r"-+", "-", slug)
    if not slug:
        raise SkillFileValidationError("skill_id", "must contain at least one alphanumeric character")
    return slug


def generated_skill_root(skill_path: Optional[Path] = None) -> Path:
    return (skill_path or SKILL_PATH).parent / "skills" / "generated"


def user_skill_root(skill_path: Optional[Path] = None) -> Path:
    return (skill_path or SKILL_PATH).parent / "skills" / "user"


def generated_skill_file_path(skill_id: str, version: int, skill_path: Optional[Path] = None) -> Path:
    normalized_skill_id = slugify_skill_id(skill_id)
    if int(version) <= 0:
        raise SkillFileValidationError("version", "must be positive")
    return generated_skill_root(skill_path) / normalized_skill_id / f"v{int(version):04d}" / "SKILL.md"


def validate_generated_skill_path(path: Path, skill_path: Optional[Path] = None) -> Path:
    resolved_path = Path(path).resolve()
    resolved_root = generated_skill_root(skill_path).resolve()
    if resolved_path.name != "SKILL.md":
        raise SkillFileValidationError("file_path", "generated skill file must be named SKILL.md")
    try:
        resolved_path.relative_to(resolved_root)
    except ValueError as exc:
        raise SkillFileValidationError("file_path", "generated skill path must stay under generated skill root") from exc
    return resolved_path


def _normalize_non_empty(value: Any, field: str) -> str:
    normalized = re.sub(r"\s+", " ", str(value or "")).strip()
    if not normalized:
        raise SkillFileValidationError(field, "must be non-empty")
    return normalized


def _normalize_string_list(value: Any, field: str) -> List[str]:
    if isinstance(value, str):
        raw_items = [item.strip() for item in value.split(",")]
    elif isinstance(value, Sequence) and not isinstance(value, (bytes, bytearray)):
        raw_items = [str(item).strip() for item in value]
    else:
        raise SkillFileValidationError(field, "must be a list of strings")
    return [item for item in raw_items if item]


def _canonical_json(value: Mapping[str, Any]) -> str:
    return json.dumps(dict(value), ensure_ascii=False, sort_keys=True, separators=(",", ":"))


def calculate_skill_content_hash(content: str) -> str:
    return hashlib.sha256(str(content or "").encode("utf-8")).hexdigest()


def _yaml_scalar(value: Any) -> str:
    if value is True:
        return "true"
    if value is False:
        return "false"
    if value is None:
        return "null"
    if isinstance(value, (int, float)):
        return str(value)
    return json.dumps(str(value), ensure_ascii=False)


def _frontmatter_without_hash(frontmatter: SkillFileFrontmatter) -> Dict[str, Any]:
    data = frontmatter.to_dict()
    data["content_hash"] = ""
    return data


def _render_frontmatter(data: Mapping[str, Any]) -> str:
    lines = ["---"]
    for key in (
        "schema_version",
        "skill_id",
        "version",
        "name",
        "description",
        "author",
        "namespace",
        "enabled",
        "active",
        "created_at",
        "content_hash",
        "trigger_keywords",
        "preferred_tools",
        "tags",
        "approval_required",
        "approval_id",
        "candidate_id",
        "confidence",
        "archived_at",
    ):
        value = data.get(key)
        if isinstance(value, list):
            lines.append(f"{key}:")
            if value:
                for item in value:
                    lines.append(f"  - {_yaml_scalar(item)}")
            else:
                lines.append("  []")
        else:
            lines.append(f"{key}: {_yaml_scalar(value)}")
    lines.append("---")
    return "\n".join(lines)


def _render_body(frontmatter: SkillFileFrontmatter, execution_steps: str) -> str:
    keywords = "\n".join(f"- {keyword}" for keyword in frontmatter.trigger_keywords) or "- general"
    steps = _normalize_non_empty(execution_steps, "execution_steps")
    return (
        f"# {frontmatter.name}\n\n"
        "## Description\n\n"
        f"{frontmatter.description}\n\n"
        "## Trigger Keywords\n\n"
        f"{keywords}\n\n"
        "## Workflow\n\n"
        f"{steps.strip()}\n"
    )


def render_skill_markdown(frontmatter: SkillFileFrontmatter, execution_steps: str) -> str:
    validated = validate_skill_frontmatter(frontmatter, validate_hash=False)
    body = _render_body(validated, execution_steps)
    content_without_hash = f"{_render_frontmatter(_frontmatter_without_hash(validated))}\n{body}"
    content_hash = calculate_skill_content_hash(content_without_hash)
    final_frontmatter = SkillFileFrontmatter(**{**validated.to_dict(), "content_hash": content_hash})
    return f"{_render_frontmatter(final_frontmatter.to_dict())}\n{body}"


def _parse_scalar(raw: str) -> Any:
    value = raw.strip()
    if value == "null":
        return None
    if value == "true":
        return True
    if value == "false":
        return False
    if re.fullmatch(r"-?\d+", value):
        return int(value)
    if re.fullmatch(r"-?\d+\.\d+", value):
        return float(value)
    try:
        return json.loads(value)
    except Exception:
        return value


def _parse_frontmatter_block(block: str) -> Dict[str, Any]:
    data: Dict[str, Any] = {}
    current_list_key: Optional[str] = None
    for raw_line in block.splitlines():
        line = raw_line.rstrip()
        if not line.strip():
            continue
        if line.startswith("  - ") and current_list_key:
            data.setdefault(current_list_key, []).append(_parse_scalar(line[4:]))
            continue
        if line.startswith("  []") and current_list_key:
            data[current_list_key] = []
            continue
        current_list_key = None
        if ":" not in line:
            raise SkillFileValidationError("frontmatter", "contains invalid YAML-like line")
        key, raw_value = line.split(":", 1)
        key = key.strip()
        raw_value = raw_value.strip()
        if raw_value == "":
            data[key] = []
            current_list_key = key
        else:
            data[key] = _parse_scalar(raw_value)
    return data


def parse_skill_markdown(content: str) -> tuple[SkillFileFrontmatter, str]:
    text = str(content or "")
    if not text.startswith("---\n"):
        raise SkillFileValidationError("frontmatter", "SKILL.md must start with YAML frontmatter")
    end = text.find("\n---", 4)
    if end == -1:
        raise SkillFileValidationError("frontmatter", "SKILL.md frontmatter must be closed")
    block = text[4:end]
    body = text[end + 4 :].lstrip("\n")
    data = _parse_frontmatter_block(block)
    frontmatter = SkillFileFrontmatter(
        schema_version=int(data.get("schema_version", 0)),
        skill_id=str(data.get("skill_id") or ""),
        version=int(data.get("version", 0)),
        name=str(data.get("name") or ""),
        description=str(data.get("description") or ""),
        author=str(data.get("author") or ""),
        namespace=str(data.get("namespace") or ""),
        enabled=bool(data.get("enabled")),
        active=bool(data.get("active")),
        created_at=str(data.get("created_at") or ""),
        content_hash=str(data.get("content_hash") or ""),
        trigger_keywords=_normalize_string_list(data.get("trigger_keywords", []), "trigger_keywords"),
        preferred_tools=_normalize_string_list(data.get("preferred_tools", []), "preferred_tools"),
        tags=_normalize_string_list(data.get("tags", []), "tags"),
        approval_required=bool(data.get("approval_required")),
        approval_id=data.get("approval_id"),
        candidate_id=data.get("candidate_id"),
        confidence=data.get("confidence"),
        archived_at=data.get("archived_at"),
    )
    return validate_skill_frontmatter(frontmatter, content=text), body


def validate_skill_frontmatter(
    frontmatter: SkillFileFrontmatter,
    *,
    content: Optional[str] = None,
    validate_hash: bool = True,
) -> SkillFileFrontmatter:
    if int(frontmatter.schema_version) != 1:
        raise SkillFileValidationError("schema_version", "must be 1")
    skill_id = slugify_skill_id(frontmatter.skill_id)
    version = int(frontmatter.version)
    if version <= 0:
        raise SkillFileValidationError("version", "must be positive")
    namespace = _normalize_non_empty(frontmatter.namespace, "namespace")
    if namespace not in {"generated", "user"}:
        raise SkillFileValidationError("namespace", "must be generated or user")
    confidence = frontmatter.confidence
    if confidence is not None:
        confidence = float(confidence)
        if confidence < 0 or confidence > 1:
            raise SkillFileValidationError("confidence", "must be between 0 and 1")
    if validate_hash and content is not None:
        without_hash = content.replace(f"content_hash: {json.dumps(frontmatter.content_hash)}", "content_hash: \"\"", 1)
        if without_hash == content:
            without_hash = content.replace(f"content_hash: {frontmatter.content_hash}", "content_hash: \"\"", 1)
        expected_hash = calculate_skill_content_hash(without_hash)
        if frontmatter.content_hash != expected_hash:
            raise SkillFileValidationError("content_hash", "does not match SKILL.md content")
    elif _normalize_non_empty(frontmatter.content_hash if validate_hash else "placeholder", "content_hash") == "":
        raise SkillFileValidationError("content_hash", "must be non-empty")
    return SkillFileFrontmatter(
        schema_version=1,
        skill_id=skill_id,
        version=version,
        name=_normalize_non_empty(frontmatter.name, "name"),
        description=_normalize_non_empty(frontmatter.description, "description"),
        author=_normalize_non_empty(frontmatter.author, "author"),
        namespace=namespace,
        enabled=bool(frontmatter.enabled),
        active=bool(frontmatter.active),
        created_at=_normalize_non_empty(frontmatter.created_at, "created_at"),
        content_hash=str(frontmatter.content_hash),
        trigger_keywords=_normalize_string_list(frontmatter.trigger_keywords, "trigger_keywords"),
        preferred_tools=_normalize_string_list(frontmatter.preferred_tools, "preferred_tools"),
        tags=_normalize_string_list(frontmatter.tags, "tags"),
        approval_required=bool(frontmatter.approval_required),
        approval_id=frontmatter.approval_id,
        candidate_id=frontmatter.candidate_id,
        confidence=confidence,
        archived_at=frontmatter.archived_at,
    )


def write_immutable_skill_file(path: Path, content: str, skill_path: Optional[Path] = None) -> Path:
    target_path = validate_generated_skill_path(path, skill_path)
    if target_path.exists():
        raise SkillFileValidationError("file_path", "generated skill version already exists")
    target_path.parent.mkdir(parents=True, exist_ok=True)
    target_path.write_text(content, encoding="utf-8")
    return target_path


def render_active_skill_index(skills: Sequence[Mapping[str, Any]]) -> str:
    lines = [
        GENERATED_SKILL_INDEX_MARKER,
        "# Procedural Skills & Workflows",
        "",
        "## Active Generated Skills",
    ]
    if not skills:
        lines.append("")
        lines.append("*No procedural skills defined yet.*")
        return "\n".join(lines) + "\n"
    for index, skill in enumerate(skills, 1):
        lines.append("")
        lines.append(f"### {index}. {skill.get('name', '')}")
        lines.append(f"- **Description**: {skill.get('description', '')}")
        lines.append(f"- **Trigger Keywords**: {skill.get('trigger_keywords', '')}")
        lines.append(f"- **Action Steps**: {skill.get('execution_steps', '')}")
        if skill.get("version") is not None:
            lines.append(f"- **Version**: {skill.get('version')}")
    return "\n".join(lines) + "\n"
