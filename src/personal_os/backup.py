from typing import List, Optional
import zipfile
import datetime
from pathlib import Path

from src.config import AGENT_DIR, MEMORY_PATH, SOUL_PATH, SKILL_PATH, DB_PATH

COGNEE_ARCHIVE_PREFIX = "cognee/"


def _cognee_dir() -> Path:
    from src.memory.cognee_memory import resolve_data_dir
    from src.memory.config import load_memory_config

    return resolve_data_dir(load_memory_config().cognee)

def rotate_backups(output_dir: Path = None, max_backups: int = 5) -> List[str]:
    """
    Prunes old backup zip files in output_dir keeping at most max_backups archives.
    Returns list of deleted archive filenames.
    """
    if output_dir is None:
        output_dir = AGENT_DIR / "backups"
    
    if not output_dir.exists():
        return []

    backups = sorted(
        [f for f in output_dir.glob("agent_backup_*.zip") if f.is_file()],
        key=lambda p: p.stat().st_mtime
    )

    deleted = []
    while len(backups) > max_backups:
        oldest = backups.pop(0)
        try:
            oldest.unlink()
            deleted.append(oldest.name)
        except OSError:
            pass

    return deleted

def export_agent_backup(output_dir: Path = None, max_backups: int = 5) -> dict:
    """
    Creates a compressed zip archive backup of the entire .agent workspace
    including state.db, SOUL.md, legacy MEMORY.md/SKILL.md, and the cognee
    knowledge-graph stores, applying backup rotation policy.
    """
    if output_dir is None:
        output_dir = AGENT_DIR / "backups"
    
    output_dir.mkdir(parents=True, exist_ok=True)

    timestamp = datetime.datetime.now().strftime("%Y%m%d_%H%M%S_%f")[:19]
    zip_path = output_dir / f"agent_backup_{timestamp}.zip"

    files_to_pack = [
        ("state.db", DB_PATH),
        ("SOUL.md", SOUL_PATH),
        ("MEMORY.md", MEMORY_PATH),
        ("SKILL.md", SKILL_PATH),
    ]

    packed = []
    with zipfile.ZipFile(zip_path, "w", zipfile.ZIP_DEFLATED) as zf:
        for arcname, file_path in files_to_pack:
            if file_path.exists():
                zf.write(file_path, arcname=arcname)
                packed.append(arcname)
        cognee_dir = _cognee_dir()
        if cognee_dir.is_dir():
            for file_path in sorted(cognee_dir.rglob("*")):
                if file_path.is_file():
                    zf.write(file_path, arcname=COGNEE_ARCHIVE_PREFIX + file_path.relative_to(cognee_dir).as_posix())
            packed.append(COGNEE_ARCHIVE_PREFIX)

    pruned = rotate_backups(output_dir=output_dir, max_backups=max_backups)

    return {
        "status": "SUCCESS",
        "backup_path": zip_path.as_posix(),
        "packed_files": packed,
        "pruned_backups": pruned,
        "size_bytes": zip_path.stat().st_size if zip_path.exists() else 0,
        "created_at": datetime.datetime.now().isoformat()
    }


def get_available_backups(output_dir: Optional[Path] = None) -> List[dict]:
    """Returns list of available backup zip archives in output_dir."""
    if output_dir is None:
        output_dir = AGENT_DIR / "backups"

    if not output_dir.exists():
        return []

    backups = sorted(
        [f for f in output_dir.glob("agent_backup_*.zip") if f.is_file()],
        key=lambda p: p.stat().st_mtime,
        reverse=True
    )

    results = []
    for b in backups:
        stat = b.stat()
        results.append({
            "filename": b.name,
            "path": b.as_posix(),
            "size_bytes": stat.st_size,
            "created_at": datetime.datetime.fromtimestamp(stat.st_mtime).isoformat()
        })
    return results


def restore_agent_backup(zip_path: Path, db_path: Optional[Path] = None) -> dict:
    """
    Restores state.db, SOUL.md, legacy MEMORY.md/SKILL.md and the cognee stores from a zip backup with safety checks and pre-restore copy.
    """
    target_path = Path(zip_path).resolve()
    if not target_path.exists() or not target_path.is_file():
        raise FileNotFoundError(f"Backup archive '{target_path}' not found.")

    if not zipfile.is_zipfile(target_path):
        raise ValueError(f"Backup file '{target_path.name}' is not a valid zip archive.")

    target_db = db_path or DB_PATH

    target_map = {
        "state.db": target_db,
        "SOUL.md": SOUL_PATH,
        "MEMORY.md": MEMORY_PATH,
        "SKILL.md": SKILL_PATH
    }

    # Verify SQLite DB header inside zip file if state.db present
    with zipfile.ZipFile(target_path, "r") as zf:
        if "state.db" in zf.namelist():
            db_bytes = zf.read("state.db")
            if len(db_bytes) < 16 or db_bytes[:16] != b"SQLite format 3\x00":
                raise ValueError("Corrupt or invalid SQLite database inside backup archive (missing SQLite header).")

    # Create safety rollback copy of existing database before overwriting
    if target_db.exists():
        bak_file = target_db.parent / f"{target_db.name}.bak"
        try:
            bak_file.write_bytes(target_db.read_bytes())
        except Exception:
            pass

    restored = []
    cognee_dir = _cognee_dir().resolve()
    cognee_restored = False
    with zipfile.ZipFile(target_path, "r") as zf:
        for name in zf.namelist():
            if name.startswith(COGNEE_ARCHIVE_PREFIX) and not name.endswith("/"):
                dest = (cognee_dir / name[len(COGNEE_ARCHIVE_PREFIX):]).resolve()
                # Reject zip-slip paths that would escape the cognee directory.
                if cognee_dir not in dest.parents:
                    continue
                dest.parent.mkdir(parents=True, exist_ok=True)
                dest.write_bytes(zf.read(name))
                cognee_restored = True
                continue
            if name in target_map:
                dest = target_map[name]
                dest.parent.mkdir(parents=True, exist_ok=True)
                content = zf.read(name)
                try:
                    dest.write_bytes(content)
                    restored.append(name)
                except OSError as err:
                    print(f"[Backup Restore Warning] File '{name}' write deferred/locked: {err}")
                    restored.append(f"{name} (deferred)")

    if cognee_restored:
        restored.append(COGNEE_ARCHIVE_PREFIX)

    return {
        "status": "RESTORED",
        "backup_path": target_path.as_posix(),
        "restored_files": restored,
        "restored_at": datetime.datetime.now().isoformat()
    }




