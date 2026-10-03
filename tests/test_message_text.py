from langchain_core.messages import AIMessage

from src.harness.message_text import content_text, message_text


def test_plain_string_content_is_unchanged():
    assert content_text("pong") == "pong"
    assert content_text(None) == ""


def test_gemini_content_blocks_keep_only_text():
    content = [
        {"type": "thinking", "thinking": "hidden reasoning"},
        {"type": "text", "text": "po", "extras": {"signature": "EuMCCuAC..."}},
        {"type": "text", "text": "ng"},
        "!",
    ]

    assert content_text(content) == "pong!"
    assert message_text(AIMessage(content=content)) == "pong!"


def test_chat_api_returns_plain_text_for_block_content(monkeypatch, tmp_path):
    from fastapi.testclient import TestClient

    from src.api.server import app
    from src.db import get_connection, init_db

    db_file = tmp_path / "blocks.db"
    monkeypatch.setattr("src.db.DB_PATH", db_file)
    init_db(db_file)

    class BlockLLM:
        def bind_tools(self, tools):
            return self

        def invoke(self, messages):
            return AIMessage(content=[{"type": "text", "text": "pong", "extras": {"signature": "secret-signature"}}])

    monkeypatch.setattr("src.harness.graph.get_primary_llm", lambda provider=None, model_name=None: (BlockLLM(), 128000))

    data = TestClient(app).post("/api/chat", json={"message": "Reply with pong", "session_id": "blocks"}).json()

    assert data["response"] == "pong"
    conn = get_connection(db_file)
    stored = [row[0] for row in conn.execute("SELECT content FROM raw_turns WHERE sender = 'assistant'")]
    conn.close()
    assert stored == ["pong"]
