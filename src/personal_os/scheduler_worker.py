from __future__ import annotations

import json
import uuid
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Dict, List, Optional

from src.db import get_connection
from src.hitl.approval_engine import create_approval_request
from src.personal_os.cron_parser import ensure_aware_utc, parse_run_at, utc_iso
from src.personal_os.scheduler_policy import decide_scheduler_execution
from src.personal_os.scheduler_service import occurrences_due_for_schedule
from src.personal_os.scheduler_store import ToolScheduleRecord, ToolScheduleRepository, ToolScheduleRunRecord


@dataclass(frozen=True)
class SchedulerRunResult:
    schedule_id: str
    run_id: str
    scheduled_for: str
    status: str
    target_tool_id: str
    message: str
    approval_request_id: Optional[str] = None

    def to_dict(self) -> Dict[str, Any]:
        return self.__dict__.copy()


def _preview(value: Any, limit: int = 500) -> str:
    text = str(value)
    return text[:limit] + ("..." if len(text) > limit else "")


def _record_tool_execution(schedule: ToolScheduleRecord, run: ToolScheduleRunRecord, result: str, *, db_path: Optional[Path] = None) -> str:
    call_id = f"tc_sched_{uuid.uuid4().hex[:10]}"
    result_id = f"tr_sched_{uuid.uuid4().hex[:10]}"
    conn = get_connection(db_path)
    cursor = conn.cursor()
    cursor.execute(
        "INSERT INTO tool_calls (id, session_id, tool_name, tool_args, status, created_at) VALUES (?, ?, ?, ?, 'EXECUTED', datetime('now'))",
        (call_id, f"schedule:{schedule.id}", schedule.target_tool_id, json.dumps(schedule.target_payload, sort_keys=True)),
    )
    cursor.execute(
        "INSERT INTO tool_results (id, tool_call_id, session_id, tool_name, result_content, status, created_at) VALUES (?, ?, ?, ?, ?, 'SUCCESS', datetime('now'))",
        (result_id, call_id, f"schedule:{schedule.id}", schedule.target_tool_id, _preview(result)),
    )
    conn.commit()
    conn.close()
    return call_id


def _invoke_direct_tool(schedule: ToolScheduleRecord) -> str:
    from src.harness.graph import get_registered_tools

    _, tool_map = get_registered_tools()
    tool = tool_map.get(schedule.target_tool_id)
    if tool is None:
        raise KeyError(f"Scheduled target tool '{schedule.target_tool_id}' is not available")
    return str(tool.invoke(schedule.target_payload or {}))


def _process_run(schedule: ToolScheduleRecord, run: ToolScheduleRunRecord, *, db_path: Optional[Path] = None, now: Any = None) -> SchedulerRunResult:
    repo = ToolScheduleRepository(db_path)
    now_iso = utc_iso(now)
    decision = decide_scheduler_execution(schedule.target_tool_id, schedule.target_payload)
    if decision.approval_policy == "blocked":
        updated = repo.update_run(
            run.id,
            status="FAILED_TERMINAL",
            completed_at=now_iso,
            error_json=json.dumps({"error": decision.reason}, sort_keys=True),
        )
        repo.advance_after_occurrence(schedule, run.scheduled_for, now=now)
        return SchedulerRunResult(schedule.id, updated.id, updated.scheduled_for, updated.status, schedule.target_tool_id, decision.reason)

    if decision.requires_approval:
        approval = create_approval_request(
            session_id=f"schedule:{schedule.id}",
            tool_name=schedule.target_tool_id,
            tool_args=schedule.target_payload,
            reason=f"Scheduled action requires approval before execution for schedule {schedule.id} at {run.scheduled_for}.",
            idempotency_key=f"sched:{schedule.id}:{run.scheduled_for}:{schedule.target_tool_id}",
            db_path=db_path,
        )
        updated = repo.update_run(
            run.id,
            status="WAITING_FOR_APPROVAL",
            approval_request_id=approval.get("request_id") or approval.get("id"),
            claimed_at=now_iso,
        )
        repo.advance_after_occurrence(schedule, run.scheduled_for, now=now)
        return SchedulerRunResult(
            schedule.id,
            updated.id,
            updated.scheduled_for,
            updated.status,
            schedule.target_tool_id,
            "Scheduled action is waiting for HITL approval; no target tool execution occurred.",
            approval_request_id=updated.approval_request_id,
        )

    repo.update_run(run.id, status="RUNNING", claimed_at=now_iso, started_at=now_iso, attempt_count=run.attempt_count + 1)
    try:
        result = _invoke_direct_tool(schedule)
        call_id = _record_tool_execution(schedule, run, result, db_path=db_path)
        updated = repo.update_run(
            run.id,
            status="SUCCEEDED",
            completed_at=now_iso,
            tool_call_id=call_id,
            result_preview=_preview(result),
        )
        repo.advance_after_occurrence(schedule, run.scheduled_for, now=now)
        return SchedulerRunResult(schedule.id, updated.id, updated.scheduled_for, updated.status, schedule.target_tool_id, _preview(result))
    except Exception as exc:
        attempts = run.attempt_count + 1
        status = "FAILED_RETRYABLE" if attempts < 3 else "FAILED_TERMINAL"
        updated = repo.update_run(
            run.id,
            status=status,
            attempt_count=attempts,
            completed_at=now_iso,
            error_json=json.dumps({"error": str(exc)}, sort_keys=True),
        )
        if status == "FAILED_TERMINAL":
            repo.advance_after_occurrence(schedule, run.scheduled_for, now=now)
        return SchedulerRunResult(schedule.id, updated.id, updated.scheduled_for, updated.status, schedule.target_tool_id, str(exc))


