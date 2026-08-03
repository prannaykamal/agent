from datetime import datetime, timedelta

from langchain_core.messages import AIMessage, HumanMessage

from src.memory.episode_detector import EpisodeDetectorConfig, detect_episode_trigger
from src.memory.episode_store import StructuredEpisodeRecord
from src.memory.summary_blocks import RawTurnRecord


def _turn(turn_id, sender, content, tokens=10, created_at="2026-08-03 10:00:00"):
    return RawTurnRecord(
        id=turn_id,
        session_id="sess",
        sender=sender,
        content=content,
        token_count=tokens,
        created_at=created_at,
    )


def _episode(start="t1", end="t2"):
    return StructuredEpisodeRecord(
        id="episode-existing",
        session_id="sess",
        title="Existing deployment episode",
        summary="Deployment approval was discussed.",
        participants=["User", "Assistant"],
        goals=["Deploy safely"],
        decisions=["Use approvals"],
        artifacts=[],
        topics=["Deployment"],
        importance=0.7,
        start_message_id=start,
        end_message_id=end,
        source="test",
        action="CREATE",
        parent_episode_id=None,
        source_job_id="job-existing",
        search_text="deployment approval",
        created_at="2026-08-03 09:00:00",
        updated_at=None,
    )


def test_explicit_remember_trigger_selects_latest_pair():
    raw_turns = [
        _turn("t1", "user", "Earlier context"),
        _turn("t2", "assistant", "Earlier reply"),
        _turn("t3", "user", "Please remember that deploys need approval"),
        _turn("t4", "assistant", "Got it"),
    ]

    result = detect_episode_trigger(
        state={"session_id": "sess", "messages": [HumanMessage(content="Please remember that deploys need approval"), AIMessage(content="Got it")]},
        raw_turns=raw_turns,
        existing_episodes=[],
    )

    assert result.should_enqueue is True
    assert result.primary_reason == "explicit_memory_request"
    assert result.source_window is not None
    assert result.source_window.turn_ids == ["t2", "t3", "t4"]


def test_ordinary_turn_no_trigger():
    result = detect_episode_trigger(
        state={"session_id": "sess", "messages": [HumanMessage(content="Hello"), AIMessage(content="Hi")]},
        raw_turns=[_turn("t1", "user", "Hello"), _turn("t2", "assistant", "Hi")],
        existing_episodes=[],
    )

    assert result.should_enqueue is False
    assert result.primary_reason is None


def test_trimming_task_and_workflow_triggers():
    raw_turns = [_turn("t1", "user", "A"), _turn("t2", "assistant", "B")]

    assert detect_episode_trigger(state={"session_id": "sess", "trimming_occurred": True}, raw_turns=raw_turns, existing_episodes=[]).primary_reason == "trimming_occurred"
    assert detect_episode_trigger(state={"session_id": "sess", "task_completed": True}, raw_turns=raw_turns, existing_episodes=[]).primary_reason == "task_completed"
    assert detect_episode_trigger(state={"session_id": "sess", "workflow_finished": True}, raw_turns=raw_turns, existing_episodes=[]).primary_reason == "workflow_finished"


def test_idle_timeout_trigger_at_threshold():
    previous = datetime(2026, 8, 3, 10, 0, 0)
    latest = previous + timedelta(seconds=2700)
    raw_turns = [
        _turn("t1", "assistant", "Previous", created_at=previous.strftime("%Y-%m-%d %H:%M:%S")),
        _turn("t2", "user", "After a pause", created_at=latest.strftime("%Y-%m-%d %H:%M:%S")),
        _turn("t3", "assistant", "Welcome back", created_at=latest.strftime("%Y-%m-%d %H:%M:%S")),
    ]

    result = detect_episode_trigger(state={"session_id": "sess"}, raw_turns=raw_turns, existing_episodes=[])

    assert result.should_enqueue is True
    assert result.primary_reason == "idle_timeout"


def test_long_conversation_token_trigger_and_source_cap():
    raw_turns = [_turn(f"t{i}", "user" if i % 2 else "assistant", f"turn {i}", tokens=10000) for i in range(1, 8)]

    result = detect_episode_trigger(
        state={"session_id": "sess"},
        raw_turns=raw_turns,
        existing_episodes=[],
        config=EpisodeDetectorConfig(max_source_turns=3),
    )

    assert result.primary_reason == "long_conversation"
    assert result.source_window is not None
    assert result.source_window.turn_ids == ["t1", "t2", "t3"]


def test_reason_priority_is_deterministic():
    raw_turns = [_turn("t1", "user", "Please remember this after trimming"), _turn("t2", "assistant", "OK")]

    result = detect_episode_trigger(
        state={"session_id": "sess", "messages": [HumanMessage(content="Please remember this after trimming")], "trimming_occurred": True, "task_completed": True},
        raw_turns=raw_turns,
        existing_episodes=[],
    )

    assert result.reasons == ["explicit_memory_request", "trimming_occurred", "task_completed"]
    assert result.primary_reason == "explicit_memory_request"


def test_source_window_excludes_already_covered_structured_episode_span():
    raw_turns = [
        _turn("t1", "user", "covered"),
        _turn("t2", "assistant", "covered"),
        _turn("t3", "user", "Please remember this new part"),
        _turn("t4", "assistant", "OK"),
    ]

    result = detect_episode_trigger(
        state={"session_id": "sess", "messages": [HumanMessage(content="Please remember this new part")]},
        raw_turns=raw_turns,
        existing_episodes=[_episode("t1", "t2")],
    )

    assert result.source_window is not None
    assert result.source_window.turn_ids == ["t3", "t4"]


def test_detector_does_not_call_llms(monkeypatch):
    def fail(*args, **kwargs):
        raise AssertionError("detector must not use LLMs")

    monkeypatch.setattr("src.harness.models.get_secondary_llm", fail)
    monkeypatch.setattr("src.harness.llm_router.resolve_secondary_llm", fail)

    result = detect_episode_trigger(
        state={"session_id": "sess", "messages": [HumanMessage(content="Please remember this")]},
        raw_turns=[_turn("t1", "user", "Please remember this"), _turn("t2", "assistant", "OK")],
        existing_episodes=[],
    )

    assert result.should_enqueue is True

