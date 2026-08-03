# Phase 8A Design: Versioned Procedural Skill Files

## 1. Executive Summary

Phase 8A establishes procedural memory as immutable, versioned Markdown `SKILL.md` files backed by the existing `skill_versions` and `skill_usage_stats` tables. It replaces the current single mutable procedural catalog model in `src/memory/procedural.py`, while preserving public compatibility for existing skill APIs and callers.

The current system stores procedural skills in the legacy `skills` table and renders all skills into one `.agent/SKILL.md` file. That conflicts with the approved architecture because generated updates can overwrite prior content, there is no immutable history, rollback is impossible, and user-authored skill files cannot be safely separated from generated ones.

Phase 8A introduces:

- `src/memory/skill_files.py` for file paths, frontmatter validation, Markdown rendering, content hashing, and generated/user namespace safety.
- `src/memory/skill_store.py` for version metadata, active-version tracking, rollback, disabled/archive metadata, usage stat initialization, and compatibility read/write methods.
- A refactored `src/memory/procedural.py` compatibility facade that delegates to the new store without preserving flawed mutable abstractions internally.
- Minimal `src/startup.py` and `src/api/server.py` changes to stop treating `.agent/SKILL.md` as the authoritative generated skill catalog.

Phase 8A must not create skill candidates, deduplicate procedural skills, use HITL approval linkage, auto-generate skills from episodes, change retrieval behavior, or add schema migrations.

## 2. Scope

In scope:

- Create versioned generated skill files.
- Store generated skill metadata in `skill_versions`.
- Initialize and update `skill_usage_stats` for logical skills.
- Validate required YAML frontmatter.
- Separate generated skill files from user-authored skill directories.
- Prevent overwrites of user-authored files and immutable generated versions.
- Create new versions for updates.
- Mark exactly one active enabled version per logical skill.
- Support rollback by activating an older version without mutating that version file.
- Preserve existing public procedural functions where practical:
  - `add_procedural_skill()`
  - `update_procedural_skill()`
  - `delete_procedural_skill()`
  - `get_all_procedural_skills()`
  - `sync_skill_md()`
  - `sync_skills_from_md()`
  - `match_procedural_skills()`
- Preserve `/api/skills` route availability and response compatibility while adding version metadata.
- Preserve `/api/memory/full` response shape.
- Add deterministic tests for file, DB, API, and startup behavior.

## 3. Out Of Scope

Out of scope:

- Skill candidates.
- Procedural candidate generation from episodes.
- Procedural deduplication.
- Promotion and approval workflow.
- `procedural_skill_approvals` writes.
- HITL approval UI or inbox changes.
- Automatic skill generation from semantic or episodic memory.
- Background worker procedural handlers.
- Runtime retrieval changes.
- Chat prompt changes.
- Schema migrations.
- Backfilling all existing legacy `skills` rows into `skill_versions` at startup.
- Overwriting user-authored `SKILL.md` files.

## 4. Current Procedural Memory Assessment

### `src/memory/procedural.py`

Current behavior:

- Stores procedural skills in legacy SQLite table `skills`.
- Uses `INSERT OR REPLACE`, which mutates the logical skill in place.
- `update_procedural_skill()` mutates `execution_steps`.
- `delete_procedural_skill()` removes the row.
- `sync_skill_md()` rewrites one aggregate `.agent/SKILL.md`.
- `sync_skills_from_md()` parses the aggregate Markdown back into `skills`.
- `match_procedural_skills()` performs keyword matching against the legacy `skills` table.

Problems:

- No version history.
- No active version concept.
- No rollback.
- Generated content can overwrite file content.
- User-authored and generated content share the same namespace.
- `INSERT OR REPLACE` can destroy metadata.
- The parser and renderer use mismatched labels: writer emits `Trigger Keywords` / `Action Steps`; parser looks for `Trigger` / `Action`.
- Legacy `skills` remains useful as a compatibility read model, but should not remain the source of truth for generated skills.

Classification:

- `src/memory/procedural.py`: REPLACE internally, preserve compatibility facade.

### `src/memory/schema.py`

Phase 2 already created the target tables:

- `skill_versions`
- `skill_usage_stats`
- `skill_candidates`
- `procedural_skill_approvals`

Phase 8A uses only:

- `skill_versions`
- `skill_usage_stats`

No schema changes are required.

### `src/startup.py`

Current behavior:

