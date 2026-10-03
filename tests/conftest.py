"""Shared pytest isolation so local .env secrets cannot leak into the suite."""

import pytest

# Direct-provider secrets must not make Telegram/WhatsApp look configured during
# default unit tests. Tests that need a token call monkeypatch.setenv themselves.
_ISOLATED_PROVIDER_ENV = (
    "TELEGRAM_BOT_TOKEN",
    "TELEGRAM_TEST_CHAT_ID",
    "WHATSAPP_API_TOKEN",
    "WHATSAPP_PHONE_NUMBER_ID",
)


@pytest.fixture(autouse=True)
def isolate_direct_provider_env(monkeypatch, tmp_path_factory):
    for key in _ISOLATED_PROVIDER_ENV:
        monkeypatch.delenv(key, raising=False)
    missing_mcp = tmp_path_factory.mktemp("isolated_mcp") / "mcp_config.json"
    monkeypatch.setattr("src.tools.mcp_provider_config.mcp_config_path", lambda: missing_mcp)
    monkeypatch.setattr("src.mcp_gateway.mcp_bridge.MCP_CONFIG_PATH", missing_mcp)
    try:
        monkeypatch.setattr("src.tools.provider_config.mcp_config_path", lambda: missing_mcp)
    except Exception:
        pass
    try:
        from src.tools.mcp_provider_registry import clear_mcp_provider_discovery_cache

        clear_mcp_provider_discovery_cache()
    except Exception:
        pass
    yield
    try:
        from src.tools.mcp_provider_registry import clear_mcp_provider_discovery_cache

        clear_mcp_provider_discovery_cache()
    except Exception:
        pass


class FakeCogneeModule:
    """In-memory stand-in for cognee 1.x: session caches, improve() merges, main-graph search."""

    class SearchType:
        GRAPH_COMPLETION = "GRAPH_COMPLETION"
        RAG_COMPLETION = "RAG_COMPLETION"
        CHUNKS = "CHUNKS"
        SUMMARIES = "SUMMARIES"

    class _Config:
        def __init__(self):
            self.system_root = None
            self.data_root = None

        def system_root_directory(self, path):
            self.system_root = path

        def data_root_directory(self, path):
            self.data_root = path

    class ImproveResult:
        def __init__(self, status="completed", stages=None, rerun_requested=False, error=None):
            self.status = status
            self.stages = stages or []
            self.rerun_requested = rerun_requested
            self.error = error

    __version__ = "fake"

    def __init__(self):
        self.sessions = {}  # session_id -> list of texts
        self.graph = {}  # dataset -> list of texts
        self.remember_calls = []
        self.improve_calls = []
        self.search_calls = []
        self.improve_result = None
        self.config = self._Config()

    async def remember(self, data, dataset_name="main_dataset", *, session_id=None, self_improvement=True, **kwargs):
        self.remember_calls.append({"dataset_name": dataset_name, "session_id": session_id, "self_improvement": self_improvement})
        items = data if isinstance(data, list) else [data]
        if session_id is not None:
            self.sessions.setdefault(session_id, []).extend(items)
        else:
            self.graph.setdefault(dataset_name, []).extend(items)

    async def improve(self, dataset="main_dataset", *, session_ids=None, **kwargs):
        self.improve_calls.append({"dataset": dataset, "session_ids": list(session_ids or [])})
        if self.improve_result is not None:
            return self.improve_result
        for session_id in session_ids or []:
            for text in self.sessions.get(session_id, []):
                if text not in self.graph.setdefault(dataset, []):
                    self.graph[dataset].append(text)
        return self.ImproveResult()

    async def search(self, query_text, query_type=None, datasets=None, top_k=10, only_context=False, **kwargs):
        self.search_calls.append({"query_text": query_text, "query_type": query_type, "datasets": datasets, "top_k": top_k, "only_context": only_context})
        words = {word.strip("?.!,").lower() for word in query_text.split() if len(word) > 3}
        hits = []
        for dataset in datasets or list(self.graph):
            for text in self.graph.get(dataset, []):
                if words & {word.strip("?.!,:").lower() for word in text.split()}:
                    hits.append({"search_result": [text], "dataset_name": dataset})
        return hits[:top_k]

    async def forget(self, everything=False, **kwargs):
        self.sessions.clear()
        self.graph.clear()


class FakeJev:
    """Controllable Jev: set .memory / .tool to the JSON the model should return, or .fail to raise."""

    def __init__(self):
        self.memory = {"should_store": False, "should_retrieve": False}
        self.tool = {"requires_approval": False, "reason": ""}
        self.fail = False
        self.raw = None
        self.calls = []

    def __call__(self, messages):
        import json

        prompt = messages[0]["content"]
        kind = "tool" if "tool calls" in prompt else "memory"
        self.calls.append({"kind": kind, "user": messages[-1]["content"]})
        if self.fail:
            raise TimeoutError("jev endpoint timed out")
        if self.raw is not None:
            return self.raw
        return json.dumps(self.tool if kind == "tool" else self.memory)


@pytest.fixture(autouse=True)
def isolate_cognee_memory(request):
    """Never touch a real cognee install or Jev endpoint; opt in to fakes with fake_cognee / fake_jev."""
    from src.memory.cognee_memory import CogneeMemory, set_cognee_memory
    from src.memory.config import CogneeMemoryConfig, JevConfig
    from src.memory.jev import JevClient, set_jev_client

    if "fake_cognee" not in request.fixturenames:
        set_cognee_memory(CogneeMemory(config=CogneeMemoryConfig(enabled=False)))
    if "fake_jev" not in request.fixturenames:
        set_jev_client(JevClient(config=JevConfig()))
    yield
    set_cognee_memory(None)
    set_jev_client(None)


@pytest.fixture
def fake_cognee(tmp_path):
    from src.memory.cognee_memory import CogneeMemory, set_cognee_memory
    from src.memory.config import CogneeMemoryConfig

    module = FakeCogneeModule()
    memory = CogneeMemory(
        config=CogneeMemoryConfig(data_dir=str(tmp_path / "cognee"), session_idle_timeout_minutes=30),
        cognee_module=module,
    )
    set_cognee_memory(memory)
    return module


@pytest.fixture
def fake_jev():
    from src.memory.config import JevConfig
    from src.memory.jev import JevClient, set_jev_client

    fake = FakeJev()
    set_jev_client(JevClient(config=JevConfig(endpoint="http://jev.test/v1", model="jev-test"), completion_fn=fake))
    return fake
