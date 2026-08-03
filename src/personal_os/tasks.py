import uuid
import sqlite3
from typing import Optional
from pathlib import Path
from langchain_core.tools import tool
from src.db import get_connection

@tool
def create_task(title: str, description: str = "", priority: str = "Medium") -> str:
    """Creates a new internal task in the Personal OS task tracking table."""
    task_id = f"task_{uuid.uuid4().hex[:8]}"
    conn = get_connection()
    cursor = conn.cursor()
    cursor.execute(
        """
        INSERT INTO tasks (id, title, description, priority, status, progress, created_at, updated_at)
        VALUES (?, ?, ?, ?, 'PENDING', 0, datetime('now'), datetime('now'))
        """,
        (task_id, title, description, priority)
    )
    conn.commit()
    conn.close()
    return f"[Personal OS Task Created] ID: {task_id} | Title: '{title}' | Priority: {priority}"

@tool
def update_task(task_id: str, status: str = "IN_PROGRESS", progress: int = 50) -> str:
    """Updates the status and percentage progress of an existing internal task."""
    conn = get_connection()
    cursor = conn.cursor()
    cursor.execute(
        """
        UPDATE tasks
        SET status = ?, progress = ?, updated_at = datetime('now')
        WHERE id = ?
        """,
        (status, progress, task_id)
    )
    affected = cursor.rowcount
    conn.commit()
    conn.close()

    if affected == 0:
        return f"[Personal OS Task Error] Task '{task_id}' not found."
    return f"[Personal OS Task Updated] Task '{task_id}' status set to '{status}' ({progress}% progress)."

@tool
def cancel_task(task_id: str) -> str:
    """Cancels a running or pending internal task."""
    conn = get_connection()
    cursor = conn.cursor()
    cursor.execute(
        """
        UPDATE tasks
        SET status = 'CANCELLED', updated_at = datetime('now')
        WHERE id = ?
        """,
        (task_id,)
    )
    affected = cursor.rowcount
    conn.commit()
    conn.close()

    if affected == 0:
        return f"[Personal OS Task Error] Task '{task_id}' not found."
    return f"[Personal OS Task Cancelled] Task '{task_id}' has been cancelled."

@tool
def list_tasks(status_filter: str = "ALL") -> str:
    """Lists pending, running, or completed internal tasks."""
    conn = get_connection()
    cursor = conn.cursor()

    if status_filter.upper() == "ALL":
        cursor.execute("SELECT id, title, priority, status, progress FROM tasks ORDER BY created_at DESC")
    else:
        cursor.execute("SELECT id, title, priority, status, progress FROM tasks WHERE status = ? ORDER BY created_at DESC", (status_filter.upper(),))

    rows = cursor.fetchall()
    conn.close()

    if not rows:
        return f"[Personal OS Tasks] No tasks found matching status filter '{status_filter}'."

    task_lines = [f"- ID: {r['id']} | Title: {r['title']} | Status: {r['status']} | Priority: {r['priority']} | Progress: {r['progress']}%" for r in rows]
    return "[Personal OS Task List]\n" + "\n".join(task_lines)