- Creates `.agent/SKILL.md` if missing.
- Treats `SKILL_PATH.exists()` as the procedural skill file health indicator.

Problem:

- Startup should initialize directories for versioned generated skills and user-authored skills.
- Startup must not overwrite existing `.agent/SKILL.md`.
- Startup should keep `.agent/SKILL.md` compatibility only, not treat it as the generated skill source of truth.

Classification:

- `src/startup.py`: REFACTOR.

### `src/api/server.py`

Current behavior:

- `/api/skills` reads legacy `get_all_procedural_skills()`.
- `POST /api/skills` writes legacy skills and rewrites `.agent/SKILL.md`.
- `DELETE /api/skills/{skill_name}` deletes legacy skill rows and rewrites `.agent/SKILL.md`.
- `/api/memory/full` reads `SKILL_PATH` and returns `skill_md`.

Phase 8A behavior:

- Keep route shapes compatible.
- Add version metadata to skill objects returned by `/api/skills`.
- Continue returning `skills` and `total_skills`.
- Keep `POST /api/skills` as a user/API-authored procedural write that creates a versioned skill file.
- Convert delete into disable/archive for the active generated skill version rather than deleting immutable files.
- Keep `/api/memory/full` response keys unchanged.

Classification:

- `src/api/server.py`: REFACTOR.

### `src/hitl/*`

Current behavior:

- HITL provides generic approval requests and decisions.

Phase 8A behavior:

- No HITL integration changes.
- No writes to `procedural_skill_approvals`.
- Phase 8C will link skill versions and approvals.

Classification:

- `src/hitl/*`: KEEP for Phase 8A.

## 5. Skill File Architecture

Phase 8A creates immutable `SKILL.md` files under a generated namespace. Each logical skill has a stable `skill_id`; each update creates a new version directory with a new `SKILL.md`.

Recommended directory layout:

```text
.agent/
  SKILL.md                         # compatibility index only, never authoritative for generated skills
  skills/
    generated/
      <skill_id>/
        v0001/
          SKILL.md
        v0002/
          SKILL.md
    user/
      README.md                    # reserved namespace for user-authored skills
```

Rules:

- Generated files live only under `.agent/skills/generated`.
- User-authored files live outside generated version directories.
- Existing `.agent/SKILL.md` is preserved if present.
- Existing generated version files are never overwritten.
- Updating a skill creates `vNNNN/SKILL.md`.
- Active version is tracked in SQLite, not by replacing files.
- Disabled and archived versions remain readable.

### Module: `src/memory/skill_files.py`

Responsibilities:

- Resolve procedural skill roots from `SKILL_PATH.parent`.
- Normalize and validate `skill_id`.
- Generate deterministic file paths for generated skill versions.
- Render valid `SKILL.md` content with YAML frontmatter.
- Parse YAML frontmatter from `SKILL.md`.
- Validate frontmatter and body.
- Calculate content hash.
- Detect whether a path is inside the generated namespace.
- Refuse to write outside the generated namespace.
- Refuse to overwrite existing version files.
- Render a compatibility index from active versions if needed.

No DB access belongs in this module.

## 6. Directory / Namespace Design

### Generated namespace

Root:

```text
.agent/skills/generated
```

Generated skill path:

```text
.agent/skills/generated/<skill_id>/v<version:04d>/SKILL.md
```

Example:

```text
.agent/skills/generated/deploy-staging/v0001/SKILL.md
```

Generated namespace rules:

- `skill_id` must be slug-safe: lowercase letters, numbers, and hyphens.
- Version path must use zero-padded four digit form.
- The final filename must be exactly `SKILL.md`.
- Writes are allowed only when the target path does not already exist.
- Parent directories may be created.
- Existing files are treated as immutable history.

### User-authored namespace

Root:

```text
.agent/skills/user
```

Phase 8A creates the directory but does not scan or mutate user-authored skills.

Rules:

- Phase 8A must not write user-authored skill files.
- Phase 8A must not rename or delete user-authored skill files.
- If a user-authored file name conflicts with a generated `skill_id`, generated storage still uses the generated namespace and does not touch the user path.

### Legacy compatibility file

Path:

```text
.agent/SKILL.md
```

Phase 8A treats this as a compatibility index, not as generated skill source of truth.

Recommended behavior:

- If missing, startup may create a lightweight compatibility index.
- If present and not marked as generated by this application, do not overwrite it.
- `sync_skill_md()` should render active generated skills only to a caller-provided path in tests, or to `.agent/SKILL.generated.md` by default if overwriting `.agent/SKILL.md` would be unsafe.
- `/api/memory/full` should keep returning a `skill_md` string, sourced from the compatibility index plus active version metadata.

## 7. `SKILL.md` Frontmatter Schema

Every generated version file must contain YAML frontmatter followed by Markdown body.

Required frontmatter fields:

```yaml
---
schema_version: 1
skill_id: deploy-staging
version: 1
name: Deploy Staging
description: Deploys a build to staging.
author: generated
namespace: generated
enabled: true
active: true
created_at: "2026-08-03T00:00:00Z"
content_hash: "<sha256 of body or normalized full content without content_hash>"
trigger_keywords:
  - deploy
  - staging
preferred_tools: []
tags: []
approval_required: false
approval_id: null
candidate_id: null
confidence: null
archived_at: null
---
```

Required Markdown body sections:

```markdown
# Deploy Staging

## Description

Deploys a build to staging.

## Trigger Keywords

- deploy
- staging

## Workflow

1. Validate the build artifact.
2. Deploy to staging.
```

Validation rules:

- `schema_version` must be `1`.
- `skill_id`, `name`, `description`, `author`, and `namespace` are non-empty strings.
- `version` must be positive.
- `namespace` must be `generated` or `user`.
- Phase 8A writes only `namespace: generated`.
- `enabled`, `active`, and `approval_required` must be booleans.
- `trigger_keywords`, `preferred_tools`, and `tags` must be lists of strings.
- `confidence` must be `null` or between `0` and `1`.
- `content_hash` must be non-empty and match the rendered content hash.
- Body must contain a top-level heading and non-empty workflow content.

YAML dependency policy:

- Prefer `yaml.safe_load` if PyYAML is already installed.
- Provide a deterministic fallback parser/writer for the simple Phase 8A frontmatter subset if PyYAML is unavailable.
- Do not add a dependency unless tests show the environment already lacks a reliable parser and the project policy permits adding one.

## 8. Skill Store Design

### Module: `src/memory/skill_store.py`

Responsibilities:

- Create immutable generated skill versions.
- Read skill versions.
- List active skills.
- List all versions for a skill.
- Activate a version.
- Roll back to an older version.
- Disable/archive a skill version.
- Initialize and update `skill_usage_stats`.
- Mirror minimal active generated skill metadata into legacy `skills` for compatibility, if needed.
- Provide compatibility objects matching current `/api/skills` callers.

No LLM calls belong in this module.

### Public Data Models

```python
SkillNamespace = Literal["generated", "user"]
SkillAuthor = Literal["generated", "user", "api", "system"]

@dataclass(frozen=True)
class SkillFileFrontmatter:
    schema_version: int
    skill_id: str
    version: int
    name: str
    description: str
    author: str
    namespace: SkillNamespace
    enabled: bool
    active: bool
    created_at: str
    content_hash: str
    trigger_keywords: list[str]
    preferred_tools: list[str]
    tags: list[str]
    approval_required: bool = False
    approval_id: str | None = None
    candidate_id: str | None = None
    confidence: float | None = None
    archived_at: str | None = None

@dataclass(frozen=True)
class SkillVersionWrite:
    name: str
    description: str
    trigger_keywords: list[str]
    execution_steps: str
    preferred_tools: list[str] = field(default_factory=list)
    tags: list[str] = field(default_factory=list)
    skill_id: str | None = None
    candidate_id: str | None = None
    author: str = "api"
    approval_required: bool = False
    approval_id: str | None = None
    confidence: float | None = None
    enabled: bool = True
    activate: bool = True

@dataclass(frozen=True)
class SkillVersionRecord:
    id: str
    skill_id: str
    candidate_id: str | None
    version: int
    name: str
    description: str
    file_path: str
    content_hash: str
    frontmatter: dict[str, Any]
    workflow: dict[str, Any]
    preferred_tools: list[str]
    tags: list[str]
    enabled: bool
    active: bool
    author: str
    approval_required: bool
    approval_id: str | None
    confidence: float | None
    created_at: str
    updated_at: str
    approved_at: str | None
    archived_at: str | None

@dataclass(frozen=True)
class SkillUsageStatsRecord:
    skill_id: str
    active_version_id: str | None
    times_loaded: int
    times_used: int
    last_loaded: str | None
    last_used: str | None
    last_updated: str
    created_at: str
```

