import sqlite3

from cryptography.fernet import Fernet

from services.oauth_service import OAuthService


def test_invalid_grant_clears_google_connection_and_prompts_reconnect(tmp_path, monkeypatch):
    db_path = tmp_path / "oauth_invalid_grant.db"
    key = Fernet.generate_key().decode("utf-8")
    monkeypatch.setenv("OAUTH_TOKEN_ENCRYPTION_KEY", key)
    monkeypatch.setenv("GOOGLE_OAUTH_CLIENT_ID", "client-id")
    monkeypatch.setenv("GOOGLE_OAUTH_CLIENT_SECRET", "client-secret")

    conn = sqlite3.connect(db_path)
    try:
        conn.execute(
            """
            CREATE TABLE users (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                email TEXT UNIQUE NOT NULL,
                password_hash TEXT NOT NULL
            )
            """
        )
        conn.execute(
            """
            CREATE TABLE audit_logs (
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
        conn.execute(
            "INSERT INTO users (id, email, password_hash) VALUES (1, 'u@example.com', 'x')"
        )
        conn.commit()
    finally:
        conn.close()

    service = OAuthService(str(db_path))
    encrypted_token = service._encrypt("stale-refresh-token")
    conn = sqlite3.connect(db_path)
    try:
        conn.execute(
            """
            INSERT INTO oauth_connections
            (user_id, provider, provider_account_email, encrypted_refresh_token, scopes, token_uri)
            VALUES (1, 'google', 'u@example.com', ?, 'gmail.send', ?)
            """,
            (encrypted_token, service.GOOGLE_TOKEN_URI),
        )
        conn.commit()
    finally:
        conn.close()

    monkeypatch.setattr(
        service,
        "_post_form_with_retry",
        lambda *args, **kwargs: (
            False,
            {},
            'HTTP 400: {"error": "invalid_grant", "error_description": "Bad Request"}',
        ),
    )

    ok, message = service._get_google_access_token(1)

    assert ok is False
    assert "reconnect Gmail" in message
    assert service.get_google_connection(1) is None
