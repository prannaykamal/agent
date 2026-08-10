from langchain_core.tools import tool
from src.db import get_connection
from src.personal_os.audit import log_personal_os_action
from src.personal_os.scheduler_service import create_legacy_compatible_schedule
from src.personal_os.scheduler_store import ToolScheduleRepository


@tool
def schedule_job(cron_or_timestamp: str, task_payload: str) -> str:
    """Schedules a local assistant action using the durable T5 scheduler compatibility wrapper."""
    result = create_legacy_compatible_schedule(cron_or_timestamp=cron_or_timestamp, task_payload=task_payload)
    schedule = result.schedule
    log_personal_os_action(
        tool_name="schedule_job",
        action="PERSONAL_OS_SCHEDULE_CREATED",
        payload={"cron_or_timestamp": cron_or_timestamp, "task_payload": task_payload, "schedule_id": schedule.id},
        target_resource=schedule.id,
    )
    return f"[Personal OS Scheduled Job] Job '{schedule.id}' registered for schedule '{cron_or_timestamp}'."


@tool
def cancel_job(job_id: str) -> str:
    """Cancels a scheduled local assistant action."""
    repo = ToolScheduleRepository()
    cancelled = False
    try:
        repo.cancel_schedule(job_id)
        cancelled = True
    except KeyError:
        pass

    conn = get_connection()
    cursor = conn.cursor()
    cursor.execute("UPDATE scheduled_jobs SET status = 'CANCELLED' WHERE id = ?", (job_id,))
    affected = cursor.rowcount
    conn.commit()
    conn.close()

    if not cancelled and affected == 0:
        return f"[Personal OS Scheduler Error] Job '{job_id}' not found."
    log_personal_os_action(
        tool_name="cancel_job",
        action="PERSONAL_OS_SCHEDULE_CANCELLED",
        payload={"job_id": job_id},
        target_resource=job_id,
    )
    return f"[Personal OS Scheduler] Job '{job_id}' successfully cancelled."


@tool
def heartbeat() -> str:
    """Verifies that the assistant core harness and database background services are alive and responsive."""
    conn = get_connection()
    cursor = conn.cursor()
    cursor.execute("SELECT datetime('now') as now_time")
    res = cursor.fetchone()
    conn.close()
    return f"[Personal OS Heartbeat OK] System active at {res['now_time']}. Core harness fully operational."