### Repository API

```python
class SkillVersionStore:
    def create_version(self, write: SkillVersionWrite) -> SkillVersionRecord: ...
    def get_version(self, version_id: str) -> SkillVersionRecord | None: ...
    def get_active_version(self, skill_id: str) -> SkillVersionRecord | None: ...
    def list_active_versions(self, include_disabled: bool = False) -> list[SkillVersionRecord]: ...
    def list_versions(self, skill_id: str) -> list[SkillVersionRecord]: ...
    def rollback_to_version(self, skill_id: str, version: int) -> SkillVersionRecord: ...
    def disable_skill(self, skill_id: str, reason: str | None = None) -> SkillVersionRecord | None: ...
    def archive_version(self, version_id: str, reason: str | None = None) -> SkillVersionRecord: ...
    def record_loaded(self, skill_id: str, version_id: str) -> SkillUsageStatsRecord: ...
    def record_used(self, skill_id: str, version_id: str) -> SkillUsageStatsRecord: ...
    def list_legacy_compatible_skills(self) -> list[dict[str, Any]]: ...
```

## 9. Versioning Design

Logical skill identity:

- `skill_id` is stable across versions.
- If not provided, derive from `name` using a slug helper.
- `skill_id` must not depend on the version content.

Version IDs:

```text
skillver_<skill_id>_v<version>
```

Example:

```text
skillver_deploy-staging_v0002
```

Version selection:

- Read current max `version` for `skill_id`.
- New version is max + 1.
- Insert into `skill_versions`.
- Write file to generated namespace.
- If `activate=True`, mark existing active version for `skill_id` inactive and mark new version active inside one DB transaction.

Atomicity strategy:

1. Validate input.
2. Determine target version and path.
3. Render content in memory.
4. Verify target path does not exist.
5. Write file.
6. Insert `skill_versions`.
7. Update active flags and usage stats.
8. If DB insert fails after file write, leave the immutable file in place and return a clear error; a future repair helper can reconcile orphaned generated files.

The file write cannot be perfectly atomic with SQLite. The implementation should favor never overwriting user content and never mutating prior versions over attempting aggressive rollback.

## 10. Active Version / Rollback Design

Active version invariant:

- At most one `skill_versions` row per `skill_id` has `active = 1`.
- This is already enforced by `idx_skill_versions_one_active_per_skill`.

Activating a version:

- Validate version belongs to `skill_id`.
- Validate version is enabled.
- Set all versions for `skill_id` to `active = 0`.
- Set selected version to `active = 1`.
- Update `skill_usage_stats.active_version_id`.
- Do not modify any `SKILL.md` file.

Rollback:

- Rollback is active pointer movement only.
- Rollback does not create a new version in Phase 8A.
- Rollback to disabled or archived version is rejected unless explicitly re-enabled first.
- Rollback preserves immutable history.

Disable/archive behavior:

- `disable_skill(skill_id)` sets the active version `enabled = 0`, `active = 0`, and `archived_at = datetime('now')`.
- Historical versions remain on disk.
- Disabled versions must be excluded from active lists and compatibility matching.
- Phase 8A does not permanently delete files.

## 11. User-authored vs Generated Skill Safety

Safety rules:

- Never write under `.agent/skills/user`.
- Never write outside `.agent/skills/generated`.
- Never write directly to an existing generated `SKILL.md`.
- Never overwrite existing `.agent/SKILL.md` unless it contains a clear generated compatibility marker or a caller supplies an explicit test path.
- Do not infer user-authored skill contents from arbitrary Markdown and write them into generated namespaces.
- Do not use `sync_skills_from_md()` to mutate existing generated versions.

Path validation:

- Resolve the absolute generated root.
- Resolve the absolute target path.
- Confirm target path is under generated root.
- Confirm target filename is `SKILL.md`.
- Confirm target does not exist.

Generated compatibility marker:

```markdown
<!-- generated-by: personal-agent-skill-index v1 -->
```

Only files containing this marker are eligible for automatic regeneration.

## 12. API Compatibility

### `GET /api/skills`

Keep response shape:

```json
{
  "skills": [],
  "total_skills": 0
}
```

Each skill object should preserve legacy keys:

```json
{
  "id": 1,
  "name": "Deploy Staging",
  "description": "Deploys to staging server",
  "trigger_keywords": "deploy, release, staging",
  "execution_steps": "Deploy build v1"
}
```

