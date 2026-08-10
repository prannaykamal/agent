from __future__ import annotations

from dataclasses import dataclass
from datetime import timedelta
from pathlib import Path
from typing import Any, Dict, List, Optional

from src.personal_os.cron_parser import ensure_aware_utc, next_cron_run_at, utc_iso
from src.personal_os.scheduler_policy import approval_policy_for_target
from src.personal_os.scheduler_store import ToolScheduleRecord, ToolScheduleRepository, ToolScheduleRunRecord, ToolScheduleWrite


@dataclass(frozen=True)
class ScheduleCreationResult:
    schedule: ToolScheduleRecord
    legacy_mirrored: bool = False

    def to_dict(self) -> Dict[str, Any]:
        return {"schedule": self.schedule.to_dict(), "legacy_mirrored": self.legacy_mirrored}


def default_missed_policy_for_target(target_tool_id: str) -> str:
    policy = approval_policy_for_target(target_tool_id)
    if policy == "no_approval_needed":
        return "run_once"
    return "skip"


def create_tool_schedule(
    *,
    schedule_type: str,
    target_tool_id: str,
    target_payload: Optional[Dict[str, Any]] = None,
    cron_expression: Optional[str] = None,
    run_at: Optional[str] = None,
    timezone: str = "UTC",
    missed_run_policy: Optional[str] = None,
    max_catchup_runs: int = 1,
    created_by: str = "user",
    db_path: Optional[Path] = None,
    now: Any = None,
    mirror_legacy: bool = False,
) -> ScheduleCreationResult:
    approval_policy = approval_policy_for_target(target_tool_id)
    write = ToolScheduleWrite(
        schedule_type=schedule_type,
        cron_expression=cron_expression,
        run_at=run_at,
        timezone=timezone or "UTC",
        target_tool_id=target_tool_id,
        target_payload=target_payload or {},
        missed_run_policy=missed_run_policy or default_missed_policy_for_target(target_tool_id),
        max_catchup_runs=max_catchup_runs,
        approval_policy=approval_policy,
        created_by=created_by,
    )
    repo = ToolScheduleRepository(db_path)
    schedule = repo.create_schedule(write, now=now)
    if mirror_legacy:
        repo.mirror_legacy_scheduled_job(schedule)
    return ScheduleCreationResult(schedule=schedule, legacy_mirrored=mirror_legacy)


def create_legacy_compatible_schedule(cron_or_timestamp: str, task_payload: str, *, db_path: Optional[Path] = None, now: Any = None) -> ScheduleCreationResult:
    text = str(cron_or_timestamp or "").strip()
    if len(text.split()) == 5:
        return create_tool_schedule(
            schedule_type="recurring",
            cron_expression=text,
            timezone="UTC",
            target_tool_id="heartbeat",
            target_payload={"legacy_task_payload": task_payload},
            created_by="legacy_api",
            db_path=db_path,
            now=now,
            mirror_legacy=True,
        )
    return create_tool_schedule(
        schedule_type="one_time",
        run_at=text,
        timezone="UTC",
        target_tool_id="heartbeat",
        target_payload={"legacy_task_payload": task_payload},
        created_by="legacy_api",
        db_path=db_path,
        now=now,
        mirror_legacy=True,
    )


def occurrences_due_for_schedule(schedule: ToolScheduleRecord, *, now: Any = None) -> List[str]:
    if not schedule.next_run_at:
        return []
    now_dt = ensure_aware_utc(now)
    next_dt = ensure_aware_utc(schedule.next_run_at)
    if next_dt > now_dt:
        return []
    if schedule.schedule_type == "one_time":
        return [schedule.next_run_at]
    if schedule.missed_run_policy == "skip" and next_dt < now_dt.replace(second=0, microsecond=0):
        return []
    if schedule.missed_run_policy == "run_once":
        return [schedule.next_run_at]
    if schedule.missed_run_policy == "catch_up_limited":
        occurrences: List[str] = []
        current = schedule.next_run_at
        limit = max(0, int(schedule.max_catchup_runs or 0))
        while current and len(occurrences) < limit and ensure_aware_utc(current) <= now_dt:
            occurrences.append(current)
            current = next_cron_run_at(schedule.cron_expression or "", schedule.timezone, after=current)
        return occurrences
    return [schedule.next_run_at]


def list_schedules(db_path: Optional[Path] = None, status: Optional[str] = None, limit: int = 100) -> List[Dict[str, Any]]:
    return [item.to_dict(include_payload=False) for item in ToolScheduleRepository(db_path).list_schedules(status=status, limit=limit)]


def list_runs(db_path: Optional[Path] = None, schedule_id: Optional[str] = None, status: Optional[str] = None, limit: int = 100) -> List[Dict[str, Any]]:
    return [item.to_dict() for item in ToolScheduleRepository(db_path).list_runs(schedule_id=schedule_id, status=status, limit=limit)]
