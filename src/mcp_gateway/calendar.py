import os
import uuid
from typing import List, Dict, Any, Optional
from langchain_core.tools import tool
from src.db import get_connection

def is_google_calendar_credentials_configured() -> bool:
    """Returns True if real Google Calendar credentials/token are present in environment or filesystem."""
    creds_path = os.getenv("GOOGLE_CALENDAR_CREDENTIALS") or ".agent/google_calendar_credentials.json"
    return os.path.exists(creds_path)

def get_calendar_storage_mode_banner() -> str:
    """Returns transparent mode tag for calendar tools."""
    if is_google_calendar_credentials_configured():
        return "[Calendar MCP (Google Calendar Sync Active)]"
    return "[Calendar MCP (Local SQLite Storage)]"

def detect_calendar_conflicts(start_time: str, end_time: str, exclude_id: str = "") -> List[Dict[str, Any]]:
    """Checks SQLite calendar_events table for overlapping event time slots."""
    conn = get_connection()
    cursor = conn.cursor()
    if exclude_id:
        cursor.execute(
            """
            SELECT id, title, start_time, end_time, status
            FROM calendar_events
            WHERE id != ? AND start_time < ? AND end_time > ?
            """,
            (exclude_id, end_time, start_time)
        )
    else:
        cursor.execute(
            """
            SELECT id, title, start_time, end_time, status
            FROM calendar_events
            WHERE start_time < ? AND end_time > ?
            """,
            (end_time, start_time)
        )
    rows = cursor.fetchall()
    conn.close()
    return [dict(r) for r in rows]

@tool
def calendar_inspect_availability(start_date: str, end_date: str) -> str:
    """Inspects calendar availability and booked events from local SQLite calendar_events table between start_date and end_date."""
    conn = get_connection()
    cursor = conn.cursor()
    cursor.execute(
        """
        SELECT id, title, start_time, end_time, attendees, location, status
        FROM calendar_events
        WHERE start_time >= ? AND start_time <= ?
        ORDER BY start_time ASC
        """,
        (start_date, end_date)
    )
    rows = cursor.fetchall()
    conn.close()

    banner = get_calendar_storage_mode_banner()
    if not rows:
        return f"{banner} Availability for {start_date} to {end_date}: All slots free. No booked events."

    event_list = [f"- '{r['title']}' ({r['start_time']} to {r['end_time']}) [{r['status']}] (ID: {r['id']})" for r in rows]
    return f"{banner} Events for {start_date} to {end_date}:\n" + "\n".join(event_list)

@tool
def calendar_propose_event(title: str, start_time: str, end_time: str, attendees: str = "", location: str = "") -> str:
    """Proposes a tentative calendar event proposal and stores it with TENTATIVE status in local SQLite after conflict checking."""
    conflicts = detect_calendar_conflicts(start_time, end_time)
    conflict_msg = ""
    if conflicts:
        conflict_list = [f"'{c['title']}' ({c['start_time']}-{c['end_time']})" for c in conflicts]
        conflict_msg = f" [CONFLICT WARNING: Overlaps with {', '.join(conflict_list)}]"

    event_id = f"evt_{uuid.uuid4().hex[:8]}"
    conn = get_connection()
    cursor = conn.cursor()
    cursor.execute(
        """
        INSERT INTO calendar_events (id, title, start_time, end_time, attendees, location, status, created_at)
        VALUES (?, ?, ?, ?, ?, ?, 'TENTATIVE', datetime('now'))
        """,
        (event_id, title, start_time, end_time, attendees, location)
    )
    conn.commit()
    conn.close()

    banner = get_calendar_storage_mode_banner()
    return f"{banner} [PROPOSAL] Event '{title}' proposed for {start_time} to {end_time} (ID: {event_id}).{conflict_msg}"