Phase 8A may add version metadata without removing legacy keys:

```json
{
  "skill_id": "deploy-staging",
  "version_id": "skillver_deploy-staging_v0001",
  "version": 1,
  "active": true,
  "enabled": true,
  "file_path": ".agent/skills/generated/deploy-staging/v0001/SKILL.md",
  "content_hash": "...",
  "author": "api"
}
```

### `POST /api/skills`

Existing request shape remains:

```json
{
  "name": "Deploy Staging",
  "description": "Deploys to staging server",
  "trigger_keywords": "deploy, release, staging",
  "execution_steps": "Deploy build v1"
}
```

Phase 8A behavior:

- Create a new generated skill version.
- Activate it by default.
- Mirror to legacy `skills` only as a compatibility read model if required by existing callers.
- Return existing `status` key and a compatible message.

### `DELETE /api/skills/{skill_name}`

Existing route remains.

Phase 8A behavior:

- Resolve `skill_name` to active skill by exact name or slug.
- Disable/archive the active generated version.
- Remove or mark inactive in the legacy compatibility table.
- Do not delete generated version files.
- Return existing `status` key.

### `/api/memory/full`

Response shape remains:

```json
{
  "facts": [],
  "episodes": [],
  "soul_md": "",
  "skill_md": "",
  "memory_md": ""
}
```

Phase 8A should populate `skill_md` from:

1. Existing `.agent/SKILL.md` if present and user-authored.
2. Generated compatibility index if present.
3. Rendered active generated skills if no compatibility file exists.

No new public response keys are required for Phase 8A.

## 13. Startup / Hot-load Compatibility

Startup changes:

- Create `.agent/skills/generated`.
- Create `.agent/skills/user`.
- Keep existing `.agent/SKILL.md` untouched if present.
- If `.agent/SKILL.md` is missing, create a minimal compatibility index with the generated marker.
- Initialize DB as before.
- Do not scan episodes or candidates.
- Do not create generated skill versions from existing legacy rows automatically.

Hot-load compatibility:

- Phase 8A does not implement runtime skill hot-reload.
- `skill_usage_stats.times_loaded` may be initialized when active versions are listed for `/api/skills`, but should not imply retrieval behavior.
- Phase 8C will implement approval-driven reload and runtime loading stats.

## 14. File-by-file Modifications

### New file: `src/memory/skill_files.py`

Add:

- `SkillFileFrontmatter`
- `SkillFileValidationError`
- `slugify_skill_id()`
- `generated_skill_root()`
- `user_skill_root()`
- `generated_skill_file_path()`
- `validate_generated_skill_path()`
- `render_skill_markdown()`
- `parse_skill_markdown()`
- `validate_skill_frontmatter()`
- `calculate_skill_content_hash()`
- `write_immutable_skill_file()`
- `render_active_skill_index()`

### New file: `src/memory/skill_store.py`

Add:

- `SkillVersionWrite`
- `SkillVersionRecord`
- `SkillUsageStatsRecord`
- `SkillVersionStore`
- version creation/read/list/rollback/disable/archive APIs
- usage stat initialization/update APIs
- compatibility conversion to current skill dictionaries

### Modify: `src/memory/procedural.py`

Replace internals with facade behavior:

- `add_procedural_skill()` delegates to `SkillVersionStore.create_version()`.
- `update_procedural_skill()` creates a new version for the skill.
- `delete_procedural_skill()` disables/archives active version.
- `get_all_procedural_skills()` returns active enabled versions as legacy-compatible dicts.
- `sync_skill_md()` renders an index from active versions without using it as source of truth.
- `sync_skills_from_md()` becomes conservative:
  - parses only caller-supplied files,
  - creates generated versions only when explicitly requested by existing tests/callers,
  - never overwrites user-authored files.
- `match_procedural_skills()` still performs keyword matching over active enabled versions.

### Modify: `src/startup.py`

Add:

- generated/user skill directory initialization.
- compatibility index creation only if missing.
- no overwrite of existing `SKILL.md`.

### Modify: `src/api/server.py`

Add:

- `/api/skills` response uses `SkillVersionStore` through procedural facade.
- `POST /api/skills` creates a new version.
- `DELETE /api/skills/{skill_name}` disables/archive active version.
- `/api/memory/full` preserves shape and reads compatibility skill content.

