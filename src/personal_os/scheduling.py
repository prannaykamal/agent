import uuid
from langchain_core.tools import tool
from src.db import get_connection
from src.personal_os.audit import log_personal_os_action

@tool
def schedule_job(cron_or_timestamp: str, task_payload: str) -> str:
    """Schedules a task payload to execute at a specified timestamp or cron expression."""
    job_id = f"job_{uuid.uuid4().hex[:8]}"
    conn = get_connection()
    cursor = conn.cursor()
    cursor.execute(
        """
        INSERT INTO scheduled_jobs (id, cron_or_timestamp, task_payload, status, created_at)
        VALUES (?, ?, ?, 'PENDING', datetime('now'))
        """,
        (job_id, cron_or_timestamp, task_payload)
    )

    conn.commit()
    conn.close()
    log_personal_os_action(
        tool_name="schedule_job",
        action="PERSONAL_OS_SCHEDULE_CREATED",
        payload={"cron_or_timestamp": cron_or_timestamp, "task_payload": task_payload},
        target_resource=job_id,
    )
    return f"[Personal OS Scheduled Job] Job '{job_id}' registered for schedule '{cron_or_timestamp}'."

@tool
def cancel_job(job_id: str) -> str:
    """Cancels a scheduled background job."""
    conn = get_connection()
    cursor = conn.cursor()
    cursor.execute(
        """
        UPDATE scheduled_jobs
        SET status = 'CANCELLED'
        WHERE id = ?
        """,
        (job_id,)
    )
    affected = cursor.rowcount
    conn.commit()
    conn.close()

    if affected == 0:
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
