import json
import sqlite3
from datetime import datetime
from typing import Any, Dict, List, Optional

from database.safety import ensure_schema_backup, get_db_path


class AuditService:
    """Lightweight audit logging service."""

    def __init__(self, db_path=None):
        self.db_path = get_db_path(db_path)
        self.db_path.parent.mkdir(exist_ok=True)
        self._ensure_table()

    def _get_connection(self):
        conn = sqlite3.connect(self.db_path)
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA foreign_keys = ON")
        return conn

    def _ensure_table(self):
        ensure_schema_backup(self.db_path, reason="audit")
        conn = self._get_connection()
        cursor = conn.cursor()
        try:
            cursor.execute(
                """
                CREATE TABLE IF NOT EXISTS audit_logs (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    event_type TEXT NOT NULL,
                    entity_type TEXT NOT NULL,
                    entity_id INTEGER,
                    actor TEXT DEFAULT 'system',
                    source TEXT DEFAULT 'system',
                    details_json TEXT,
                    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
                )
                """
            )
            cursor.execute(
                "CREATE INDEX IF NOT EXISTS idx_audit_logs_created_at ON audit_logs(created_at)"
            )
            cursor.execute(
                "CREATE INDEX IF NOT EXISTS idx_audit_logs_entity ON audit_logs(entity_type, entity_id)"
            )
            conn.commit()
        finally:
            conn.close()

    def log_action(
        self,
        event_type: str,
        entity_type: str,
        entity_id: Optional[int] = None,
        actor: str = "system",
        source: str = "system",
        details: Optional[Dict[str, Any]] = None,
    ) -> bool:
        conn = self._get_connection()
        cursor = conn.cursor()
        try:
            cursor.execute(
                """
                INSERT INTO audit_logs
                (event_type, entity_type, entity_id, actor, source, details_json, created_at)
                VALUES (?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    event_type,
                    entity_type,
                    entity_id,
                    actor or "system",
                    source or "system",
                    json.dumps(details or {}, default=str),
                    datetime.now().isoformat(),
                ),
            )
            conn.commit()
            return True
        except Exception:
            return False
        finally:
            conn.close()

    def get_recent_logs(self, limit: int = 100) -> List[Dict[str, Any]]:
        conn = self._get_connection()
        cursor = conn.cursor()
        try:
            cursor.execute(
                """
                SELECT * FROM audit_logs
                ORDER BY created_at DESC
                LIMIT ?
                """,
                (limit,),
            )
            rows = [dict(row) for row in cursor.fetchall()]
            for row in rows:
                try:
                    row["details"] = json.loads(row.get("details_json") or "{}")
                except Exception:
                    row["details"] = {}
            return rows
        finally:
            conn.close()

    def query_logs(
        self,
        limit: int = 200,
        entity_type: Optional[str] = None,
        event_text: Optional[str] = None,
        date_from: Optional[str] = None,
        date_to: Optional[str] = None,
    ) -> List[Dict[str, Any]]:
        """Query audit logs with optional filters."""
        conn = self._get_connection()
        cursor = conn.cursor()
        try:
            query = "SELECT * FROM audit_logs WHERE 1=1"
            params: List[Any] = []

            if entity_type:
                query += " AND entity_type = ?"
                params.append(entity_type)

            if event_text:
                query += " AND event_type LIKE ?"
                params.append(f"%{event_text}%")

            if date_from:
                query += " AND date(created_at) >= date(?)"
                params.append(date_from)

            if date_to:
                query += " AND date(created_at) <= date(?)"
                params.append(date_to)

            query += " ORDER BY created_at DESC LIMIT ?"
            params.append(limit)
            cursor.execute(query, params)

            rows = [dict(row) for row in cursor.fetchall()]
            for row in rows:
                try:
                    row["details"] = json.loads(row.get("details_json") or "{}")
                except Exception:
                    row["details"] = {}
            return rows
        finally:
            conn.close()