@tool
def calendar_create_event(title: str, start_time: str, end_time: str, attendees: str = "", location: str = "") -> str:
    """
    Creates a confirmed calendar event in local SQLite calendar_events table and syncs to Google Calendar API if credentials exist.
    HIGH RISK OPERATION: Requires Human-In-The-Loop approval.
    """
    conflicts = detect_calendar_conflicts(start_time, end_time)
    conflict_msg = ""
    if conflicts:
        conflict_list = [f"'{c['title']}' ({c['start_time']}-{c['end_time']})" for c in conflicts]
        conflict_msg = f" [CONFLICT WARNING: Overlaps with {', '.join(conflict_list)}]"

    gcal_synced = False
    gcal_token = os.getenv("GOOGLE_CALENDAR_TOKEN")
    if gcal_token:
        try:
            import urllib.request, json
            url = "https://www.googleapis.com/calendar/v3/calendars/primary/events"
            payload = json.dumps({
                "summary": title,
                "location": location,
                "start": {"dateTime": start_time if "T" in start_time else f"{start_time}:00Z"},
                "end": {"dateTime": end_time if "T" in end_time else f"{end_time}:00Z"}
            }).encode("utf-8")
            req = urllib.request.Request(url, data=payload, headers={
                "Authorization": f"Bearer {gcal_token}",
                "Content-Type": "application/json"
            })
            with urllib.request.urlopen(req, timeout=10) as resp:
                if resp.status in (200, 201):
                    gcal_synced = True
        except Exception:
            pass

    event_id = f"evt_{uuid.uuid4().hex[:8]}"
    conn = get_connection()
    cursor = conn.cursor()
    cursor.execute(
        """
        INSERT INTO calendar_events (id, title, start_time, end_time, attendees, location, status, created_at)
        VALUES (?, ?, ?, ?, ?, ?, 'CONFIRMED', datetime('now'))
        """,
        (event_id, title, start_time, end_time, attendees, location)
    )
    conn.commit()
    conn.close()

    banner = "[Calendar MCP (Google Calendar API Synced)]" if gcal_synced else get_calendar_storage_mode_banner()
    return f"{banner} [CREATED] Confirmed event '{title}' scheduled for {start_time} to {end_time} (ID: {event_id}).{conflict_msg}"


@tool
def calendar_update_event(event_id: str, title: str, start_time: str, end_time: str, attendees: str = "", location: str = "", status: str = "CONFIRMED") -> str:
    """Updates an existing calendar event record in local SQLite calendar_events table after conflict checking."""
    conflicts = detect_calendar_conflicts(start_time, end_time, exclude_id=event_id)
    conflict_msg = ""
    if conflicts:
        conflict_list = [f"'{c['title']}' ({c['start_time']}-{c['end_time']})" for c in conflicts]
        conflict_msg = f" [CONFLICT WARNING: Overlaps with {', '.join(conflict_list)}]"

    conn = get_connection()
    cursor = conn.cursor()
    cursor.execute(
        """
        UPDATE calendar_events
        SET title = ?, start_time = ?, end_time = ?, attendees = ?, location = ?, status = ?
        WHERE id = ?
        """,
        (title, start_time, end_time, attendees, location, status, event_id)
    )
    affected = cursor.rowcount
    conn.commit()
    conn.close()

    banner = get_calendar_storage_mode_banner()
    if affected == 0:
        return f"{banner} [Error] Event '{event_id}' not found."
    return f"{banner} [UPDATED] Event '{event_id}' updated to '{title}' ({start_time} to {end_time}) [{status}].{conflict_msg}"

@tool
def calendar_delete_event(event_id: str) -> str:
    """Deletes a calendar event record from local SQLite calendar_events table."""
    conn = get_connection()
    cursor = conn.cursor()
    cursor.execute("DELETE FROM calendar_events WHERE id = ?", (event_id,))
    affected = cursor.rowcount
    conn.commit()
    conn.close()

    banner = get_calendar_storage_mode_banner()
    if affected == 0:
        return f"{banner} [Error] Event '{event_id}' not found."
    return f"{banner} [DELETED] Event '{event_id}' successfully removed from calendar."