### Tests only

Add Phase 8A tests and update legacy procedural expectations where needed.

## 15. Database Usage

No migrations are added.

### `skill_versions`

Purpose:

- Store metadata for every immutable skill file version.

Fields used:

- `id`: deterministic version id.
- `skill_id`: stable logical skill id.
- `candidate_id`: null in Phase 8A.
- `version`: positive integer.
- `name`: display name.
- `description`: short description.
- `file_path`: path to versioned `SKILL.md`.
- `content_hash`: hash of rendered skill content.
- `frontmatter_json`: canonical JSON copy of frontmatter.
- `workflow_json`: canonical workflow representation derived from execution steps.
- `preferred_tools_json`: canonical JSON list.
- `tags_json`: canonical JSON list.
- `enabled`: active skill availability flag.
- `active`: active version pointer flag.
- `author`: `api`, `generated`, or `system`.
- `approval_required`: false in Phase 8A unless caller explicitly passes true for future compatibility.
- `approval_id`: null in Phase 8A.
- `confidence`: null in Phase 8A unless caller supplies explicit metadata.
- `approved_at`: null in Phase 8A.
- `archived_at`: set when disabled/archive behavior runs.

### `skill_usage_stats`

Purpose:

- Track active version and later load/use metrics.

Phase 8A behavior:

- Create or update one row per `skill_id`.
- Set `active_version_id` when active version changes.
- Initialize counters at zero.
- Do not increment `times_used` from retrieval because retrieval behavior is unchanged.

### Legacy `skills`

Purpose:

- Compatibility read model for existing tests/callers until later phases remove direct reliance.

Phase 8A behavior:

- Not authoritative for generated skill files.
- May be synced from active generated versions after create/update/disable.
- Existing rows remain readable.

## 16. Testing Strategy

Add tests:

- `tests/test_phase8a_skill_files.py`
  - slug normalization.
  - generated path validation.
  - user-authored path cannot be targeted.
  - immutable write refuses overwrite.
  - frontmatter render/parse round trip.
  - invalid frontmatter fails with field names.
  - content hash is deterministic.

- `tests/test_phase8a_skill_store_versions.py`
  - create first version.
  - update creates second version.
  - old version file is unchanged.
  - exactly one active version.
  - rollback activates older version.
  - disabled version excluded from active list.
  - `skill_usage_stats` initialized and active version updated.

- `tests/test_phase8a_procedural_compatibility.py`
  - `add_procedural_skill()` preserves callable behavior.
  - `update_procedural_skill()` creates a new version.
  - `delete_procedural_skill()` disables/archive instead of deleting files.
  - `get_all_procedural_skills()` includes legacy keys.
  - `match_procedural_skills()` matches active enabled versions.
  - existing legacy `skills` rows remain readable during transition.

- `tests/test_phase8a_api_skills.py`
  - `GET /api/skills` keeps `skills` and `total_skills`.
  - skill objects include version metadata.
  - `POST /api/skills` creates versioned file and DB row.
  - `DELETE /api/skills/{skill_name}` disables active generated version.
  - `/api/memory/full` response shape unchanged.

- `tests/test_phase8a_startup_skill_dirs.py`
  - startup creates generated/user directories.
  - startup does not overwrite existing `.agent/SKILL.md`.
  - startup creates compatibility index only when missing.

Regression tests:

- `tests/test_procedural_memory.py`
- `tests/test_long_term_memory.py`
- `tests/test_api_server.py`
- `tests/test_harness.py`
- `tests/test_phase7c_consolidation_handler.py`
- `tests/test_phase3b_router_handlers.py`

Suggested run command:

```powershell
python -m pytest tests/test_phase8a_skill_files.py tests/test_phase8a_skill_store_versions.py tests/test_phase8a_procedural_compatibility.py tests/test_phase8a_api_skills.py tests/test_phase8a_startup_skill_dirs.py -q
python -m pytest tests/test_procedural_memory.py tests/test_long_term_memory.py tests/test_api_server.py tests/test_harness.py -q
python -m pytest tests/test_phase7c_consolidation_handler.py tests/test_phase3b_router_handlers.py -q
```

Run full suite if focused tests pass.

## 17. Risks

### Risk: accidental overwrite of user-authored skills

Mitigation:

- Generated namespace path validation.
- Immutable write helper refuses existing files.
- Startup never overwrites existing `.agent/SKILL.md`.
- Tests create conflicting user files and verify they survive unchanged.

