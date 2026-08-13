"""In-process pub/sub for live chat loop events (SSE)."""

from __future__ import annotations

import threading
from collections import defaultdict
from contextvars import ContextVar
from queue import Full, Queue
from typing import Any, Dict, Optional

current_run_id: ContextVar[Optional[str]] = ContextVar("chat_run_id", default=None)

_lock = threading.Lock()
_subscribers: Dict[str, list] = defaultdict(list)


def subscribe(run_id: str) -> Queue:
    queue: Queue = Queue(maxsize=256)
    with _lock:
        _subscribers[str(run_id)].append(queue)
    return queue


def unsubscribe(run_id: str, queue: Queue) -> None:
    key = str(run_id)
    with _lock:
        watchers = _subscribers.get(key) or []
        _subscribers[key] = [item for item in watchers if item is not queue]
        if not _subscribers[key]:
            _subscribers.pop(key, None)


def publish(event: Dict[str, Any], *, run_id: Optional[str] = None, session_id: Optional[str] = None) -> None:
    keys = []
    active_run = run_id or current_run_id.get()
    if active_run:
        keys.append(str(active_run))
    if session_id:
        keys.append(f"session:{session_id}")
    if not keys:
        return
    with _lock:
        watchers = []
        for key in keys:
            watchers.extend(list(_subscribers.get(key) or []))
    for watcher in watchers:
        try:
            watcher.put_nowait(event)
        except Full:
            continue
