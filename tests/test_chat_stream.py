import json

from fastapi.testclient import TestClient
from langchain_core.messages import AIMessage

from src.api.server import app
from src.db import init_db
from src.harness.llm_router import LLMRouteResult, LLMSelector


client = TestClient(app)


class DeterministicStreamLLM:
    def bind_tools(self, tools, **kwargs):
        return self

    def invoke(self, messages):
        return AIMessage(content="Streamed hello from Ivo.")


def test_chat_stream_emits_steps_then_finished(tmp_path, monkeypatch):
    db_file = tmp_path / "chat_stream.db"
    monkeypatch.setattr("src.db.DB_PATH", db_file)
    monkeypatch.setattr("src.config.MEMORY_PATH", tmp_path / "MEMORY.md")
    init_db(db_file)
    fake = DeterministicStreamLLM()
    selector = LLMSelector(
        role="primary",
        provider="test",
        model_name="deterministic-stream",
        temperature=0.0,
        context_window=4096,
        source="test",
    )
    route = LLMRouteResult(selector=selector, llm=fake, available=True, fallback_used=False, error=None)
    monkeypatch.setattr("src.harness.graph.resolve_primary_llm", lambda **kwargs: route)
    monkeypatch.setattr("src.harness.graph.get_primary_llm", lambda **kwargs: (fake, 4096))
    monkeypatch.setattr("src.harness.graph.get_registered_tools", lambda: ([], {}))

    events = []
    with client.stream(
        "POST",
        "/api/chat/stream",
        json={"message": "Hello stream", "session_id": "sess_stream_ui"},
    ) as response:
        assert response.status_code == 200
        assert "text/event-stream" in response.headers.get("content-type", "")
        for line in response.iter_lines():
            if not line.startswith("data:"):
                continue
            events.append(json.loads(line[5:].strip()))

    types = [event.get("type") or event.get("step_type") for event in events]
    assert "run_started" in types
    assert "step" in types
    assert "run_finished" in types
    finished = next(event for event in events if event.get("type") == "run_finished")
    assert finished["response"] == "Streamed hello from Ivo."
    step_types = [event.get("step_type") for event in events if event.get("type") == "step"]
    assert "USER_INPUT" in step_types
    assert "LLM_STARTED" in step_types
    assert "FINAL_RESPONSE" in step_types


def test_chat_cockpit_shows_activity_and_stream_endpoint():
    text = open("frontend/src/components/ChatCockpit.jsx", encoding="utf-8").read()
    assert "/api/chat/stream" in text
    assert "Activity" in text
    assert "Working…" not in text
    assert "Stop" in text
