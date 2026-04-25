import sqlite3
from datetime import datetime, timedelta
from typing import Dict, Optional

from database.safety import ensure_schema_backup, get_db_path

class SubscriptionService:
    """Manage trial and subscription status for tenant accounts."""

    TRIAL_DAYS = 90
    WRITE_ALLOWED_STATUSES = {"trialing", "active"}

    def __init__(self, db_path=None):
        self.db_path = get_db_path(db_path)
        self.db_path.parent.mkdir(exist_ok=True)
        self._ensure_columns()

    def _get_connection(self):
        conn = sqlite3.connect(self.db_path)
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA foreign_keys = ON")
        return conn

    def _ensure_columns(self):
        ensure_schema_backup(self.db_path, reason="subscriptions")
        conn = self._get_connection()
        cursor = conn.cursor()
        try:
            cursor.execute(
                """
                CREATE TABLE IF NOT EXISTS users (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    email TEXT UNIQUE NOT NULL,
                    password_hash TEXT NOT NULL,
                    role TEXT NOT NULL DEFAULT 'admin',
                    is_active INTEGER NOT NULL DEFAULT 1,
                    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
                )
                """
            )
            cursor.execute("PRAGMA table_info(users)")
            columns = {row["name"] for row in cursor.fetchall()}
            additions = {
                "trial_starts_at": "TEXT",
                "trial_ends_at": "TEXT",
                "subscription_status": "TEXT DEFAULT 'trialing'",
                "subscription_started_at": "TEXT",
                "subscription_ends_at": "TEXT",
                "billing_provider": "TEXT",
                "billing_customer_id": "TEXT",
                "billing_subscription_id": "TEXT",
            }
            for name, definition in additions.items():
                if name not in columns:
                    cursor.execute(f"ALTER TABLE users ADD COLUMN {name} {definition}")
            conn.commit()
        finally:
            conn.close()

    def initialize_user_trial(self, user_id: int, role: str = "owner") -> None:
        now = datetime.now()
        status = "active" if str(role).strip().lower() == "admin" else "trialing"
        trial_start = now.isoformat()
        trial_end = (now + timedelta(days=self.TRIAL_DAYS)).isoformat()
        conn = self._get_connection()
        cursor = conn.cursor()
        try:
            cursor.execute(
                """
                UPDATE users
                SET trial_starts_at = COALESCE(trial_starts_at, ?),
                    trial_ends_at = COALESCE(trial_ends_at, ?),
                    subscription_status = COALESCE(subscription_status, ?),
                    updated_at = ?
                WHERE id = ?
                """,
                (trial_start, trial_end, status, now.isoformat(), int(user_id)),
            )
            conn.commit()
        finally:
            conn.close()

    def _persist_status(self, user_id: int, status: str) -> None:
        conn = self._get_connection()
        cursor = conn.cursor()
        try:
            cursor.execute(
                """
                UPDATE users
                SET subscription_status = ?, updated_at = ?
                WHERE id = ?
                """,
                (status, datetime.now().isoformat(), int(user_id)),
            )
            conn.commit()
        finally:
            conn.close()

    def get_summary(self, user_id: Optional[int]) -> Dict:
        default = {
            "user_id": user_id,
            "role": "",
            "subscription_status": "",
            "trial_starts_at": "",
            "trial_ends_at": "",
            "days_left": None,
            "is_admin": False,
            "write_allowed": False,
            "is_expired": False,
            "banner_message": "",
            "status_label": "Unknown",
            "status_tone": "neutral",
            "headline": "",
            "subheadline": "",
            "warning_stage": "",
        }
        if user_id is None:
            return default

        conn = self._get_connection()
        cursor = conn.cursor()
        try:
            cursor.execute(
                """
                SELECT id, role, trial_starts_at, trial_ends_at, subscription_status,
                       subscription_started_at, subscription_ends_at
                FROM users
                WHERE id = ?
                """,
                (int(user_id),),
            )
            row = cursor.fetchone()
        finally:
            conn.close()

        if not row:
            return default

        role = str(row["role"] or "").strip().lower()
        status = str(row["subscription_status"] or "trialing").strip().lower()
        trial_ends_at = str(row["trial_ends_at"] or "").strip()
        is_admin = role == "admin"
        now = datetime.now()
        days_left = None
        is_expired = False

        if is_admin:
            status = "active"
        elif trial_ends_at:
            try:
                ends_at = datetime.fromisoformat(trial_ends_at)
                days_left = max((ends_at.date() - now.date()).days, 0)
                if status == "trialing" and now > ends_at:
                    status = "expired"
                    self._persist_status(int(user_id), status)
            except ValueError:
                days_left = None

        is_expired = status in {"expired", "cancelled", "past_due"}
        write_allowed = is_admin or status in self.WRITE_ALLOWED_STATUSES

        banner_message = ""
        status_label = "Trial"
        status_tone = "info"
        headline = "Your free trial is active."
        subheadline = "You currently have full access to create, edit, send, and manage invoices."
        warning_stage = ""
        if is_admin:
            banner_message = "Admin account: billing restrictions do not apply."
            status_label = "Admin"
            status_tone = "success"
            headline = "Admin account"
            subheadline = "Billing restrictions do not apply to this account."
        elif status == "trialing" and days_left is not None and days_left <= 14:
            banner_message = f"Your free trial ends in {days_left} day{'s' if days_left != 1 else ''}."
            status_label = "Trial"
            status_tone = "warning" if days_left <= 7 else "info"
            if days_left <= 3:
                warning_stage = "final"
            elif days_left <= 7:
                warning_stage = "urgent"
            else:
                warning_stage = "warning"
            headline = f"{days_left} day{'s' if days_left != 1 else ''} left in your free trial."
            subheadline = "You still have full access, but payment will be required soon to keep creating and sending invoices."
        elif is_expired:
            banner_message = "Your free trial has ended. Subscribe to continue creating, editing, sending, and managing invoices."
            status_label = "Expired"
            status_tone = "danger"
            headline = "Your free trial has ended."
            subheadline = "You can still log in and view your data, but action-taking features are locked until billing is activated."
            warning_stage = "expired"
        elif status == "active":
            status_label = "Active"
            status_tone = "success"
            headline = "Billing is active."
            subheadline = "Your account has full access."
        elif status == "past_due":
            status_label = "Past Due"
            status_tone = "danger"
            headline = "Your account is past due."
            subheadline = "View billing to restore full access."
            warning_stage = "expired"
        elif status == "cancelled":
            status_label = "Cancelled"
            status_tone = "danger"
            headline = "Your subscription is cancelled."
            subheadline = "View billing to restore full access."
            warning_stage = "expired"
        elif days_left is not None:
            headline = f"{days_left} day{'s' if days_left != 1 else ''} left in your free trial."
            subheadline = "You currently have full access."

        return {
            "user_id": int(row["id"]),
            "role": role,
            "subscription_status": status,
            "trial_starts_at": str(row["trial_starts_at"] or ""),
            "trial_ends_at": trial_ends_at,
            "days_left": days_left,
            "is_admin": is_admin,
            "write_allowed": write_allowed,
            "is_expired": is_expired,
            "banner_message": banner_message,
            "status_label": status_label,
            "status_tone": status_tone,
            "headline": headline,
            "subheadline": subheadline,
            "warning_stage": warning_stage,
        }
