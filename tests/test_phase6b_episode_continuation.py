from src.memory.episode_continuation import decide_episode_continuation, tokenize_for_episode_similarity
from src.memory.episode_detector import EpisodeSourceWindow
from src.memory.episode_store import StructuredEpisodeRecord
from src.memory.summary_blocks import RawTurnRecord


def _turn(content):
    return RawTurnRecord(
        id="t1",
        session_id="sess",
        sender="user",
        content=content,
        token_count=10,
        created_at="2026-08-03 10:00:00",
    )


def _window():
    return EpisodeSourceWindow(
        session_id="sess",
        turn_ids=["t1"],
        start_message_id="t1",
        end_message_id="t1",
        token_count=10,
        user_text_hash=None,
        assistant_text_hash=None,
        summary_block_ids=[],
        source_text_mode="raw_turns",
    )


def _episode(episode_id, title="deploy approval", topics=None):
    return StructuredEpisodeRecord(
        id=episode_id,
        session_id="sess",
        title=title,
        summary=f"{title} deploy approval",
        participants=["User", "Assistant"],
        goals=["deploy approval"],
        decisions=["deploy approval"],
        artifacts=[],
        topics=topics or ["deploy", "approval"],
        importance=0.8,
        start_message_id="old-1",
        end_message_id="old-2",
        source="test",
        action="CREATE",
        parent_episode_id=None,
        source_job_id=f"job-{episode_id}",
        search_text=title,
        created_at=f"2026-08-03 09:00:0{episode_id[-1]}",
        updated_at=None,
    )


def test_tokenizer_is_deterministic_and_filters_stopwords():
    assert tokenize_for_episode_similarity("This is about Deploy, deploy approval!") == {"deploy", "approval"}


def test_no_existing_episodes_defaults_to_create():
    decision = decide_episode_continuation(
        source_window=_window(),
        raw_turns=[_turn("deploy approval")],
        existing_episodes=[],
    )

    assert decision.action == "CREATE"
    assert decision.parent_episode_id is None


def test_weak_similarity_defaults_to_create():
    decision = decide_episode_continuation(
        source_window=_window(),
        raw_turns=[_turn("totally different garden planning")],
        existing_episodes=[_episode("episode-1")],
    )

    assert decision.action == "CREATE"


def test_strong_single_similarity_chooses_update():
    decision = decide_episode_continuation(
        source_window=_window(),
        raw_turns=[_turn("deploy approval deploy approval")],
        existing_episodes=[_episode("episode-1")],
    )

    assert decision.action == "UPDATE"
    assert decision.parent_episode_id == "episode-1"


def test_two_related_episodes_choose_merge():
    decision = decide_episode_continuation(
        source_window=_window(),
        raw_turns=[_turn("deploy approval rollback checklist deploy approval")],
        existing_episodes=[
            _episode("episode-1", "deploy approval"),
            _episode("episode-2", "rollback checklist", topics=["rollback", "checklist"]),
        ],
    )

    assert decision.action == "MERGE"
    assert decision.parent_episode_id in {"episode-1", "episode-2"}
    assert len(decision.related_episode_ids) >= 2


def test_split_requires_explicit_marker_and_parent_similarity():
    decision = decide_episode_continuation(
        source_window=_window(),
        raw_turns=[_turn("new topic: deploy approval should be split")],
        existing_episodes=[_episode("episode-1")],
    )

    assert decision.action == "SPLIT"
    assert decision.parent_episode_id == "episode-1"


def test_no_split_marker_never_chooses_split():
    decision = decide_episode_continuation(
        source_window=_window(),
        raw_turns=[_turn("deploy approval should continue")],
        existing_episodes=[_episode("episode-1")],
    )

    assert decision.action != "SPLIT"


def test_continuation_does_not_call_llms(monkeypatch):
    def fail(*args, **kwargs):
        raise AssertionError("continuation must not use LLMs")

    monkeypatch.setattr("src.harness.models.get_secondary_llm", fail)
    monkeypatch.setattr("src.harness.llm_router.resolve_secondary_llm", fail)

    decision = decide_episode_continuation(
        source_window=_window(),
        raw_turns=[_turn("deploy approval")],
        existing_episodes=[_episode("episode-1")],
    )

    assert decision.action in {"CREATE", "UPDATE", "MERGE", "SPLIT"}

