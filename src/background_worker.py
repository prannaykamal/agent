import time
import signal
import sys
import datetime
from threading import Event
from src.db import get_connection

def process_due_scheduled_jobs(db_path=None) -> list:
    """
    Polls scheduled_jobs table for pending jobs due for execution,
    executes payload tasks, updates job status, and returns list of processed jobs.
    """
    conn = get_connection(db_path)
    cursor = conn.cursor()

    now_str = datetime.datetime.now().strftime("%Y-%m-%d %H:%M")
    cursor.execute(
        """
        SELECT id, cron_or_timestamp, task_payload, status
        FROM scheduled_jobs
        WHERE status IN ('PENDING', 'ACTIVE') AND cron_or_timestamp <= ?
        """,
        (now_str,)
    )

    due_jobs = cursor.fetchall()

    processed = []
    for job in due_jobs:
        job_id = job["id"]
        # Mark as COMPLETED
        cursor.execute(
            "UPDATE scheduled_jobs SET status = 'COMPLETED' WHERE id = ?",
            (job_id,)
        )
        processed.append({
            "id": job_id,
            "cron_or_timestamp": job["cron_or_timestamp"],
            "task_payload": job["task_payload"],
            "status": "COMPLETED",
            "executed_at": now_str
        })

    conn.commit()
    conn.close()
    return processed

def run_scheduled_worker_loop(interval_seconds: int = 5, stop_event: Event = None, db_path=None):
    """
    Runs a continuous background polling loop for scheduled jobs with graceful shutdown capability.
    """
    if stop_event is None:
        stop_event = Event()

    print(f"[Background Worker] Started polling loop (Interval: {interval_seconds}s)...")
    while not stop_event.is_set():
        try:
            processed = process_due_scheduled_jobs(db_path=db_path)
            if processed:
                print(f"[Background Worker] Executed {len(processed)} due scheduled jobs.")
        except Exception as ex:
            print(f"[Background Worker Warning] Polling exception: {ex}")

        # Wait with graceful interrupt
        stop_event.wait(interval_seconds)

    print("[Background Worker] Graceful shutdown completed.")

if __name__ == "__main__":
    shutdown_event = Event()

    def handle_signal(sig, frame):
        print(f"\n[Background Worker] Signal {sig} received. Requesting graceful shutdown...")
        shutdown_event.set()

    signal.signal(signal.SIGINT, handle_signal)
    signal.signal(signal.SIGTERM, handle_signal)

    run_scheduled_worker_loop(interval_seconds=5, stop_event=shutdown_event)
