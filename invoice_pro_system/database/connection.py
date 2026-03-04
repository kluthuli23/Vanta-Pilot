"""Shared database connection utilities."""

import sqlite3
from typing import Optional

from config.settings import config


class DatabaseConnection:
    """Simple shared SQLite connection manager for app-level lifecycle hooks."""

    def __init__(self, db_path=None, timeout=None):
        self.db_path = str(db_path or config.DB_PATH)
        self.timeout = timeout if timeout is not None else config.DB_TIMEOUT
        self._connection: Optional[sqlite3.Connection] = None

    def get_connection(self) -> sqlite3.Connection:
        """Return an open SQLite connection, creating it lazily."""
        if self._connection is None:
            self._connection = sqlite3.connect(self.db_path, timeout=self.timeout)
            self._connection.row_factory = sqlite3.Row
            self._connection.execute("PRAGMA foreign_keys = ON")
        return self._connection

    def close_connection(self) -> None:
        """Close the shared connection if it exists."""
        if self._connection is not None:
            self._connection.close()
            self._connection = None


# Module-level singleton used by the CLI shutdown hook.
db = DatabaseConnection()
