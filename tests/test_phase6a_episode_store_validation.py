import pytest

from src.memory.episode_store import (
    StructuredEpisodeValidationError,
    StructuredEpisodeWrite,
    validate_structured_episode_write,
)


def _episode(**overrides):
    data = {
        "session_id": "session-1",
        "title": "Episode title",
        "summary": "Episode summary",
        "participants": ["User", "Assistant"],
        "goals": ["Finish design"],
        "decisions": [],
        "artifacts": [],
        "topics": ["Memory"],
        "importance": 0.5,
        "start_message_id": "turn-1",
        "end_message_id": "turn-2",
        "source": "phase6a.test",
    }
    data.update(overrides)
    return StructuredEpisodeWrite(**data)


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("session_id", " "),
        ("title", ""),
        ("summary", "\t"),
        ("start_message_id", ""),
        ("end_message_id", " "),
        ("source", ""),
    ],
)
def test_required_string_fields_must_be_non_empty(field, value):
    with pytest.raises(StructuredEpisodeValidationError) as exc_info:
        validate_structured_episode_write(_episode(**{field: value}))

    assert exc_info.value.field == field
    assert field in str(exc_info.value)


def test_invalid_action_fails_with_field_name():
    with pytest.raises(StructuredEpisodeValidationError) as exc_info:
        validate_structured_episode_write(_episode(action="IGNORE"))

    assert exc_info.value.field == "action"
    assert "CREATE" in str(exc_info.value)


@pytest.mark.parametrize("importance", [-0.01, 1.01, "high"])
def test_importance_must_be_between_zero_and_one(importance):
    with pytest.raises(StructuredEpisodeValidationError) as exc_info:
        validate_structured_episode_write(_episode(importance=importance))

    assert exc_info.value.field == "importance"


@pytest.mark.parametrize("field", ["participants", "goals", "decisions", "artifacts", "topics"])
def test_json_array_fields_must_be_lists(field):
    with pytest.raises(StructuredEpisodeValidationError) as exc_info:
        validate_structured_episode_write(_episode(**{field: "not-a-list"}))

    assert exc_info.value.field == field


@pytest.mark.parametrize("field", ["participants", "goals", "decisions", "artifacts", "topics"])
def test_json_array_items_must_be_strings(field):
    with pytest.raises(StructuredEpisodeValidationError) as exc_info:
        validate_structured_episode_write(_episode(**{field: ["ok", 3]}))

    assert exc_info.value.field == field


@pytest.mark.parametrize("field", ["participants", "topics"])
def test_participants_and_topics_must_not_be_empty_after_normalization(field):
    with pytest.raises(StructuredEpisodeValidationError) as exc_info:
        validate_structured_episode_write(_episode(**{field: [" ", "\t"]}))

    assert exc_info.value.field == field
    assert "at least one" in str(exc_info.value)


def test_whitespace_only_list_values_are_removed_and_strings_normalized():
    validated = validate_structured_episode_write(
        _episode(
            title="  Episode   title  ",
            participants=[" User ", " ", "Assistant"],
            goals=["  Finish   design  ", ""],
            topics=[" Memory  Architecture ", "\t"],
        )
    )

    assert validated.title == "Episode title"
    assert validated.participants == ["User", "Assistant"]
    assert validated.goals == ["Finish design"]
    assert validated.topics == ["Memory Architecture"]


def test_optional_source_job_id_empty_string_normalizes_to_none():
    validated = validate_structured_episode_write(_episode(source_job_id=" "))

    assert validated.source_job_id is None

