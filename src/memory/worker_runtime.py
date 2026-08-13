import os
import sys
from threading import Event, Lock, Thread
from typing import Optional

_STOP = Event()
_LOCK = Lock()
_THREAD: Optional[Thread] = None
_STARTED = False


def should_autostart_memory_worker() -> bool:
    """Start the in-process worker for a live API, never under pytest, never on the chat path."""
    explicit = os.getenv("MEMORY_WORKER_AUTOSTART")
    if explicit is not None and explicit.strip() != "":
        normalized = explicit.strip().lower()
        if normalized in {"1", "true", "yes", "on"}:
            return True
        if normalized in {"0", "false", "no", "off"}:
            return False
    if os.getenv("PYTEST_CURRENT_TEST"):
        return False
    if "pytest" in sys.modules:
        return False
    return True


def start_memory_worker_runtime() -> bool:
    if not should_autostart_memory_worker():
        return False
    from src.memory.worker import run_memory_worker_loop

    global _THREAD, _STARTED
    with _LOCK:
        if _THREAD is not None and _THREAD.is_alive():
            return True
        _STOP.clear()
        _THREAD = Thread(
            target=run_memory_worker_loop,
            kwargs={
                "worker_id": "astra-memory-worker",
                "interval_seconds": 5,
                "stop_event": _STOP,
            },
            name="astra-memory-worker",
            daemon=True,
        )
        _THREAD.start()
        _STARTED = True
        return True


def stop_memory_worker_runtime(timeout_seconds: float = 2.0) -> None:
    global _THREAD, _STARTED
    _STOP.set()
    thread = _THREAD
    if thread is not None and thread.is_alive():
        thread.join(timeout=timeout_seconds)
    with _LOCK:
        _THREAD = None
        _STARTED = False
