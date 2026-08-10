import time
import signal
from threading import Event
from src.personal_os.scheduler_worker import process_due_schedules_once, process_legacy_due_scheduled_jobs


def process_due_scheduled_jobs(db_path=None) -> list:
    """
    Compatibility wrapper for the T5 durable scheduler.

    Processes new tool_schedules first, then legacy scheduled_jobs rows that contain
    parseable one-time timestamps. Cron expressions are no longer compared to
    timestamps lexicographically.
    """
    typed_results = process_due_schedules_once(db_path=db_path)
    processed = []
    for item in typed_results:
        processed.append({
            "id": item.get("schedule_id"),
            "run_id": item.get("run_id"),
            "status": "COMPLETED" if item.get("status") == "SUCCEEDED" else item.get("status"),
            "target_tool_id": item.get("target_tool_id"),
            "scheduled_for": item.get("scheduled_for"),
            "message": item.get("message", ""),
        })
    processed.extend(process_legacy_due_scheduled_jobs(db_path=db_path))
    return processed


def run_scheduled_worker_loop(interval_seconds: int = 5, stop_event: Event = None, db_path=None):
    """Runs an explicit scheduler polling loop. It is not auto-started by app/chat startup."""
    if stop_event is None:
        stop_event = Event()

    print(f"[Scheduler Worker] Started explicit polling loop (Interval: {interval_seconds}s)...")
    while not stop_event.is_set():
        try:
            processed = process_due_scheduled_jobs(db_path=db_path)
            if processed:
                print(f"[Scheduler Worker] Processed {len(processed)} due schedule run(s).")
        except Exception as ex:
            print(f"[Scheduler Worker Warning] Polling exception: {ex}")

        stop_event.wait(interval_seconds)

    print("[Scheduler Worker] Graceful shutdown completed.")


if __name__ == "__main__":
    shutdown_event = Event()

    def handle_signal(sig, frame):
        print(f"\n[Scheduler Worker] Signal {sig} received. Requesting graceful shutdown...")
        shutdown_event.set()

    signal.signal(signal.SIGINT, handle_signal)
    signal.signal(signal.SIGTERM, handle_signal)

    run_scheduled_worker_loop(interval_seconds=5, stop_event=shutdown_event)
