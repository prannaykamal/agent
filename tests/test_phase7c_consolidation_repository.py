import json
import sqlite3

import pytest

from src.db import init_db
from src.memory.semantic_candidates import PendingFactCandidateStore, PendingFactCandidateWrite
from src.memory.semantic_consolidation import ConsolidationRunRepository


@pytest.fixture
def temp_db(tmp_path, monkeypatch):
    db_file = tmp_path / "phase7c_repository.db"
    monkeypatch.setattr("src.db.DB_PATH", db_file)
    init_db(db_file)
    return db_file


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


def _row(db_path, table):
    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
    try:
        return dict(conn.execute(f"SELECT * FROM {table}").fetchone())
    finally:
        conn.close()


def test_candidate_claiming_and_status_transitions(temp_db):
    store = PendingFactCandidateStore(db_path=temp_db)
    first = store.add_candidate(_candidate(1))
    second = store.add_candidate(_candidate(2))

    claimed = store.claim_pending_batch(session_id="sess", batch_id="run-1", limit=1)

    assert [record.id for record in claimed] == [first.id]
    assert store.get_by_id(first.id).status == "IN_CONSOLIDATION"
    assert store.get_by_id(second.id).status == "PENDING"

    store.update_status(first.id, "PROMOTED", metadata_update={"fact_id": "1"}, processed=True)
    promoted = store.get_by_id(first.id)
    assert promoted.status == "PROMOTED"
    assert promoted.processed_at is not None
    assert promoted.metadata["fact_id"] == "1"


def test_update_status_many_and_recovery(temp_db):
    store = PendingFactCandidateStore(db_path=temp_db)
    records = [store.add_candidate(_candidate(index)) for index in range(3)]
    store.claim_pending_batch(session_id="sess", batch_id="run-stale", limit=3)

    recovered = store.recover_stale_in_consolidation(batch_id="run-stale")

    assert recovered == 3
    assert [store.get_by_id(record.id).status for record in records] == ["PENDING", "PENDING", "PENDING"]

    store.update_status_many([record.id for record in records[:2]], "DEFERRED", processed=True)
    assert [store.get_by_id(record.id).status for record in records[:2]] == ["DEFERRED", "DEFERRED"]


def test_consolidation_runs_status_transitions(temp_db):
    repository = ConsolidationRunRepository(db_path=temp_db)

    run = repository.create_run(
        run_id="run-1",
        trigger_type="manual",
        input_refs={"session_id": "sess", "candidate_ids": ["c1"]},
        source_job_id="job-1",
    )
    same = repository.create_run(
        run_id="run-other",
        trigger_type="manual",
        input_refs={"session_id": "sess"},
        source_job_id="job-1",
    )

    assert run.id == "run-1"
    assert same.id == run.id
    assert run.status == "RUNNING"

    finished = repository.mark_finished(
        run.id,
        status="SUCCEEDED",
        output_refs={"fact_ids": ["1"]},
        metrics={"promoted_candidate_count": 1},
    )

    assert finished.status == "SUCCEEDED"
    assert finished.output_refs["fact_ids"] == ["1"]
    assert finished.metrics["promoted_candidate_count"] == 1
    assert _row(temp_db, "consolidation_runs")["status"] == "SUCCEEDED"
    assert json.loads(_row(temp_db, "consolidation_runs")["input_refs_json"])["candidate_ids"] == ["c1"]
