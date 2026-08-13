import json
from typing import Any, Dict, Mapping, Optional

from src.memory.job_handlers import (
    JobHandlerResult,
    MemoryJobHandler,
    build_default_handler_registry,
)


class MemoryJobRouter:
    def __init__(self, handlers: Optional[Mapping[str, MemoryJobHandler]] = None):
        self.handlers: Dict[str, MemoryJobHandler] = dict(handlers or build_default_handler_registry())

    def dispatch(self, job: Mapping[str, Any]) -> JobHandlerResult:
        job_type = str(job.get("job_type") or "")
        payload_json = job.get("payload_json")
        try:
            payload = json.loads(payload_json if isinstance(payload_json, str) else "{}")
        except Exception as exc:
            return JobHandlerResult(
                success=False,
                result={
                    "handler": "router",
                    "job_type": job_type,
                    "processed": False,
                    "phase": "3B",
                    "message": "Invalid payload JSON",
                    "error_type": type(exc).__name__,
                },
            )

        if not isinstance(payload, dict):
            return JobHandlerResult(
                success=False,
                result={
                    "handler": "router",
                    "job_type": job_type,
                    "processed": False,
                    "phase": "3B",
                    "message": "Payload must decode to a JSON object",
                },
            )

        handler = self.handlers.get(job_type)
        if handler is None:
            return JobHandlerResult(
                success=False,
                result={
                    "handler": "router",
                    "job_type": job_type,
                    "processed": False,
                    "phase": "3B",
                    "message": f"Unknown memory job type: {job_type}",
                },
            )

        return handler.handle(job=job, payload=payload)
