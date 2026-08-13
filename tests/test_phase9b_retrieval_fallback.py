from types import SimpleNamespace

from langchain_core.messages import HumanMessage, SystemMessage

from src.harness import graph
from src.memory.retrieval_types import (
    RetrievedMemoryCandidate,
    RetrievalBundle,
    RetrievalProvenance,
    RetrievalRequest,
    RetrievalScore,
    RetrievalSourceResult,
)


def _memory_blocks(messages):
    return [
        message
        for message in messages
        if isinstance(message, SystemMessage) and str(message.content).startswith("[Retrieved Long-Term Memory]")
    ]


def _legacy_success(monkeypatch):
    monkeypatch.setattr(
        graph,
        "search_facts_top_k",
        lambda query, k=3: [{"category": "profile", "fact_text": "User prefers legacy fallback"}],
    )
    monkeypatch.setattr(graph, "search_episodes_fts", lambda query, limit=2: [])
    monkeypatch.setattr(graph, "match_procedural_skills", lambda query: [])


def _plan():
    request = RetrievalRequest(query="what do you remember", session_id="sess", token_budget=200)
    return SimpleNamespace(
        should_retrieve=True,
        retrieval_request=request,
        total_token_budget=200,
        budget_by_kind={"semantic": 200},
    )


def _semantic_candidate():
    return RetrievedMemoryCandidate(
        id="semantic:1",
        memory_kind="semantic",
        title="profile",
        content="User prefers new retrieval",
        token_count=6,
        score=RetrievalScore(raw_score=1, normalized_score=1, rank_score=1),
        provenance=RetrievalProvenance(
            source_name="semantic_facts",
            table_name="facts",
            record_id="1",
            session_id=None,
            created_at="2026-01-01T00:00:00Z",
            metadata={"category": "profile"},
        ),
    )


def test_planner_exception_falls_back_to_legacy_wrappers(monkeypatch):
    monkeypatch.setattr(graph, "build_retrieval_plan", lambda **kwargs: (_ for _ in ()).throw(RuntimeError("planner")))
    _legacy_success(monkeypatch)

    result = graph.node_retrieval_gate({"messages": [HumanMessage(content="what do you remember about me?")], "session_id": "sess"})

    assert result["retrieval_triggered"] is True
    assert "User prefers legacy fallback" in _memory_blocks(result["messages"])[0].content


def test_retriever_exception_falls_back_to_legacy_wrappers(monkeypatch):
    monkeypatch.setattr(graph, "build_retrieval_plan", lambda **kwargs: _plan())
    monkeypatch.setattr(graph, "retrieve_all_sources", lambda request: (_ for _ in ()).throw(RuntimeError("retriever")))
    _legacy_success(monkeypatch)

    result = graph.node_retrieval_gate({"messages": [HumanMessage(content="what do you remember about me?")], "session_id": "sess"})

    assert result["retrieval_triggered"] is True
    assert "Semantic Facts:" in _memory_blocks(result["messages"])[0].content


def test_assembler_exception_falls_back_to_legacy_wrappers(monkeypatch):
    monkeypatch.setattr(graph, "build_retrieval_plan", lambda **kwargs: _plan())
    monkeypatch.setattr(graph, "retrieve_all_sources", lambda request: RetrievalBundle(request=request, candidates=(_semantic_candidate(),)))
    monkeypatch.setattr(graph, "assemble_retrieved_memory_context", lambda bundle, options: (_ for _ in ()).throw(RuntimeError("assembler")))
    _legacy_success(monkeypatch)

    result = graph.node_retrieval_gate({"messages": [HumanMessage(content="what do you remember about me?")], "session_id": "sess"})

    assert result["retrieval_triggered"] is True
    assert "User prefers legacy fallback" in _memory_blocks(result["messages"])[0].content


def test_source_level_failure_does_not_trigger_legacy_fallback_when_candidates_exist(monkeypatch):
    def fail_legacy(*args, **kwargs):
        raise AssertionError("legacy fallback should not run for isolated source errors")

    request = RetrievalRequest(query="what do you remember", session_id="sess", token_budget=200)
    bundle = RetrievalBundle(
        request=request,
        source_results=(
            RetrievalSourceResult("semantic_facts", "semantic", candidates=(_semantic_candidate(),)),
            RetrievalSourceResult("structured_episodes", "episodic", errors=("source failed",)),
        ),
        candidates=(_semantic_candidate(),),
    )
    monkeypatch.setattr(graph, "build_retrieval_plan", lambda **kwargs: _plan())
    monkeypatch.setattr(graph, "retrieve_all_sources", lambda request: bundle)
    monkeypatch.setattr(graph, "search_facts_top_k", fail_legacy)
    monkeypatch.setattr(graph, "search_episodes_fts", fail_legacy)
    monkeypatch.setattr(graph, "match_procedural_skills", fail_legacy)

    result = graph.node_retrieval_gate({"messages": [HumanMessage(content="what do you remember about me?")], "session_id": "sess"})

    assert result["retrieval_triggered"] is True
    assert "User prefers new retrieval" in _memory_blocks(result["messages"])[0].content


def test_legacy_fallback_failure_does_not_fail_chat(monkeypatch):
    def fail(*args, **kwargs):
        raise RuntimeError("boom")

    monkeypatch.setattr(graph, "build_retrieval_plan", fail)
    monkeypatch.setattr(graph, "search_facts_top_k", fail)
    monkeypatch.setattr(graph, "search_episodes_fts", fail)
    monkeypatch.setattr(graph, "match_procedural_skills", fail)
    monkeypatch.setattr(graph, "assemble_pinned_profile", lambda: "")

    result = graph.node_retrieval_gate({"messages": [HumanMessage(content="what do you remember about me?")], "session_id": "sess"})

    assert result["retrieval_triggered"] is False
    assert result["retrieved_memories"] == []
    assert _memory_blocks(result["messages"]) == []


def test_exactly_one_retrieved_memory_block_is_appended(monkeypatch):
    monkeypatch.setattr(graph, "build_retrieval_plan", lambda **kwargs: _plan())
    request = RetrievalRequest(query="what do you remember", session_id="sess", token_budget=200)
    monkeypatch.setattr(graph, "retrieve_all_sources", lambda request: RetrievalBundle(request=request, candidates=(_semantic_candidate(),)))

    result = graph.node_retrieval_gate({"messages": [HumanMessage(content="what do you remember about me?")], "session_id": "sess"})

    assert len(_memory_blocks(result["messages"])) == 1