### Risk: API compatibility break

Mitigation:

- Keep existing request bodies.
- Keep response top-level keys.
- Preserve legacy fields in each skill object.
- Add version metadata additively.

### Risk: legacy table and versioned store diverge

Mitigation:

- Treat `skill_versions` as source of truth for generated versions.
- Use legacy `skills` only as compatibility mirror.
- Add tests verifying active generated versions are reflected in legacy-compatible reads.

### Risk: rollback violates active unique index

Mitigation:

- Deactivate all versions for `skill_id` before activating selected version in one transaction.
- Test rollback with multiple versions.

### Risk: frontmatter parser dependency instability

Mitigation:

- Use PyYAML only if already available.
- Keep supported frontmatter values simple.
- Provide deterministic fallback parser/writer if needed.

### Risk: later Phase 8B/8C assumptions are blocked

Mitigation:

- Include nullable `candidate_id`, `approval_id`, `approval_required`, `confidence`, `preferred_tools`, and `tags`.
- Do not use candidates or approvals yet.
- Keep generated version IDs stable and queryable.

## 18. Acceptance Criteria

Phase 8A is accepted when:

- `src/memory/skill_files.py` exists and validates generated `SKILL.md` files.
- `src/memory/skill_store.py` exists and writes immutable skill versions.
- New skill creation writes a versioned `SKILL.md` file under `.agent/skills/generated`.
- Updating a skill creates a new version and does not mutate prior version files.
- Rollback activates an older enabled version without changing files.
- Disabled/archive metadata excludes inactive skills from active listings.
- Existing user-authored skill files are not overwritten.
- Existing procedural public functions remain callable.
- `/api/skills` top-level response shape remains compatible.
- `/api/memory/full` response shape remains compatible.
- `skill_versions` and `skill_usage_stats` are used.
- `skill_candidates` and `procedural_skill_approvals` are not written.
- No retrieval behavior changes.
- No schema migrations are added.
- Focused and relevant regression tests pass.

## 19. Implementation Checklist

1. Add `src/memory/skill_files.py`.
2. Add frontmatter models, parsing, rendering, validation, hashing, and path safety helpers.
3. Add immutable generated file writer.
4. Add active skill index renderer.
5. Add `src/memory/skill_store.py`.
6. Implement version create/read/list APIs.
7. Implement active version transaction.
8. Implement rollback by active pointer movement.
9. Implement disable/archive metadata behavior.
10. Implement `skill_usage_stats` initialization and active version updates.
11. Refactor `src/memory/procedural.py` into a compatibility facade.
12. Preserve legacy function names and return shapes.
13. Refactor `src/startup.py` to create skill directories and preserve existing `.agent/SKILL.md`.
14. Refactor `src/api/server.py` skill endpoints through compatibility facade.
15. Add Phase 8A tests.
16. Run focused Phase 8A tests.
17. Run procedural/API/harness regressions.
18. Run full suite if focused tests pass.

## 20. Filesystem Wiring Check Required After Implementation

Before final implementation approval, verify actual files changed on disk. Do not rely only on the UI edited-files list.

Required checks:

- Verify `src/memory/skill_files.py` exists.
- Verify `src/memory/skill_store.py` exists.
- Verify `src/memory/procedural.py` delegates to the new store.
- Verify `src/startup.py` creates generated/user skill directories without overwriting existing `.agent/SKILL.md`.
- Verify `src/api/server.py` skill endpoints still preserve request and response compatibility.
- Verify generated skill files are under `.agent/skills/generated/<skill_id>/vNNNN/SKILL.md`.
- Verify old version files are not modified after updates.
- Verify user-authored skill files are unchanged.
- Verify `skill_versions` and `skill_usage_stats` are used.
- Verify `skill_candidates` and `procedural_skill_approvals` are not written.
- Verify no schema/migration/retrieval/frontend files were modified.
- Verify procedural, API, and harness regression tests pass.

## 21. Phase 8A Design Boundaries

Phase 8A creates the storage foundation for procedural memory. It does not decide what should become a skill, whether two skills are duplicates, whether a generated skill should be approved, or how skills are retrieved during chat. Those behaviors belong to later phases.

The core invariant is simple: generated procedural memory is no longer a mutable single catalog. It is versioned, inspectable, rollback-capable, and stored as valid `SKILL.md` files without overwriting user-authored work.
