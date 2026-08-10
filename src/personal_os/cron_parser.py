from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

UTC_FORMAT = "%Y-%m-%dT%H:%M:%SZ"


class CronParseError(ValueError):
    pass


@dataclass(frozen=True)
class ParsedCronExpression:
    expression: str
    minutes: frozenset[int]
    hours: frozenset[int]
    days_of_month: frozenset[int]
    months: frozenset[int]
    days_of_week: frozenset[int]


def get_zone(tz_name: str | None) -> ZoneInfo:
    clean = str(tz_name or "UTC").strip() or "UTC"
    try:
        return ZoneInfo(clean)
    except ZoneInfoNotFoundError as exc:
        raise CronParseError(f"Unsupported timezone: {clean}") from exc


def ensure_aware_utc(value: datetime | str | None) -> datetime:
    if value is None:
        return datetime.now(timezone.utc).replace(microsecond=0)
    if isinstance(value, datetime):
        dt = value
    else:
        text = str(value).strip()
        if text.endswith("Z"):
            text = text[:-1] + "+00:00"
        try:
            dt = datetime.fromisoformat(text)
        except ValueError:
            for fmt in ("%Y-%m-%d %H:%M", "%Y-%m-%dT%H:%M", "%Y-%m-%d %H:%M:%S"):
                try:
                    dt = datetime.strptime(str(value).strip(), fmt)
                    break
                except ValueError:
                    dt = None  # type: ignore[assignment]
            if dt is None:
                raise CronParseError(f"Unsupported datetime format: {value}")
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc).replace(microsecond=0)


def utc_iso(value: datetime | str | None) -> str:
    return ensure_aware_utc(value).strftime(UTC_FORMAT)


def parse_run_at(run_at: str, timezone_name: str = "UTC") -> str:
    text = str(run_at or "").strip()
    if not text:
        raise CronParseError("run_at is required for one-time schedules")
    if text.endswith("Z") or "+" in text[10:] or ("-" in text[10:]):
        return utc_iso(text)
    zone = get_zone(timezone_name)
    try:
        local = datetime.fromisoformat(text)
    except ValueError:
        for fmt in ("%Y-%m-%d %H:%M", "%Y-%m-%dT%H:%M", "%Y-%m-%d %H:%M:%S"):
            try:
                local = datetime.strptime(text, fmt)
                break
            except ValueError:
                local = None  # type: ignore[assignment]
        if local is None:
            raise CronParseError(f"Unsupported run_at format: {run_at}")
    if local.tzinfo is None:
        local = local.replace(tzinfo=zone)
    return utc_iso(local)


def _parse_field(field: str, minimum: int, maximum: int, *, allow_7_as_0: bool = False) -> frozenset[int]:
    values: set[int] = set()
    for part in str(field or "").split(","):
        part = part.strip()
        if not part:
            raise CronParseError("Empty cron field component")
        step = 1
        base = part
        if "/" in part:
            base, step_text = part.split("/", 1)
            if not step_text.isdigit() or int(step_text) <= 0:
                raise CronParseError(f"Invalid cron step: {part}")
            step = int(step_text)
        if base == "*":
            start, end = minimum, maximum
        elif "-" in base:
            left, right = base.split("-", 1)
            if not left.isdigit() or not right.isdigit():
                raise CronParseError(f"Invalid cron range: {part}")
            start, end = int(left), int(right)
        else:
            if not base.isdigit():
                raise CronParseError(f"Unsupported cron token: {part}")
            start = end = int(base)
        if allow_7_as_0:
            if start == 7:
                start = 0
            if end == 7:
                end = 0
        if start > end and not allow_7_as_0:
            raise CronParseError(f"Invalid cron range: {part}")
        if start < minimum or end > maximum:
            raise CronParseError(f"Cron field out of range: {part}")
        if allow_7_as_0 and start > end:
            range_values = list(range(start, maximum + 1, step)) + list(range(minimum, end + 1, step))
        else:
            range_values = list(range(start, end + 1, step))
        values.update(range_values)
    return frozenset(values)


def parse_cron_expression(expression: str) -> ParsedCronExpression:
    clean = " ".join(str(expression or "").strip().split())
    fields = clean.split(" ")
    if len(fields) != 5:
        raise CronParseError("Only standard 5-field cron expressions are supported")
    return ParsedCronExpression(
        expression=clean,
        minutes=_parse_field(fields[0], 0, 59),
        hours=_parse_field(fields[1], 0, 23),
        days_of_month=_parse_field(fields[2], 1, 31),
        months=_parse_field(fields[3], 1, 12),
        days_of_week=_parse_field(fields[4], 0, 6, allow_7_as_0=True),
    )


def _cron_dow(local_dt: datetime) -> int:
    return (local_dt.weekday() + 1) % 7


def cron_matches(parsed: ParsedCronExpression, local_dt: datetime) -> bool:
    return (
        local_dt.minute in parsed.minutes
        and local_dt.hour in parsed.hours
        and local_dt.day in parsed.days_of_month
        and local_dt.month in parsed.months
        and _cron_dow(local_dt) in parsed.days_of_week
    )


def next_cron_run_at(expression: str, timezone_name: str = "UTC", after: datetime | str | None = None) -> str:
    parsed = parse_cron_expression(expression)
    zone = get_zone(timezone_name)
    current_utc = ensure_aware_utc(after)
    local = current_utc.astimezone(zone).replace(second=0, microsecond=0) + timedelta(minutes=1)
    max_minutes = 366 * 24 * 60
    for _ in range(max_minutes):
        if cron_matches(parsed, local):
            return utc_iso(local.astimezone(timezone.utc))
        local += timedelta(minutes=1)
    raise CronParseError("No matching cron occurrence found within one year")
