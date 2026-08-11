import json

from src.tools.observability import redact_observability_payload, redact_observability_value, safe_json_loads, truncate_preview


def test_t9_redacts_nested_secrets_and_tokens():
    payload = {
        "api_key": "abc",
        "nested": {"access_token": "def", "safe_id": "id_123"},
        "items": [{"password": "pw"}],
    }
    redacted = redact_observability_value(payload)
    assert redacted["api_key"] == "[REDACTED]"
    assert redacted["nested"]["access_token"] == "[REDACTED]"
    assert redacted["nested"]["safe_id"] == "id_123"
    assert redacted["items"][0]["password"] == "[REDACTED]"


def test_t9_redacts_hidden_reasoning_and_previews_messages():
    payload = {
        "chain_of_thought": "do not show",
        "scratchpad": "private",
        "reasoning": "x" * 300,
        "message_body": "hello world" * 50,
    }
    redacted = redact_observability_value(payload, preview_limit=40)
    assert redacted["chain_of_thought"] == "[REDACTED]"
    assert redacted["scratchpad"] == "[REDACTED]"
    assert redacted["reasoning"]["truncated"] is True
    assert redacted["message_body"]["truncated"] is True
    assert len(redacted["message_body"]["preview"]) <= 43


def test_t9_safe_json_and_payload_redaction():
    raw = json.dumps({"authorization": "Bearer abc", "body": "secret body" * 40, "tool_id": "x"})
    loaded = safe_json_loads(raw)
    redacted = redact_observability_payload(raw, preview_limit=30)
    assert loaded["tool_id"] == "x"
    assert redacted["authorization"] == "[REDACTED]"
    assert redacted["body"]["truncated"] is True
    assert truncate_preview("abcd", limit=10) == "abcd"