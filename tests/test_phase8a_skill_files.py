import pytest

from src.memory.skill_files import (
    SkillFileFrontmatter,
    SkillFileValidationError,
    calculate_skill_content_hash,
    generated_skill_file_path,
    generated_skill_root,
    parse_skill_markdown,
    render_skill_markdown,
    slugify_skill_id,
    user_skill_root,
    validate_generated_skill_path,
    write_immutable_skill_file,
)


def _frontmatter(**overrides):
    data = {
        "schema_version": 1,
        "skill_id": "deploy-staging",
        "version": 1,
        "name": "Deploy Staging",
        "description": "Deploys to staging.",
        "author": "api",
        "namespace": "generated",
        "enabled": True,
        "active": True,
        "created_at": "1970-01-01T00:00:00Z",
        "content_hash": "pending",
        "trigger_keywords": ["deploy", "staging"],
        "preferred_tools": [],
        "tags": [],
    }
    data.update(overrides)
    return SkillFileFrontmatter(**data)


def test_skill_file_path_validation(tmp_path):
    skill_path = tmp_path / "SKILL.md"
    path = generated_skill_file_path("Deploy Staging", 1, skill_path)

    assert path == generated_skill_root(skill_path) / "deploy-staging" / "v0001" / "SKILL.md"
    assert validate_generated_skill_path(path, skill_path) == path.resolve()
    assert slugify_skill_id("Deploy Staging!") == "deploy-staging"


def test_user_path_cannot_be_targeted(tmp_path):
    skill_path = tmp_path / "SKILL.md"
    user_path = user_skill_root(skill_path) / "deploy-staging" / "SKILL.md"

    with pytest.raises(SkillFileValidationError) as exc:
        validate_generated_skill_path(user_path, skill_path)

    assert exc.value.field == "file_path"


def test_immutable_write_refuses_overwrite(tmp_path):
    skill_path = tmp_path / "SKILL.md"
    path = generated_skill_file_path("deploy-staging", 1, skill_path)
    content = render_skill_markdown(_frontmatter(), "1. Deploy the build.")

    write_immutable_skill_file(path, content, skill_path)

    with pytest.raises(SkillFileValidationError):
        write_immutable_skill_file(path, content, skill_path)


def test_frontmatter_render_parse_validation_round_trip():
    content = render_skill_markdown(_frontmatter(), "1. Deploy the build.")

    frontmatter, body = parse_skill_markdown(content)

    assert frontmatter.skill_id == "deploy-staging"
    assert frontmatter.version == 1
    assert frontmatter.trigger_keywords == ["deploy", "staging"]
    assert "# Deploy Staging" in body


def test_content_hash_deterministic():
    first = calculate_skill_content_hash("same content")
    second = calculate_skill_content_hash("same content")
    other = calculate_skill_content_hash("other content")

    assert first == second
    assert first != other


def test_invalid_frontmatter_reports_field():
    content = render_skill_markdown(_frontmatter(namespace="generated"), "1. Deploy.")
    bad = content.replace('namespace: "generated"', 'namespace: "elsewhere"')

    with pytest.raises(SkillFileValidationError) as exc:
        parse_skill_markdown(bad)

    assert exc.value.field == "namespace"
