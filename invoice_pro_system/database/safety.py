"""Database path and backup safety helpers."""

from __future__ import annotations

import shutil
from datetime import datetime
from pathlib import Path
from typing import Optional

from config.settings import config

_BACKED_UP_PATHS: set[str] = set()


def is_production() -> bool:
    return str(__import__("os").getenv("APP_ENV", "development")).strip().lower() == "production"


def allow_production_bootstrap() -> bool:
    value = str(__import__("os").getenv("ALLOW_DB_BOOTSTRAP", "")).strip().lower()
    return value in {"1", "true", "yes", "on"}


def allow_manual_db_maintenance() -> bool:
    value = str(__import__("os").getenv("ALLOW_MANUAL_DB_MAINTENANCE", "")).strip().lower()
    return value in {"1", "true", "yes", "on"}


def get_db_path(db_path=None) -> Path:
    """Return the canonical database path used by the app."""
    path = Path(db_path) if db_path is not None else Path(config.DB_PATH)
    path.parent.mkdir(parents=True, exist_ok=True)
    return path


def require_existing_production_db(db_path=None, reason: str = "database access") -> Path:
    """Refuse to silently bootstrap a brand-new production DB unless explicitly allowed."""
    path = get_db_path(db_path)
    if is_production() and not path.exists() and not allow_production_bootstrap():
        raise RuntimeError(
            f"Production database not found at {path}. Refusing to create a new empty database during {reason}. "
            "Set ALLOW_DB_BOOTSTRAP=true only for an intentional first-time bootstrap."
        )
    return path


def require_manual_db_maintenance(db_path=None, reason: str = "manual database maintenance") -> Path:
    """Block risky ad-hoc database maintenance in production unless explicitly enabled."""
    path = require_existing_production_db(db_path, reason=reason)
    if is_production() and not allow_manual_db_maintenance():
        raise RuntimeError(
            f"{reason.capitalize()} is blocked in production for {path}. "
            "Set ALLOW_MANUAL_DB_MAINTENANCE=true only for a deliberate one-off maintenance window."
        )
    return path


def ensure_schema_backup(db_path=None, reason: str = "schema", keep: int = 10) -> Optional[Path]:
    """Create a one-time per-process backup before schema-changing work."""
    path = require_existing_production_db(db_path, reason=reason)
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


def create_manual_backup(db_path=None, reason: str = "manual") -> Path:
    """Create a timestamped on-demand backup of the configured database."""
    path = require_existing_production_db(db_path, reason=reason)
    backups_dir = path.parent / "backups"
    backups_dir.mkdir(parents=True, exist_ok=True)
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    backup_path = backups_dir / f"{path.stem}_{reason}_{timestamp}{path.suffix}"
    shutil.copy2(path, backup_path)
    return backup_path
