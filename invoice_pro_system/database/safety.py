"""Database path and backup safety helpers."""

from __future__ import annotations

import shutil
from datetime import datetime
from pathlib import Path
from typing import Optional

from config.settings import config

_BACKED_UP_PATHS: set[str] = set()


def get_db_path(db_path=None) -> Path:
    """Return the canonical database path used by the app."""
    path = Path(db_path) if db_path is not None else Path(config.DB_PATH)
    path.parent.mkdir(parents=True, exist_ok=True)
    return path


def ensure_schema_backup(db_path=None, reason: str = "schema", keep: int = 10) -> Optional[Path]:
    """Create a one-time per-process backup before schema-changing work."""
    path = get_db_path(db_path)
    try:
        key = str(path.resolve())
    except Exception:
        key = str(path)

    if key in _BACKED_UP_PATHS or not path.exists():
        return None

    backups_dir = path.parent / "backups"
    backups_dir.mkdir(parents=True, exist_ok=True)
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    backup_path = backups_dir / f"{path.stem}_{reason}_{timestamp}{path.suffix}"
    shutil.copy2(path, backup_path)
    _BACKED_UP_PATHS.add(key)

    backups = sorted(
        backups_dir.glob(f"{path.stem}_*{path.suffix}"),
        key=lambda p: p.stat().st_mtime,
        reverse=True,
    )
    for old_backup in backups[keep:]:
        old_backup.unlink(missing_ok=True)

    return backup_path
