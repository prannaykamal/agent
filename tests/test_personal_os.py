import pytest
from src.db import init_db
from src.personal_os.tasks import create_task, update_task, cancel_task, list_tasks
from src.personal_os.agent_lifecycle import terminate_agent, pause_agent, resume_agent, get_agent_status
from src.personal_os.scheduling import schedule_job, cancel_job, heartbeat
from src.personal_os.concurrency import lock_resource, unlock_resource
from src.personal_os.event_bus import publish_event
from src.personal_os.checkpointing import checkpoint, restore_checkpoint
from src.personal_os.registry import get_all_personal_os_tools

@pytest.fixture
def temp_db(tmp_path, monkeypatch):
    db_file = tmp_path / "test_personal_os.db"
    monkeypatch.setattr("src.db.DB_PATH", db_file)
    init_db(db_file)
    return db_file

def test_task_management_tools(temp_db):
    create_res = create_task.invoke({"title": "Fix bug", "description": "Fix bug #123", "priority": "High"})
    assert "[Personal OS Task Created]" in create_res
    task_id = create_res.split("ID: ")[1].split(" |")[0]

    update_res = update_task.invoke({"task_id": task_id, "status": "IN_PROGRESS", "progress": 75})
    assert "status set to 'IN_PROGRESS'" in update_res

    list_res = list_tasks.invoke({"status_filter": "ALL"})
    assert task_id in list_res

    cancel_res = cancel_task.invoke({"task_id": task_id})
    assert "has been cancelled" in cancel_res

def test_scheduling_and_health_tools(temp_db):
    sched_res = schedule_job.invoke({"cron_or_timestamp": "0 9 * * *", "task_payload": "Daily briefing"})
    assert "[Personal OS Scheduled Job]" in sched_res
    job_id = sched_res.split("Job '")[1].split("' registered")[0]

    cancel_res = cancel_job.invoke({"job_id": job_id})
    assert "successfully cancelled" in cancel_res

    hb_res = heartbeat.invoke({})
    assert "[Personal OS Heartbeat OK]" in hb_res

def test_concurrency_tools(temp_db):
    lock_res1 = lock_resource.invoke({"resource_uri": "file:///d:/agent/state.db"})
    assert "locked successfully" in lock_res1

    lock_res2 = lock_resource.invoke({"resource_uri": "file:///d:/agent/state.db"})
    assert "is currently locked" in lock_res2

    unlock_res = unlock_resource.invoke({"resource_uri": "file:///d:/agent/state.db"})
    assert "unlocked successfully" in unlock_res

def test_event_bus_tools(temp_db):
    pub_res = publish_event.invoke({"topic": "task.completed", "payload": "Task #123 completed"})
    assert "published to topic 'task.completed'" in pub_res




def test_checkpointing_tools(temp_db):
    chk_res = checkpoint.invoke({"task_id": "task_xyz"})
    assert "[Personal OS Checkpoint]" in chk_res
    chk_id = chk_res.split("ID '")[1].split("' for task")[0]

    rest_res = restore_checkpoint.invoke({"checkpoint_id": chk_id})
    assert "[Personal OS Checkpoint Restored]" in rest_res


def test_personal_os_registry():
    tools = get_all_personal_os_tools()
    assert len(tools) == 17
    names = [t.name for t in tools]
    assert "create_task" in names
    assert "spawn_agent" in names
    assert "lock_resource" in names
    assert "publish_event" in names
    assert "checkpoint" in names
    assert "sleep" not in names
    assert "wake" not in names
    assert "subscribe_event" not in names
    assert "acquire_context" not in names
    assert "release_context" not in names

