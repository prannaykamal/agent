from __future__ import annotations

import json
import uuid
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Dict, List, Optional

from src.db import get_connection
from src.personal_os.cron_parser import next_cron_run_at, parse_run_at, utc_iso

SCHEDULE_TYPES = {"one_time", "recurring"}
MISSED_POLICIES = {"skip", "run_once", "catch_up_limited"}
SCHEDULE_STATUSES = {"ACTIVE", "PAUSED", "CANCELLED", "COMPLETED"}
RUN_STATUSES = {
    "PENDING", "CLAIMED", "WAITING_FOR_APPROVAL", "RUNNING", "SUCCEEDED",
    "FAILED_RETRYABLE", "FAILED_TERMINAL", "CANCELLED",
}


def create_scheduler_schema(conn) -> None:
    cursor = conn.cursor()
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS tool_schedules (
            id TEXT PRIMARY KEY,
            schedule_type TEXT NOT NULL CHECK(schedule_type IN ('one_time', 'recurring')),
            cron_expression TEXT,
            run_at TEXT,
            timezone TEXT NOT NULL DEFAULT 'UTC',
            next_run_at TEXT,
            last_run_at TEXT,
            missed_run_policy TEXT NOT NULL DEFAULT 'run_once' CHECK(missed_run_policy IN ('skip', 'run_once', 'catch_up_limited')),
            max_catchup_runs INTEGER NOT NULL DEFAULT 1 CHECK(max_catchup_runs >= 0),
            target_tool_id TEXT NOT NULL,
            target_payload_json TEXT NOT NULL DEFAULT '{}',
            approval_policy TEXT NOT NULL DEFAULT 'no_approval_needed',
            status TEXT NOT NULL DEFAULT 'ACTIVE' CHECK(status IN ('ACTIVE', 'PAUSED', 'CANCELLED', 'COMPLETED')),
            created_by TEXT NOT NULL DEFAULT 'system',
            created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
            updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
            CHECK((schedule_type = 'one_time' AND run_at IS NOT NULL) OR (schedule_type = 'recurring' AND cron_expression IS NOT NULL))
        )
    """)
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS tool_schedule_runs (
            id TEXT PRIMARY KEY,
            schedule_id TEXT NOT NULL,
            scheduled_for TEXT NOT NULL,
            claimed_at TEXT,
            started_at TEXT,
            completed_at TEXT,
            status TEXT NOT NULL DEFAULT 'PENDING' CHECK(status IN ('PENDING', 'CLAIMED', 'WAITING_FOR_APPROVAL', 'RUNNING', 'SUCCEEDED', 'FAILED_RETRYABLE', 'FAILED_TERMINAL', 'CANCELLED')),
            attempt_count INTEGER NOT NULL DEFAULT 0 CHECK(attempt_count >= 0),
            approval_request_id TEXT,
            tool_call_id TEXT,
            result_preview TEXT,
            error_json TEXT,
            created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
            updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
            UNIQUE(schedule_id, scheduled_for)
        )
    """)
    cursor.execute("CREATE INDEX IF NOT EXISTS idx_tool_schedules_status_next ON tool_schedules(status, next_run_at)")
    cursor.execute("CREATE INDEX IF NOT EXISTS idx_tool_schedule_runs_schedule ON tool_schedule_runs(schedule_id)")
    cursor.execute("CREATE INDEX IF NOT EXISTS idx_tool_schedule_runs_status ON tool_schedule_runs(status, scheduled_for)")
    conn.commit()


@dataclass(frozen=True)
class ToolScheduleWrite:
    schedule_type: str
    target_tool_id: str
    target_payload: Dict[str, Any]
    timezone: str = "UTC"
    cron_expression: Optional[str] = None
    run_at: Optional[str] = None
    missed_run_policy: Optional[str] = None
    max_catchup_runs: int = 1
    approval_policy: Optional[str] = None
    created_by: str = "user"