def process_due_tool_schedules(*, db_path: Optional[Path] = None, now: Any = None, limit: int = 50) -> List[Dict[str, Any]]:
    repo = ToolScheduleRepository(db_path)
    results: List[Dict[str, Any]] = []
    now_dt = ensure_aware_utc(now)
    for schedule in repo.list_due_schedules(now=now_dt, limit=limit):
        if schedule.missed_run_policy == "skip" and schedule.schedule_type == "recurring":
            occurrences = occurrences_due_for_schedule(schedule, now=now_dt)
            if not occurrences:
                repo.skip_missed(schedule, now=now_dt)
                continue
        else:
            occurrences = occurrences_due_for_schedule(schedule, now=now_dt)
        for scheduled_for in occurrences:
            run = repo.create_or_get_run(schedule.id, scheduled_for)
            if run.status != "PENDING":
                continue
            results.append(_process_run(schedule, run, db_path=db_path, now=now_dt).to_dict())
            schedule = repo.get_schedule(schedule.id)
    return results


def process_retryable_schedule_runs(*, db_path: Optional[Path] = None, now: Any = None, limit: int = 25) -> List[Dict[str, Any]]:
    repo = ToolScheduleRepository(db_path)
    results: List[Dict[str, Any]] = []
    for run in repo.list_runs(status="FAILED_RETRYABLE", limit=limit):
        if run.attempt_count >= 3:
            repo.update_run(run.id, status="FAILED_TERMINAL", completed_at=utc_iso(now))
            continue
        try:
            schedule = repo.get_schedule(run.schedule_id)
        except KeyError:
            continue
        results.append(_process_run(schedule, run, db_path=db_path, now=now).to_dict())
    return results


def process_due_schedules_once(*, db_path: Optional[Path] = None, now: Any = None, limit: int = 50) -> List[Dict[str, Any]]:
    return process_retryable_schedule_runs(db_path=db_path, now=now, limit=limit) + process_due_tool_schedules(db_path=db_path, now=now, limit=limit)


def process_legacy_due_scheduled_jobs(db_path: Optional[Path] = None, now: Any = None) -> List[Dict[str, Any]]:
    now_dt = ensure_aware_utc(now)
    conn = get_connection(db_path)
    cursor = conn.cursor()
    cursor.execute(
        "SELECT id, cron_or_timestamp, task_payload, status FROM scheduled_jobs WHERE status IN ('PENDING', 'ACTIVE') ORDER BY created_at ASC"
    )
    rows = cursor.fetchall()
    processed: List[Dict[str, Any]] = []
    for row in rows:
        job_id = row["id"]
        # Rows mirrored from the new scheduler are processed through tool_schedules.
        cursor.execute("SELECT id, status FROM tool_schedules WHERE id = ?", (job_id,))
        linked = cursor.fetchone()
        if linked:
            if linked["status"] in ("COMPLETED", "CANCELLED"):
                cursor.execute("UPDATE scheduled_jobs SET status = ? WHERE id = ?", (linked["status"], job_id))
            continue
        try:
            due_at = ensure_aware_utc(parse_run_at(row["cron_or_timestamp"], "UTC"))
        except Exception:
            continue
        if due_at <= now_dt:
            cursor.execute("UPDATE scheduled_jobs SET status = 'COMPLETED' WHERE id = ?", (job_id,))
            processed.append({
                "id": job_id,
                "cron_or_timestamp": row["cron_or_timestamp"],
                "task_payload": row["task_payload"],
                "status": "COMPLETED",
                "executed_at": utc_iso(now_dt),
            })
    conn.commit()
    conn.close()
    return processed
