from src.memory.observability import (
    redact_observability_payload,
    redact_observability_value,
    safe_json_loads,
    truncate_preview,
)


def test_nested_secrets_are_redacted():
    payload = {
        "id": "job-1",
        "status": "QUEUED",
        "nested": {"api_key": "sk-secret", "access_token": "tok", "password": "pw"},
    }

    redacted = redact_observability_payload(payload)

    assert redacted["id"] == "job-1"
    assert redacted["status"] == "QUEUED"
    assert redacted["nested"]["api_key"] == "[REDACTED]"
    assert redacted["nested"]["access_token"] == "[REDACTED]"
    assert redacted["nested"]["password"] == "[REDACTED]"


def test_raw_prompt_message_and_candidate_text_are_previews():
    payload = {
        "prompt": "p" * 400,
        "message_text": "private user message",
        "candidate_text": "candidate memory text",
    }

    redacted = redact_observability_payload(payload)

    assert redacted["prompt"]["redacted"] is True
    assert len(redacted["prompt"]["preview"]) <= 240
    assert redacted["message_text"]["preview"] == "private user message"
    assert redacted["candidate_text"]["preview"] == "candidate memory text"


def test_hidden_reasoning_and_scratchpad_are_redacted():
    payload = {"chain_of_thought": "hidden", "scratchpad": "hidden", "reasoning_trace": "hidden"}

    redacted = redact_observability_payload(payload)

    assert redacted["chain_of_thought"] == "[REDACTED]"
    assert redacted["scratchpad"] == "[REDACTED]"
    assert redacted["reasoning_trace"] == "[REDACTED]"


def test_safe_structural_fields_preserved_and_helpers_are_deterministic():
    assert redact_observability_value("job_type", "semantic_consolidation") == "semantic_consolidation"
    assert truncate_preview("a" * 300, 12) == "aaaaaaaaa..."
    assert safe_json_loads('{"a": 1}', {}) == {"a": 1}
    assert safe_json_loads("not json", {"fallback": True}) == {"fallback": True}
