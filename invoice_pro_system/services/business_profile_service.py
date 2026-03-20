import os
import re
import shutil
import sqlite3
from datetime import datetime
from pathlib import Path
from typing import Dict, Optional

from config.settings import config

try:
    from cryptography.fernet import Fernet
except Exception:  # pragma: no cover
    Fernet = None


class BusinessProfileService:
    """Manage per-user business profile and branding assets."""

    def __init__(self, db_path=None):
        if db_path is None:
            self.db_path = Path(__file__).parent.parent / "data" / "business.db"
        else:
            self.db_path = Path(db_path)
        self.db_path.parent.mkdir(exist_ok=True)
        self.static_upload_dir = Path(__file__).parent.parent / "web" / "static" / "uploads" / "logos"
        self.static_upload_dir.mkdir(parents=True, exist_ok=True)
        self._ensure_table()

    def _get_connection(self):
        conn = sqlite3.connect(self.db_path)
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA foreign_keys = ON")
        return conn

    def _get_fernet(self):
        key = (
            os.getenv("SMTP_CREDENTIAL_ENCRYPTION_KEY", "").strip()
            or os.getenv("OAUTH_TOKEN_ENCRYPTION_KEY", "").strip()
        )
        if not key or Fernet is None:
            return None
        try:
            return Fernet(key.encode("utf-8"))
        except Exception:
            return None

    def encrypt_smtp_password(self, password: str) -> str:
        text = str(password or "").strip()
        if not text:
            return ""
        fernet = self._get_fernet()
        if not fernet:
            raise ValueError(
                "SMTP_CREDENTIAL_ENCRYPTION_KEY or OAUTH_TOKEN_ENCRYPTION_KEY must be configured."
            )
        return fernet.encrypt(text.encode("utf-8")).decode("utf-8")

    def decrypt_smtp_password(self, encrypted_password: str) -> str:
        text = str(encrypted_password or "").strip()
        if not text:
            return ""
        fernet = self._get_fernet()
        if not fernet:
            return ""
        try:
            return fernet.decrypt(text.encode("utf-8")).decode("utf-8")
        except Exception:
            return ""

    def _ensure_table(self):
        conn = self._get_connection()
        cursor = conn.cursor()
        try:
            cursor.execute(
                """
                CREATE TABLE IF NOT EXISTS business_profiles (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    user_id INTEGER UNIQUE NOT NULL,
                    business_name TEXT,
                    business_address TEXT,
                    business_phone TEXT,
                    business_email TEXT,
                    vat_number TEXT,
                    banking_details TEXT,
                    smtp_server TEXT,
                    smtp_port INTEGER,
                    smtp_username TEXT,
                    smtp_password TEXT,
                    smtp_from_email TEXT,
                    smtp_use_tls INTEGER DEFAULT 1,
                    smtp_use_ssl INTEGER DEFAULT 0,
                    logo_file_path TEXT,
                    logo_web_path TEXT,
                    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                    FOREIGN KEY (user_id) REFERENCES users(id) ON DELETE CASCADE
                )
                """
            )
            cursor.execute("PRAGMA table_info(business_profiles)")
            columns = {row["name"] for row in cursor.fetchall()}
            if "banking_details" not in columns:
                cursor.execute(
                    "ALTER TABLE business_profiles ADD COLUMN banking_details TEXT"
                )
            if "smtp_server" not in columns:
                cursor.execute("ALTER TABLE business_profiles ADD COLUMN smtp_server TEXT")
            if "smtp_port" not in columns:
                cursor.execute("ALTER TABLE business_profiles ADD COLUMN smtp_port INTEGER")
            if "smtp_username" not in columns:
                cursor.execute("ALTER TABLE business_profiles ADD COLUMN smtp_username TEXT")
            if "smtp_password" not in columns:
                cursor.execute("ALTER TABLE business_profiles ADD COLUMN smtp_password TEXT")
            if "smtp_from_email" not in columns:
                cursor.execute("ALTER TABLE business_profiles ADD COLUMN smtp_from_email TEXT")
            if "smtp_use_tls" not in columns:
                cursor.execute("ALTER TABLE business_profiles ADD COLUMN smtp_use_tls INTEGER DEFAULT 1")
            if "smtp_use_ssl" not in columns:
                cursor.execute("ALTER TABLE business_profiles ADD COLUMN smtp_use_ssl INTEGER DEFAULT 0")
            conn.commit()
        finally:
            conn.close()

    def get_profile(self, user_id: int) -> Dict:
        conn = self._get_connection()
        cursor = conn.cursor()
        try:
            cursor.execute(
                "SELECT * FROM business_profiles WHERE user_id = ?",
                (user_id,),
            )
            row = cursor.fetchone()
            if row:
                return dict(row)
            return {
                "user_id": user_id,
                "business_name": config.BUSINESS_NAME,
                "business_address": "",
                "business_phone": "",
                "business_email": "",
                "vat_number": config.BUSINESS_VAT_NUMBER,
                "banking_details": "",
                "smtp_server": "",
                "smtp_port": 587,
                "smtp_username": "",
                "smtp_password": "",
                "smtp_from_email": "",
                "smtp_use_tls": 1,
                "smtp_use_ssl": 0,
                "logo_file_path": "",
                "logo_web_path": "",
            }
        finally:
            conn.close()

    def _save_logo(self, user_id: int, upload) -> Optional[Dict[str, str]]:
        if not upload or not getattr(upload, "filename", ""):
            return None
        filename = upload.filename
        ext = Path(filename).suffix.lower()
        if ext not in {".png", ".jpg", ".jpeg", ".gif", ".webp"}:
            return None
        safe_name = f"user_{user_id}{ext}"
        target = self.static_upload_dir / safe_name
        with target.open("wb") as f:
            shutil.copyfileobj(upload.file, f)
        return {
            "logo_file_path": str(target.resolve()),
            "logo_web_path": f"/static/uploads/logos/{safe_name}",
        }

    def upsert_profile(
        self,
        user_id: int,
        business_name: str,
        business_address: str,
        business_phone: str,
        business_email: str,
        vat_number: str,
        banking_details: str = "",
        smtp_server: str = "",
        smtp_port: int = 587,
        smtp_username: str = "",
        smtp_password: str = "",
        smtp_from_email: str = "",
        smtp_use_tls: bool = True,
        smtp_use_ssl: bool = False,
        logo_upload=None,
    ) -> bool:
        logo_data = self._save_logo(user_id, logo_upload)
        conn = self._get_connection()
        cursor = conn.cursor()
        try:
            current = self.get_profile(user_id)
            vat_digits = re.sub(r"\D", "", str(vat_number or ""))
            normalized_vat = vat_digits if len(vat_digits) == 10 else ""
            logo_file_path = (logo_data or {}).get("logo_file_path", current.get("logo_file_path"))
            logo_web_path = (logo_data or {}).get("logo_web_path", current.get("logo_web_path"))
            cursor.execute(
                """
                INSERT INTO business_profiles
                (user_id, business_name, business_address, business_phone, business_email,
                 vat_number, banking_details,
                 smtp_server, smtp_port, smtp_username, smtp_password, smtp_from_email, smtp_use_tls, smtp_use_ssl,
                 logo_file_path, logo_web_path, created_at, updated_at)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(user_id) DO UPDATE SET
                    business_name = excluded.business_name,
                    business_address = excluded.business_address,
                    business_phone = excluded.business_phone,
                    business_email = excluded.business_email,
                    vat_number = excluded.vat_number,
                    banking_details = excluded.banking_details,
                    smtp_server = excluded.smtp_server,
                    smtp_port = excluded.smtp_port,
                    smtp_username = excluded.smtp_username,
                    smtp_password = excluded.smtp_password,
                    smtp_from_email = excluded.smtp_from_email,
                    smtp_use_tls = excluded.smtp_use_tls,
                    smtp_use_ssl = excluded.smtp_use_ssl,
                    logo_file_path = excluded.logo_file_path,
                    logo_web_path = excluded.logo_web_path,
                    updated_at = excluded.updated_at
                """,
                (
                    user_id,
                    (business_name or "").strip(),
                    (business_address or "").strip(),
                    (business_phone or "").strip(),
                    (business_email or "").strip().lower(),
                    normalized_vat,
                    (banking_details or "").strip(),
                    (smtp_server or "").strip(),
                    int(smtp_port) if smtp_port else 587,
                    (smtp_username or "").strip(),
                    "",
                    (smtp_from_email or "").strip().lower(),
                    1 if smtp_use_tls else 0,
                    1 if smtp_use_ssl else 0,
                    logo_file_path or "",
                    logo_web_path or "",
                    datetime.now().isoformat(),
                    datetime.now().isoformat(),
                ),
            )
            conn.commit()
            return True
        except Exception:
            conn.rollback()
            return False
        finally:
            conn.close()

    def store_smtp_password(self, user_id: int, smtp_password: str) -> bool:
        conn = self._get_connection()
        cursor = conn.cursor()
        try:
            encrypted_password = self.encrypt_smtp_password(smtp_password)
            cursor.execute(
                """
                UPDATE business_profiles
                SET smtp_password = ?, updated_at = ?
                WHERE user_id = ?
                """,
                (
                    encrypted_password,
                    datetime.now().isoformat(),
                    int(user_id),
                ),
            )
            conn.commit()
            return cursor.rowcount > 0
        except Exception:
            conn.rollback()
            return False
        finally:
            conn.close()

    def clear_smtp_password(self, user_id: int) -> bool:
        conn = self._get_connection()
        cursor = conn.cursor()
        try:
            cursor.execute(
                """
                UPDATE business_profiles
                SET smtp_password = '', updated_at = ?
                WHERE user_id = ?
                """,
                (
                    datetime.now().isoformat(),
                    int(user_id),
                ),
            )
            conn.commit()
            return cursor.rowcount > 0
        except Exception:
            conn.rollback()
            return False
        finally:
            conn.close()
