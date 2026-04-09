import base64
import json
import os
import sqlite3
import time
import urllib.parse
import urllib.request
import urllib.error
from datetime import datetime
from typing import Dict, Optional, Tuple

from database.safety import ensure_schema_backup, get_db_path
from services.audit_service import AuditService

try:
    from dotenv import load_dotenv
except Exception:  # pragma: no cover
    load_dotenv = None

try:
    from cryptography.fernet import Fernet
except Exception:  # pragma: no cover
    Fernet = None


class OAuthService:
    """Google OAuth connection and Gmail API sender."""

    GOOGLE_AUTH_URI = "https://accounts.google.com/o/oauth2/v2/auth"
    GOOGLE_TOKEN_URI = "https://oauth2.googleapis.com/token"
    GOOGLE_USERINFO_URI = "https://www.googleapis.com/oauth2/v2/userinfo"
    GMAIL_SEND_URI = "https://gmail.googleapis.com/gmail/v1/users/me/messages/send"

    def __init__(self, db_path=None):
        if load_dotenv is not None:
            # Ensure OAuth env vars are available regardless of import order.
            load_dotenv()
        self.db_path = get_db_path(db_path)
        self.db_path.parent.mkdir(exist_ok=True)
        self.audit_service = AuditService(str(self.db_path))
        self._ensure_table()

    def _get_connection(self):
        conn = sqlite3.connect(self.db_path)
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA foreign_keys = ON")
        return conn

    def _ensure_table(self):
        ensure_schema_backup(self.db_path, reason="oauth")
        conn = self._get_connection()
        cursor = conn.cursor()
        try:
            cursor.execute(
                """
                CREATE TABLE IF NOT EXISTS oauth_connections (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    user_id INTEGER NOT NULL,
                    provider TEXT NOT NULL,
                    provider_account_email TEXT,
                    encrypted_refresh_token TEXT NOT NULL,
                    scopes TEXT,
                    token_uri TEXT,
                    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                    UNIQUE(user_id, provider),
                    FOREIGN KEY (user_id) REFERENCES users(id) ON DELETE CASCADE
                )
                """
            )
            conn.commit()
        finally:
            conn.close()

    def _post_form_with_retry(
        self,
        url: str,
        form_data: Dict[str, str],
        retries: int = 3,
        timeout: int = 30,
    ) -> Tuple[bool, Dict, str]:
        """POST form-urlencoded data and parse JSON with retry for transient network errors."""
        last_error = "Unknown network error."
        for attempt in range(1, retries + 1):
            payload = urllib.parse.urlencode(form_data).encode("utf-8")
            req = urllib.request.Request(
                url,
                data=payload,
                headers={
                    "Content-Type": "application/x-www-form-urlencoded",
                    "User-Agent": "VantaPilot/1.0",
                },
            )
            try:
                with urllib.request.urlopen(req, timeout=timeout) as resp:
                    return True, json.loads(resp.read().decode("utf-8")), ""
            except urllib.error.HTTPError as e:
                try:
                    body = e.read().decode("utf-8", errors="ignore")
                except Exception:
                    body = ""
                return False, {}, f"HTTP {e.code}: {body or e.reason}"
            except Exception as e:
                last_error = str(e)
                if attempt < retries:
                    time.sleep(1.0 * attempt)
                else:
                    break
        return False, {}, last_error

    def _get_fernet(self) -> Optional[Fernet]:
        key = os.getenv("OAUTH_TOKEN_ENCRYPTION_KEY", "").strip()
        if not key or Fernet is None:
            return None
        try:
            return Fernet(key.encode("utf-8"))
        except Exception:
            return None

    def _encrypt(self, plaintext: str) -> Optional[str]:
        f = self._get_fernet()
        if not f:
            return None
        return f.encrypt(plaintext.encode("utf-8")).decode("utf-8")

    def _decrypt(self, ciphertext: str) -> Optional[str]:
        f = self._get_fernet()
        if not f:
            return None
        try:
            return f.decrypt(ciphertext.encode("utf-8")).decode("utf-8")
        except Exception:
            return None

    def get_google_connection(self, user_id: int) -> Optional[Dict]:
        conn = self._get_connection()
        cursor = conn.cursor()
        try:
            cursor.execute(
                """
                SELECT *
                FROM oauth_connections
                WHERE user_id = ? AND provider = 'google'
                """,
                (int(user_id),),
            )
            row = cursor.fetchone()
            return dict(row) if row else None
        finally:
            conn.close()

    def is_google_connected(self, user_id: int) -> bool:
        return self.get_google_connection(user_id) is not None

    def clear_google_connection(self, user_id: int) -> bool:
        conn = self._get_connection()
        cursor = conn.cursor()
        try:
            cursor.execute(
                """
                DELETE FROM oauth_connections
                WHERE user_id = ? AND provider = 'google'
                """,
                (int(user_id),),
            )
            conn.commit()
            self.audit_service.log_action(
                event_type="oauth_disconnected",
                entity_type="user",
                entity_id=int(user_id),
                source="web",
                details={"provider": "google"},
            )
            return True
        except Exception:
            conn.rollback()
            return False
        finally:
            conn.close()

    def build_google_auth_url(self, redirect_uri: str, state: str) -> Tuple[bool, str]:
        client_id = os.getenv("GOOGLE_OAUTH_CLIENT_ID", "").strip()
        if not client_id:
            return False, "GOOGLE_OAUTH_CLIENT_ID is not configured."
        params = {
            "client_id": client_id,
            "redirect_uri": redirect_uri,
            "response_type": "code",
            "scope": "openid email https://www.googleapis.com/auth/gmail.send",
            "access_type": "offline",
            "prompt": "consent",
            "include_granted_scopes": "true",
            "state": state,
        }
        return True, f"{self.GOOGLE_AUTH_URI}?{urllib.parse.urlencode(params)}"

    def exchange_google_code(
        self,
        user_id: int,
        code: str,
        redirect_uri: str,
    ) -> Tuple[bool, str]:
        client_id = os.getenv("GOOGLE_OAUTH_CLIENT_ID", "").strip()
        client_secret = os.getenv("GOOGLE_OAUTH_CLIENT_SECRET", "").strip()
        if not client_id or not client_secret:
            return False, "Google OAuth client ID/secret are not configured."
        encrypted = self._encrypt("probe")
        if encrypted is None:
            return False, "OAUTH_TOKEN_ENCRYPTION_KEY is missing or invalid."

        ok, data, err = self._post_form_with_retry(
            self.GOOGLE_TOKEN_URI,
            {
                "code": code,
                "client_id": client_id,
                "client_secret": client_secret,
                "redirect_uri": redirect_uri,
                "grant_type": "authorization_code",
            },
            retries=3,
            timeout=30,
        )
        if not ok:
            return False, f"Failed token exchange: {err}"

        refresh_token = (data.get("refresh_token") or "").strip()
        access_token = (data.get("access_token") or "").strip()
        if not refresh_token:
            return False, "Google did not return a refresh token. Reconnect with consent."
        if not access_token:
            return False, "Google did not return an access token."

        account_email = ""
        try:
            req_user = urllib.request.Request(
                self.GOOGLE_USERINFO_URI,
                headers={"Authorization": f"Bearer {access_token}"},
            )
            with urllib.request.urlopen(req_user, timeout=30) as resp:
                userinfo = json.loads(resp.read().decode("utf-8"))
                account_email = (userinfo.get("email") or "").strip().lower()
        except Exception:
            account_email = ""

        refresh_token_enc = self._encrypt(refresh_token)
        if not refresh_token_enc:
            return False, "Failed to encrypt refresh token."

        conn = self._get_connection()
        cursor = conn.cursor()
        try:
            cursor.execute(
                """
                INSERT INTO oauth_connections
                (user_id, provider, provider_account_email, encrypted_refresh_token, scopes, token_uri, created_at, updated_at)
                VALUES (?, 'google', ?, ?, ?, ?, ?, ?)
                ON CONFLICT(user_id, provider) DO UPDATE SET
                    provider_account_email = excluded.provider_account_email,
                    encrypted_refresh_token = excluded.encrypted_refresh_token,
                    scopes = excluded.scopes,
                    token_uri = excluded.token_uri,
                    updated_at = excluded.updated_at
                """,
                (
                    int(user_id),
                    account_email,
                    refresh_token_enc,
                    data.get("scope", ""),
                    self.GOOGLE_TOKEN_URI,
                    datetime.now().isoformat(),
                    datetime.now().isoformat(),
                ),
            )
            conn.commit()
            self.audit_service.log_action(
                event_type="oauth_connected",
                entity_type="user",
                entity_id=int(user_id),
                source="web",
                details={"provider": "google", "email": account_email},
            )
            return True, "Google account connected."
        except Exception as e:
            conn.rollback()
            return False, f"Failed saving OAuth connection: {e}"
        finally:
            conn.close()

    def _get_google_access_token(self, user_id: int) -> Tuple[bool, str]:
        connection = self.get_google_connection(user_id)
        if not connection:
            return False, "Google account is not connected."
        refresh_token_enc = connection.get("encrypted_refresh_token")
        refresh_token = self._decrypt(refresh_token_enc or "")
        if not refresh_token:
            # Stored token cannot be decrypted (likely key mismatch or rotated key).
            # Clear stale connection so user can reconnect cleanly.
            self.clear_google_connection(user_id)
            return False, "Stored Gmail authorization is no longer valid. Please reconnect Gmail in Settings."

        client_id = os.getenv("GOOGLE_OAUTH_CLIENT_ID", "").strip()
        client_secret = os.getenv("GOOGLE_OAUTH_CLIENT_SECRET", "").strip()
        if not client_id or not client_secret:
            return False, "Google OAuth client ID/secret are not configured."

        ok, data, err = self._post_form_with_retry(
            self.GOOGLE_TOKEN_URI,
            {
                "client_id": client_id,
                "client_secret": client_secret,
                "refresh_token": refresh_token,
                "grant_type": "refresh_token",
            },
            retries=3,
            timeout=30,
        )
        if not ok:
            return False, f"Failed refreshing Google token: {err}"
        token = (data.get("access_token") or "").strip()
        if not token:
            return False, "Google did not return access token."
        return True, token

    def send_gmail_message(self, user_id: int, mime_bytes: bytes) -> Tuple[bool, str]:
        ok, token_or_error = self._get_google_access_token(user_id)
        if not ok:
            return False, token_or_error

        raw_b64 = base64.urlsafe_b64encode(mime_bytes).decode("utf-8").rstrip("=")
        body = json.dumps({"raw": raw_b64}).encode("utf-8")
        req = urllib.request.Request(
            self.GMAIL_SEND_URI,
            data=body,
            headers={
                "Authorization": f"Bearer {token_or_error}",
                "Content-Type": "application/json",
            },
        )
        try:
            with urllib.request.urlopen(req, timeout=30):
                return True, "Sent via Gmail API."
        except Exception as e:
            return False, f"Gmail send failed: {e}"
