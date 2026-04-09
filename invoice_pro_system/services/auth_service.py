import hashlib
import os
import secrets
import sqlite3
from datetime import datetime, timedelta
from typing import Dict, Optional

from database.safety import ensure_schema_backup, get_db_path
from services.audit_service import AuditService
from services.subscription_service import SubscriptionService


class AuthService:
    """Simple local authentication service (session-based)."""

    def __init__(self, db_path=None, bootstrap_admin: bool = True):
        self.db_path = get_db_path(db_path)
        self.db_path.parent.mkdir(exist_ok=True)
        self.audit_service = AuditService(str(self.db_path))
        self._ensure_table()
        if bootstrap_admin:
            self._ensure_default_admin()

    def _get_connection(self):
        conn = sqlite3.connect(self.db_path)
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA foreign_keys = ON")
        return conn

    def _ensure_table(self):
        ensure_schema_backup(self.db_path, reason="auth")
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
            cursor.execute(
                """
                CREATE TABLE IF NOT EXISTS password_reset_tokens (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    user_id INTEGER NOT NULL,
                    token_hash TEXT NOT NULL UNIQUE,
                    expires_at TIMESTAMP NOT NULL,
                    used_at TIMESTAMP,
                    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                    FOREIGN KEY (user_id) REFERENCES users(id) ON DELETE CASCADE
                )
                """
            )
            conn.commit()
            SubscriptionService(str(self.db_path))
        finally:
            conn.close()

    def _hash_password(self, password: str, salt_hex: Optional[str] = None) -> str:
        salt = bytes.fromhex(salt_hex) if salt_hex else secrets.token_bytes(16)
        digest = hashlib.pbkdf2_hmac(
            "sha256", password.encode("utf-8"), salt, 100_000
        ).hex()
        return f"{salt.hex()}${digest}"

    def _verify_password(self, password: str, stored_hash: str) -> bool:
        try:
            salt_hex, expected_digest = stored_hash.split("$", 1)
        except ValueError:
            return False
        candidate = self._hash_password(password, salt_hex=salt_hex).split("$", 1)[1]
        return secrets.compare_digest(candidate, expected_digest)

    def _ensure_default_admin(self):
        admin_email = os.getenv("ADMIN_EMAIL", "admin@vantapilot.local").strip().lower()
        admin_password = os.getenv("ADMIN_PASSWORD", "ChangeMe123!")

        conn = self._get_connection()
        cursor = conn.cursor()
        try:
            cursor.execute("SELECT id FROM users WHERE email = ?", (admin_email,))
            if cursor.fetchone():
                return
            cursor.execute(
                """
                INSERT INTO users (email, password_hash, role, is_active, created_at, updated_at)
                VALUES (?, ?, 'admin', 1, ?, ?)
                """,
                (
                    admin_email,
                    self._hash_password(admin_password),
                    datetime.now().isoformat(),
                    datetime.now().isoformat(),
                ),
            )
            conn.commit()
            self.audit_service.log_action(
                event_type="default_admin_created",
                entity_type="user",
                entity_id=cursor.lastrowid,
                source="system",
                details={"email": admin_email},
            )
        finally:
            conn.close()

    def authenticate(self, email: str, password: str) -> Optional[Dict]:
        conn = self._get_connection()
        cursor = conn.cursor()
        try:
            cursor.execute(
                """
                SELECT id, email, password_hash, role, is_active
                FROM users
                WHERE email = ?
                """,
                (email.strip().lower(),),
            )
            row = cursor.fetchone()
            if not row or not row["is_active"]:
                return None
            if not self._verify_password(password, row["password_hash"]):
                return None
            user = dict(row)
            user.pop("password_hash", None)
            self.audit_service.log_action(
                event_type="user_login",
                entity_type="user",
                entity_id=user["id"],
                source="web",
                details={"email": user["email"], "role": user["role"]},
            )
            return user
        except Exception:
            return None
        finally:
            conn.close()

    def get_user_by_email(self, email: str) -> Optional[Dict]:
        """Get active user metadata by email."""
        conn = self._get_connection()
        cursor = conn.cursor()
        try:
            cursor.execute(
                """
                SELECT id, email, role, is_active
                FROM users
                WHERE email = ?
                """,
                ((email or "").strip().lower(),),
            )
            row = cursor.fetchone()
            if not row or not int(row["is_active"]):
                return None
            return dict(row)
        except Exception:
            return None
        finally:
            conn.close()

    def get_user_by_id(self, user_id: int) -> Optional[Dict]:
        """Get active user metadata by id."""
        conn = self._get_connection()
        cursor = conn.cursor()
        try:
            cursor.execute(
                """
                SELECT id, email, role, is_active
                FROM users
                WHERE id = ?
                """,
                (int(user_id),),
            )
            row = cursor.fetchone()
            if not row or not int(row["is_active"]):
                return None
            return dict(row)
        except Exception:
            return None
        finally:
            conn.close()

    def create_user(self, email: str, password: str, role: str = "owner") -> Optional[Dict]:
        email = (email or "").strip().lower()
        if not email or "@" not in email:
            return None
        if not password or len(password) < 8:
            return None

        conn = self._get_connection()
        cursor = conn.cursor()
        try:
            cursor.execute("SELECT id FROM users WHERE email = ?", (email,))
            if cursor.fetchone():
                return None
            cursor.execute(
                """
                INSERT INTO users (
                    email, password_hash, role, is_active, created_at, updated_at,
                    trial_starts_at, trial_ends_at, subscription_status
                )
                VALUES (?, ?, ?, 1, ?, ?, ?, ?, ?)
                """,
                (
                    email,
                    self._hash_password(password),
                    role,
                    datetime.now().isoformat(),
                    datetime.now().isoformat(),
                    datetime.now().isoformat(),
                    (datetime.now() + timedelta(days=SubscriptionService.TRIAL_DAYS)).isoformat(),
                    "active" if role == "admin" else "trialing",
                ),
            )
            conn.commit()
            user_id = cursor.lastrowid
            SubscriptionService(str(self.db_path)).initialize_user_trial(user_id, role=role)
            self.audit_service.log_action(
                event_type="user_created",
                entity_type="user",
                entity_id=user_id,
                source="web",
                details={"email": email, "role": role},
            )
            return {"id": user_id, "email": email, "role": role}
        except Exception:
            conn.rollback()
            return None
        finally:
            conn.close()

    def _hash_reset_token(self, token: str) -> str:
        return hashlib.sha256((token or "").encode("utf-8")).hexdigest()

    def create_password_reset_token(self, email: str, ttl_minutes: int = 30) -> Optional[str]:
        """Create one-time password reset token for a user email."""
        email = (email or "").strip().lower()
        if not email:
            return None
        conn = self._get_connection()
        cursor = conn.cursor()
        try:
            cursor.execute("SELECT id, is_active FROM users WHERE email = ?", (email,))
            row = cursor.fetchone()
            if not row or not int(row["is_active"]):
                return None
            user_id = int(row["id"])
            token = secrets.token_urlsafe(32)
            token_hash = self._hash_reset_token(token)
            expires_at = (datetime.now() + timedelta(minutes=max(5, ttl_minutes))).isoformat()
            cursor.execute(
                """
                INSERT INTO password_reset_tokens (user_id, token_hash, expires_at, used_at, created_at)
                VALUES (?, ?, ?, NULL, ?)
                """,
                (user_id, token_hash, expires_at, datetime.now().isoformat()),
            )
            conn.commit()
            self.audit_service.log_action(
                event_type="password_reset_requested",
                entity_type="user",
                entity_id=user_id,
                source="web",
                details={"email": email},
            )
            return token
        except Exception:
            conn.rollback()
            return None
        finally:
            conn.close()

    def consume_password_reset_token(self, token: str, new_password: str) -> bool:
        """Consume reset token and update password."""
        if not token or not new_password or len(new_password) < 8:
            return False
        token_hash = self._hash_reset_token(token)
        conn = self._get_connection()
        cursor = conn.cursor()
        try:
            cursor.execute(
                """
                SELECT id, user_id, expires_at, used_at
                FROM password_reset_tokens
                WHERE token_hash = ?
                """,
                (token_hash,),
            )
            row = cursor.fetchone()
            if not row:
                return False
            if row["used_at"]:
                return False
            try:
                expires_at = datetime.fromisoformat(str(row["expires_at"]))
            except Exception:
                return False
            if expires_at < datetime.now():
                return False
            user_id = int(row["user_id"])
            now_iso = datetime.now().isoformat()
            cursor.execute(
                "UPDATE users SET password_hash = ?, updated_at = ? WHERE id = ?",
                (self._hash_password(new_password), now_iso, user_id),
            )
            cursor.execute(
                "UPDATE password_reset_tokens SET used_at = ? WHERE id = ?",
                (now_iso, int(row["id"])),
            )
            # Revoke any other outstanding reset links for safety.
            cursor.execute(
                """
                UPDATE password_reset_tokens
                SET used_at = ?
                WHERE user_id = ? AND used_at IS NULL
                """,
                (now_iso, user_id),
            )
            conn.commit()
            self.audit_service.log_action(
                event_type="password_reset_completed",
                entity_type="user",
                entity_id=user_id,
                source="web",
                details={},
            )
            return True
        except Exception:
            conn.rollback()
            return False
        finally:
            conn.close()
