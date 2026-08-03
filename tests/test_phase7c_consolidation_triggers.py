import pytest

from src.db import init_db
from src.memory.episode_store import StructuredEpisodeRepository, StructuredEpisodeWrite
from src.memory.semantic_candidates import PendingFactCandidateStore, PendingFactCandidateWrite
from src.memory.semantic_consolidation import SemanticConsolidationService


@pytest.fixture
def temp_db(tmp_path, monkeypatch):
    db_file = tmp_path / "phase7c_triggers.db"
    monkeypatch.setattr("src.db.DB_PATH", db_file)
    init_db(db_file)
    return db_file


def _episode(index: int) -> StructuredEpisodeWrite:
    return StructuredEpisodeWrite(
        id=f"episode-{index}",
        session_id="sess",
        title=f"Episode {index}",
        summary="A structured work episode.",
        participants=["User"],
        goals=["Build memory"],
        decisions=[],
        artifacts=[],
        topics=["memory"],
        importance=0.6,
        start_message_id=f"turn-{index}",
        end_message_id=f"turn-{index}",
        source="test",
        source_job_id=f"job-episode-{index}",
    )


def _candidate(index: int) -> PendingFactCandidateWrite:
    return PendingFactCandidateWrite(
        session_id="sess",
        fact=f"Candidate fact {index}",
        category="general",
        confidence=0.7,
        explicit=False,
        source="test",
        source_message_id=f"turn-{index}",
    )


def test_10_structured_episodes_trigger(temp_db):
    repository = StructuredEpisodeRepository(db_path=temp_db)
    for index in range(10):
        repository.append_episode(_episode(index))

    triggers = SemanticConsolidationService(db_path=temp_db).evaluate_triggers("sess")

    episode_trigger = next(trigger for trigger in triggers if trigger.trigger_type == "structured_episode_threshold")
    assert episode_trigger.should_enqueue is True
    assert episode_trigger.reason == "10_structured_episodes"


def test_fewer_than_10_structured_episodes_no_trigger(temp_db):
    repository = StructuredEpisodeRepository(db_path=temp_db)
    for index in range(9):
        repository.append_episode(_episode(index))

    triggers = SemanticConsolidationService(db_path=temp_db).evaluate_triggers("sess")

    episode_trigger = next(trigger for trigger in triggers if trigger.trigger_type == "structured_episode_threshold")
    assert episode_trigger.should_enqueue is False


def test_100_pending_candidates_trigger(temp_db):
    store = PendingFactCandidateStore(db_path=temp_db)
    for index in range(100):
        store.add_candidate(_candidate(index))

    triggers = SemanticConsolidationService(db_path=temp_db).evaluate_triggers("sess")

    candidate_trigger = next(trigger for trigger in triggers if trigger.trigger_type == "pending_candidate_threshold")
    assert candidate_trigger.should_enqueue is True
    assert candidate_trigger.reason == "100_pending_candidates"


def test_fewer_than_100_pending_candidates_no_trigger(temp_db):
    store = PendingFactCandidateStore(db_path=temp_db)
    for index in range(99):
        store.add_candidate(_candidate(index))

    triggers = SemanticConsolidationService(db_path=temp_db).evaluate_triggers("sess")

    candidate_trigger = next(trigger for trigger in triggers if trigger.trigger_type == "pending_candidate_threshold")
    assert candidate_trigger.should_enqueue is False


def test_daily_idle_trigger_is_idempotent_by_date(temp_db):
    service = SemanticConsolidationService(db_path=temp_db)

    first = service.evaluate_triggers("sess", maintenance_date="2026-08-03")[-1]
    second = service.evaluate_triggers("sess", maintenance_date="2026-08-03")[-1]

    assert first.should_enqueue is True
    assert first.trigger_type == "daily_idle"
    assert first.window_key == second.window_key
