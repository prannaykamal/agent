import re
import sqlite3
from pathlib import Path
from typing import List, Dict, Any, Optional
from src.db import get_connection, DB_PATH
from src.config import SKILL_PATH

def add_procedural_skill(
    name: str,
    description: str,
    trigger_keywords: str,
    execution_steps: str,
    db_path: Optional[Path] = None,
    skill_path: Optional[Path] = None
) -> None:
    """Inserts or updates a procedural skill in SQLite skills table and syncs SKILL.md."""
    conn = get_connection(db_path)
    cursor = conn.cursor()
    cursor.execute(
        """
        INSERT OR REPLACE INTO skills (name, description, trigger_keywords, execution_steps)
        VALUES (?, ?, ?, ?)
        """,
        (name, description, trigger_keywords, execution_steps)
    )
    conn.commit()
    conn.close()

    sync_skill_md(db_path=db_path, skill_path=skill_path)

def update_procedural_skill(
    name: str,
    execution_steps: str,
    db_path: Optional[Path] = None,
    skill_path: Optional[Path] = None
) -> None:
    """Updates execution steps of an existing procedural skill."""
    conn = get_connection(db_path)
    cursor = conn.cursor()
    cursor.execute("UPDATE skills SET execution_steps = ? WHERE name = ?", (execution_steps, name))
    conn.commit()
    conn.close()

    sync_skill_md(db_path=db_path, skill_path=skill_path)

def delete_procedural_skill(
    name: str,
    db_path: Optional[Path] = None,
    skill_path: Optional[Path] = None
) -> None:
    """Deletes a procedural skill from SQLite and syncs SKILL.md."""
    conn = get_connection(db_path)
    cursor = conn.cursor()
    cursor.execute("DELETE FROM skills WHERE name = ?", (name,))
    conn.commit()
    conn.close()

    sync_skill_md(db_path=db_path, skill_path=skill_path)

def get_all_procedural_skills(db_path: Optional[Path] = None) -> List[Dict[str, Any]]:
    """Retrieves all registered procedural skills from SQLite table `skills`."""
    conn = get_connection(db_path)
    cursor = conn.cursor()
    cursor.execute("SELECT id, name, description, trigger_keywords, execution_steps FROM skills ORDER BY name ASC")
    rows = cursor.fetchall()
    conn.close()
    return [dict(row) for row in rows]

def sync_skill_md(
    db_path: Optional[Path] = None,
    skill_path: Optional[Path] = None
) -> str:
    """Renders all procedural skills from SQLite into .agent/SKILL.md file."""
    conn = get_connection(db_path)
    cursor = conn.cursor()
    cursor.execute("SELECT name, description, trigger_keywords, execution_steps FROM skills ORDER BY name ASC")
    rows = cursor.fetchall()
    conn.close()

    target_path = skill_path or SKILL_PATH

    if not rows:
        content = "# Procedural Memory Catalog (.agent/SKILL.md)\n\n*No procedural skills defined yet.*\n"
        target_path.parent.mkdir(parents=True, exist_ok=True)
        target_path.write_text(content, encoding="utf-8")
        return content

    lines = ["# Procedural Memory Catalog (.agent/SKILL.md)\n", "*Auto-synced from SQLite `skills` table.*\n"]
    for idx, r in enumerate(rows, 1):
        lines.append(f"### {idx}. {r['name']}")
        lines.append(f"- **Description**: {r['description']}")
        lines.append(f"- **Trigger Keywords**: {r['trigger_keywords']}")
        lines.append(f"- **Action Steps**: {r['execution_steps']}")
        lines.append("")

    content = "\n".join(lines)
    target_path.parent.mkdir(parents=True, exist_ok=True)
    target_path.write_text(content, encoding="utf-8")
    return content

def sync_skills_from_md(
    skill_path: Optional[Path] = None,
    db_path: Optional[Path] = None
) -> None:
    """Parses SKILL.md and populates SQLite skills database."""
    target_path = skill_path or SKILL_PATH
    if not target_path.exists():
        return

    content = target_path.read_text(encoding="utf-8")

    sections = re.findall(r"###\s+\d+\.\s+(.*?)\n(.*?)(?=\n###|\Z)", content, re.DOTALL)
    for name, body in sections:
        clean_name = name.strip()
        trigger_match = re.search(r"-\s+\*\*Trigger\*\*:\s*(.*)", body)
        action_match = re.search(r"-\s+\*\*Action\*\*:\s*(.*)", body)

        trigger_keywords = trigger_match.group(1).strip() if trigger_match else clean_name
        execution_steps = action_match.group(1).strip() if action_match else body.strip()

        add_procedural_skill(
            name=clean_name,
            description=clean_name,
            trigger_keywords=trigger_keywords,
            execution_steps=execution_steps,
            db_path=db_path,
            skill_path=skill_path
        )

def match_procedural_skills(
    query: str,
    db_path: Optional[Path] = None
) -> List[Dict[str, Any]]:
    """Matches user query against registered skill triggers in SQLite skills table."""
    if not query.strip():
        return []

    all_skills = get_all_procedural_skills(db_path=db_path)

    matched = []
    query_lower = query.lower()
    for skill in all_skills:
        keywords = [k.strip().lower() for k in skill["trigger_keywords"].split(",")]
        keywords.append(skill["name"].lower())
        if any(kw in query_lower for kw in keywords if len(kw) > 2):
            matched.append(skill)

    return matched