@dataclass(frozen=True)
class ToolScheduleRecord:
    id: str
    schedule_type: str
    cron_expression: Optional[str]
    run_at: Optional[str]
    timezone: str
    next_run_at: Optional[str]
    last_run_at: Optional[str]
    missed_run_policy: str
    max_catchup_runs: int
    target_tool_id: str
    target_payload: Dict[str, Any]
    approval_policy: str
    status: str
    created_by: str
    created_at: str
    updated_at: str

    @classmethod
    def from_row(cls, row) -> "ToolScheduleRecord":
        data = dict(row)
        payload = json.loads(data.get("target_payload_json") or "{}")
        return cls(
            id=data["id"],
            schedule_type=data["schedule_type"],
            cron_expression=data.get("cron_expression"),
            run_at=data.get("run_at"),
            timezone=data["timezone"],
            next_run_at=data.get("next_run_at"),
            last_run_at=data.get("last_run_at"),
            missed_run_policy=data["missed_run_policy"],
            max_catchup_runs=int(data["max_catchup_runs"]),
            target_tool_id=data["target_tool_id"],
            target_payload=payload,
            approval_policy=data["approval_policy"],
            status=data["status"],
            created_by=data["created_by"],
            created_at=data["created_at"],
            updated_at=data["updated_at"],
        )

    def to_dict(self, include_payload: bool = True) -> Dict[str, Any]:
        data = self.__dict__.copy()
        data["target_payload"] = self.target_payload if include_payload else _payload_preview(self.target_payload)
        return data


@dataclass(frozen=True)
class ToolScheduleRunRecord:
    id: str
    schedule_id: str
    scheduled_for: str
    claimed_at: Optional[str]
    started_at: Optional[str]
    completed_at: Optional[str]
    status: str
    attempt_count: int
    approval_request_id: Optional[str]
    tool_call_id: Optional[str]
    result_preview: Optional[str]
    error_json: Optional[str]
    created_at: str
    updated_at: str

    @classmethod
    def from_row(cls, row) -> "ToolScheduleRunRecord":
        data = dict(row)
        return cls(
            id=data["id"],
            schedule_id=data["schedule_id"],
            scheduled_for=data["scheduled_for"],
            claimed_at=data.get("claimed_at"),
            started_at=data.get("started_at"),
            completed_at=data.get("completed_at"),
            status=data["status"],
            attempt_count=int(data["attempt_count"]),
            approval_request_id=data.get("approval_request_id"),
            tool_call_id=data.get("tool_call_id"),
            result_preview=data.get("result_preview"),
            error_json=data.get("error_json"),
            created_at=data["created_at"],
            updated_at=data["updated_at"],
        )

    def to_dict(self) -> Dict[str, Any]:
        return self.__dict__.copy()


def canonical_payload(payload: Optional[Dict[str, Any]]) -> str:
    return json.dumps(payload or {}, sort_keys=True, separators=(",", ":"), ensure_ascii=True, default=str)


def _payload_preview(payload: Dict[str, Any]) -> Dict[str, Any]:
    preview: Dict[str, Any] = {}
    for key, value in (payload or {}).items():
        lower = str(key).lower()
        if any(part in lower for part in ("secret", "token", "password", "credential", "authorization", "api_key")):
            preview[key] = "[REDACTED]"
        else:
            text = str(value)
            preview[key] = text[:160] + ("..." if len(text) > 160 else "")
    return preview


def _compute_next_run_at(write: ToolScheduleWrite, now: Any = None) -> tuple[Optional[str], Optional[str]]:
    if write.schedule_type == "one_time":
        run_at = parse_run_at(write.run_at or "", write.timezone)
        return run_at, run_at
    if write.schedule_type == "recurring":
        next_run = next_cron_run_at(write.cron_expression or "", write.timezone, after=now)
        return None, next_run
    raise ValueError(f"Unsupported schedule_type: {write.schedule_type}")


