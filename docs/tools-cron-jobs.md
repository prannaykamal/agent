# Cron Jobs

Cron is the local durable scheduler for assistant actions. It is not Google Calendar.

Google Calendar MCP manages calendar events. Cron manages local future execution of assistant actions.

## Storage Model

Cron uses scheduler-owned tables:

- `tool_schedules`: schedule definitions
- `tool_schedule_runs`: run attempts

`memory_jobs` is not used as the schedule definition table.

Legacy `scheduled_jobs` rows may remain for compatibility, but the scheduler source of truth is `tool_schedules`.

## Schedule Types

One-time schedule:

- `schedule_type = one_time`
- `run_at` required
- `timezone` required or defaulted
- `next_run_at` computed
- successful run completes the schedule

Recurring schedule:

- `schedule_type = recurring`
- `cron_expression` required
- `timezone` required or defaulted
- `next_run_at` computed from cron and timezone
- `last_run_at` updates after handling a due occurrence
- next occurrence is computed after each run

## Timezone

Schedules store the timezone and normalize computed run timestamps. Tests should inject deterministic `now` values and cover UTC plus at least one non-UTC timezone.

## Missed Runs

Supported policies:

- `skip`: move forward without running missed occurrences
- `run_once`: run at most one catch-up occurrence
- `catch_up_limited`: run up to `max_catchup_runs`

Default behavior should be conservative. High-risk external/write actions should skip or wait for approval unless explicitly authorized by policy.

## Run Statuses

Run attempts may be:

- `PENDING`
- `CLAIMED`
- `WAITING_FOR_APPROVAL`
- `RUNNING`
- `SUCCEEDED`
- `FAILED_RETRYABLE`
- `FAILED_TERMINAL`
- `CANCELLED`

## Execution Boundary

Due schedule processing:

1. Finds due schedules by `next_run_at`.
2. Creates or claims a `tool_schedule_runs` row.
3. Evaluates centralized tool policy.
4. Creates HITL approval for high-risk actions.
5. Invokes only permitted local or MCP tools through the approved invocation boundary.
6. Records result or failure.
7. Advances schedule timestamps.

Provider-targeted scheduled actions must not call provider APIs directly. They use MCP after policy permits execution.

## Observability

Cron observability exposes schedule and run status, target tool ID, approval state, timestamps, failure previews, and redacted payload previews. It does not execute schedules.
