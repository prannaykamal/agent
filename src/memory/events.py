"""Structured, content-free log events for the memory and Jev routing paths.

Event names are stable so they can be grepped or shipped to a log pipeline:
``memory.store.decision``, ``memory.retrieve.decision``, ``memory.session.write``,
``memory.session.merge``, ``memory.retrieve`` and ``tool.route.decision``.

Callers pass identifiers, decisions, timings and error categories only. Never
pass user text, assistant text, tool arguments or recalled memory content.
"""

import json
import logging
from typing import Any, Optional

logger = logging.getLogger("ivo.memory")

_ALLOWED_TYPES = (str, int, float, bool, type(None))


def error_category(exc: Optional[BaseException]) -> Optional[str]:
    """Coarse, content-free error label (the exception class name)."""
    return type(exc).__name__ if exc is not None else None


def log_memory_event(event: str, *, level: int = logging.INFO, **fields: Any) -> None:
    safe = {key: value for key, value in fields.items() if isinstance(value, _ALLOWED_TYPES)}
    try:
        logger.log(level, "%s %s", event, json.dumps(safe, sort_keys=True, default=str), extra={"event": event, **{f"memory_{k}": v for k, v in safe.items()}})
    except Exception:
        pass