class ToolScheduleRepository:
    def __init__(self, db_path: Optional[Path] = None):
        self.db_path = db_path

    def create_schedule(self, write: ToolScheduleWrite, *, now: Any = None, schedule_id: Optional[str] = None) -> ToolScheduleRecord:
        if write.schedule_type not in SCHEDULE_TYPES:
            raise ValueError("schedule_type must be one_time or recurring")
        missed = write.missed_run_policy or "run_once"
        if missed not in MISSED_POLICIES:
            raise ValueError("Unsupported missed_run_policy")
        if int(write.max_catchup_runs) < 0:
            raise ValueError("max_catchup_runs must be >= 0")
        run_at, next_run_at = _compute_next_run_at(write, now=now)
        sid = schedule_id or f"sched_{uuid.uuid4().hex[:12]}"
        conn = get_connection(self.db_path)
        cursor = conn.cursor()
        cursor.execute(
            """
            INSERT INTO tool_schedules (
                id, schedule_type, cron_expression, run_at, timezone, next_run_at, missed_run_policy,
                max_catchup_runs, target_tool_id, target_payload_json, approval_policy, status, created_by, created_at, updated_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 'ACTIVE', ?, datetime('now'), datetime('now'))
            """,
            (
                sid, write.schedule_type, write.cron_expression, run_at, write.timezone or "UTC", next_run_at,
                missed, int(write.max_catchup_runs), write.target_tool_id, canonical_payload(write.target_payload),
                write.approval_policy or "no_approval_needed", write.created_by or "user",
            ),
        )
        conn.commit()
        conn.close()
        return self.get_schedule(sid)

    def get_schedule(self, schedule_id: str) -> ToolScheduleRecord:
        conn = get_connection(self.db_path)
        cursor = conn.cursor()
        cursor.execute("SELECT * FROM tool_schedules WHERE id = ?", (schedule_id,))
        row = cursor.fetchone()
        conn.close()
        if not row:
            raise KeyError(schedule_id)
        return ToolScheduleRecord.from_row(row)

    def list_schedules(self, status: Optional[str] = None, limit: int = 100) -> List[ToolScheduleRecord]:
        conn = get_connection(self.db_path)
        cursor = conn.cursor()
        safe_limit = max(1, min(int(limit or 100), 500))
        if status:
            cursor.execute("SELECT * FROM tool_schedules WHERE status = ? ORDER BY created_at DESC LIMIT ?", (status, safe_limit))
        else:
            cursor.execute("SELECT * FROM tool_schedules ORDER BY created_at DESC LIMIT ?", (safe_limit,))
        rows = [ToolScheduleRecord.from_row(row) for row in cursor.fetchall()]
        conn.close()
        return rows

    def update_schedule(self, schedule_id: str, updates: Dict[str, Any], *, now: Any = None) -> ToolScheduleRecord:
        current = self.get_schedule(schedule_id)
        payload = updates.get("target_payload", current.target_payload)
        write = ToolScheduleWrite(
            schedule_type=updates.get("schedule_type", current.schedule_type),
            cron_expression=updates.get("cron_expression", current.cron_expression),
            run_at=updates.get("run_at", current.run_at),
            timezone=updates.get("timezone", current.timezone),
            target_tool_id=updates.get("target_tool_id", current.target_tool_id),
            target_payload=payload,
            missed_run_policy=updates.get("missed_run_policy", current.missed_run_policy),
            max_catchup_runs=int(updates.get("max_catchup_runs", current.max_catchup_runs)),
            approval_policy=updates.get("approval_policy", current.approval_policy),
            created_by=current.created_by,
        )
        run_at, next_run_at = _compute_next_run_at(write, now=now)
        status = updates.get("status", current.status)
        if status not in SCHEDULE_STATUSES:
            raise ValueError("Unsupported schedule status")
        conn = get_connection(self.db_path)
        cursor = conn.cursor()
        cursor.execute(
            """
            UPDATE tool_schedules
            SET schedule_type = ?, cron_expression = ?, run_at = ?, timezone = ?, next_run_at = ?,
                missed_run_policy = ?, max_catchup_runs = ?, target_tool_id = ?, target_payload_json = ?,
                approval_policy = ?, status = ?, updated_at = datetime('now')
            WHERE id = ?
            """,
            (
                write.schedule_type, write.cron_expression, run_at, write.timezone, next_run_at,
                write.missed_run_policy or "run_once", write.max_catchup_runs, write.target_tool_id,
                canonical_payload(write.target_payload), write.approval_policy or current.approval_policy,
                status, schedule_id,
            ),
        )
        conn.commit()
        conn.close()
        return self.get_schedule(schedule_id)

    def cancel_schedule(self, schedule_id: str) -> ToolScheduleRecord:
        conn = get_connection(self.db_path)
        cursor = conn.cursor()
        cursor.execute("UPDATE tool_schedules SET status = 'CANCELLED', updated_at = datetime('now') WHERE id = ?", (schedule_id,))
        if cursor.rowcount == 0:
            conn.close()
            raise KeyError(schedule_id)
        cursor.execute("UPDATE tool_schedule_runs SET status = 'CANCELLED', updated_at = datetime('now') WHERE schedule_id = ? AND status IN ('PENDING', 'CLAIMED')", (schedule_id,))
        conn.commit()
        conn.close()
        return self.get_schedule(schedule_id)

    def list_due_schedules(self, now: Any = None, limit: int = 50) -> List[ToolScheduleRecord]:
        now_iso = utc_iso(now)
        conn = get_connection(self.db_path)
        cursor = conn.cursor()
        cursor.execute(
            "SELECT * FROM tool_schedules WHERE status = 'ACTIVE' AND next_run_at IS NOT NULL AND next_run_at <= ? ORDER BY next_run_at ASC LIMIT ?",
            (now_iso, max(1, min(int(limit or 50), 200))),
        )
        rows = [ToolScheduleRecord.from_row(row) for row in cursor.fetchall()]
        conn.close()
        return rows

    def create_or_get_run(self, schedule_id: str, scheduled_for: str) -> ToolScheduleRunRecord:
        conn = get_connection(self.db_path)
        cursor = conn.cursor()
        run_id = f"run_{uuid.uuid4().hex[:12]}"
        cursor.execute(
            """
            INSERT OR IGNORE INTO tool_schedule_runs (id, schedule_id, scheduled_for, status, created_at, updated_at)
            VALUES (?, ?, ?, 'PENDING', datetime('now'), datetime('now'))
            """,
            (run_id, schedule_id, scheduled_for),
        )
        cursor.execute("SELECT * FROM tool_schedule_runs WHERE schedule_id = ? AND scheduled_for = ?", (schedule_id, scheduled_for))
        row = cursor.fetchone()
        conn.commit()
        conn.close()
        return ToolScheduleRunRecord.from_row(row)

    def update_run(self, run_id: str, **updates: Any) -> ToolScheduleRunRecord:
        allowed = {"claimed_at", "started_at", "completed_at", "status", "attempt_count", "approval_request_id", "tool_call_id", "result_preview", "error_json"}
        parts = []
        values = []
        for key, value in updates.items():
            if key not in allowed:
                continue
            if key == "status" and value not in RUN_STATUSES:
                raise ValueError("Unsupported run status")
            parts.append(f"{key} = ?")
            values.append(value)
        parts.append("updated_at = datetime('now')")
        values.append(run_id)
        conn = get_connection(self.db_path)
        cursor = conn.cursor()
        cursor.execute(f"UPDATE tool_schedule_runs SET {', '.join(parts)} WHERE id = ?", tuple(values))
        cursor.execute("SELECT * FROM tool_schedule_runs WHERE id = ?", (run_id,))
        row = cursor.fetchone()
        conn.commit()
        conn.close()
        if not row:
            raise KeyError(run_id)
        return ToolScheduleRunRecord.from_row(row)

    def list_runs(self, schedule_id: Optional[str] = None, status: Optional[str] = None, limit: int = 100) -> List[ToolScheduleRunRecord]:
        clauses = []
        params: list[Any] = []
        if schedule_id:
            clauses.append("schedule_id = ?")
            params.append(schedule_id)
        if status:
            clauses.append("status = ?")
            params.append(status)
        where = " WHERE " + " AND ".join(clauses) if clauses else ""
        params.append(max(1, min(int(limit or 100), 500)))
        conn = get_connection(self.db_path)
        cursor = conn.cursor()
        cursor.execute(f"SELECT * FROM tool_schedule_runs{where} ORDER BY created_at DESC LIMIT ?", tuple(params))
        rows = [ToolScheduleRunRecord.from_row(row) for row in cursor.fetchall()]
        conn.close()
        return rows

    def advance_after_occurrence(self, schedule: ToolScheduleRecord, scheduled_for: str, *, now: Any = None) -> ToolScheduleRecord:
        conn = get_connection(self.db_path)
        cursor = conn.cursor()
        if schedule.schedule_type == "one_time":
            cursor.execute(
                "UPDATE tool_schedules SET last_run_at = ?, next_run_at = NULL, status = 'COMPLETED', updated_at = datetime('now') WHERE id = ?",
                (scheduled_for, schedule.id),
            )
            cursor.execute("UPDATE scheduled_jobs SET status = 'COMPLETED' WHERE id = ?", (schedule.id,))
        else:
            next_run = next_cron_run_at(schedule.cron_expression or "", schedule.timezone, after=scheduled_for)
            cursor.execute(
                "UPDATE tool_schedules SET last_run_at = ?, next_run_at = ?, updated_at = datetime('now') WHERE id = ?",
                (scheduled_for, next_run, schedule.id),
            )
            cursor.execute("UPDATE scheduled_jobs SET status = 'PENDING', cron_or_timestamp = ? WHERE id = ?", (next_run, schedule.id))
        conn.commit()
        conn.close()
        return self.get_schedule(schedule.id)

    def skip_missed(self, schedule: ToolScheduleRecord, *, now: Any = None) -> ToolScheduleRecord:
        if schedule.schedule_type != "recurring":
            return schedule
        next_run = next_cron_run_at(schedule.cron_expression or "", schedule.timezone, after=now)
        conn = get_connection(self.db_path)
        cursor = conn.cursor()
        cursor.execute(
            "UPDATE tool_schedules SET last_run_at = next_run_at, next_run_at = ?, updated_at = datetime('now') WHERE id = ?",
            (next_run, schedule.id),
        )
        conn.commit()
        conn.close()
        return self.get_schedule(schedule.id)

    def mirror_legacy_scheduled_job(self, schedule: ToolScheduleRecord, legacy_task_payload: Optional[str] = None) -> None:
        """Mirror a schedule into the legacy scheduled_jobs table.

        ``legacy_task_payload`` is the caller's original payload text; it is kept
        out of ``target_payload`` because that dict is passed to the tool as arguments.
        """
        legacy_value = schedule.run_at or schedule.cron_expression or schedule.next_run_at or ""
        legacy_payload = legacy_task_payload
        if legacy_payload is None and isinstance(schedule.target_payload, dict):
            legacy_payload = schedule.target_payload.get("legacy_task_payload")
        if legacy_payload is None:
            legacy_payload = json.dumps(schedule.target_payload)
        conn = get_connection(self.db_path)
        cursor = conn.cursor()
        cursor.execute(
            """
            INSERT OR REPLACE INTO scheduled_jobs (id, cron_or_timestamp, task_payload, status, created_at)
            VALUES (?, ?, ?, ?, COALESCE((SELECT created_at FROM scheduled_jobs WHERE id = ?), datetime('now')))
            """,
            (schedule.id, legacy_value, str(legacy_payload), _legacy_status(schedule.status), schedule.id),
        )
        conn.commit()
        conn.close()


def _legacy_status(status: str) -> str:
    if status == "ACTIVE":
        return "PENDING"
    return status
