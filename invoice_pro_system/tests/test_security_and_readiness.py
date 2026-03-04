import sqlite3

from services.auth_service import AuthService
from services.invoice_service import InvoiceService
from web.routers import invoices as invoices_router


def _setup_auth_db(db_path):
    conn = sqlite3.connect(db_path)
    try:
        conn.execute(
            """
            CREATE TABLE users (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                email TEXT UNIQUE NOT NULL,
                password_hash TEXT NOT NULL,
                role TEXT NOT NULL DEFAULT 'owner',
                is_active INTEGER NOT NULL DEFAULT 1,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
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
        conn.commit()
    finally:
        conn.close()


def _setup_invoice_db(db_path):
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
            CREATE TABLE customers (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                owner_user_id INTEGER,
                name TEXT NOT NULL,
                surname TEXT NOT NULL,
                id_number TEXT NOT NULL,
                company TEXT,
                email TEXT,
                phone TEXT,
                address TEXT,
                date_registered TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                is_active BOOLEAN DEFAULT 1,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )
            """
        )
        conn.execute(
            """
            CREATE TABLE invoices (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                owner_user_id INTEGER,
                customer_id INTEGER NOT NULL,
                invoice_number TEXT UNIQUE NOT NULL,
                description TEXT,
                status TEXT DEFAULT 'draft',
                subtotal REAL DEFAULT 0.0,
                tax_amount REAL DEFAULT 0.0,
                total_amount REAL DEFAULT 0.0,
                amount_paid REAL DEFAULT 0.0,
                balance_due REAL DEFAULT 0.0,
                currency TEXT DEFAULT 'ZAR',
                due_date TIMESTAMP,
                invoice_date TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                paid_date TIMESTAMP,
                notes TEXT,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )
            """
        )
        conn.execute(
            """
            CREATE TABLE invoice_items (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                invoice_id INTEGER NOT NULL,
                item_description TEXT NOT NULL,
                quantity INTEGER NOT NULL DEFAULT 1,
                unit_price REAL NOT NULL,
                tax_rate REAL DEFAULT 0.15,
                line_total REAL NOT NULL,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
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
            """
            CREATE TABLE business_profiles (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                user_id INTEGER UNIQUE NOT NULL,
                vat_number TEXT
            )
            """
        )
        conn.execute(
            "INSERT INTO users (email, password_hash) VALUES ('u1@example.com', 'x')"
        )
        conn.execute(
            "INSERT INTO users (email, password_hash) VALUES ('u2@example.com', 'x')"
        )
        conn.execute(
            """
            INSERT INTO customers (owner_user_id, name, surname, id_number, email)
            VALUES (1, 'Tenant', 'One', '1234567890123', 'one@example.com')
            """
        )
        conn.commit()
    finally:
        conn.close()


def test_password_reset_token_one_time_and_expiry(tmp_path):
    db_path = tmp_path / "auth_reset.db"
    _setup_auth_db(db_path)
    auth = AuthService(str(db_path), bootstrap_admin=False)
    user = auth.create_user("user@example.com", "StrongPass1!", role="owner")
    assert user is not None

    token = auth.create_password_reset_token("user@example.com", ttl_minutes=30)
    assert token
    assert auth.consume_password_reset_token(token, "NewStrongPass2!") is True
    # one-time token cannot be reused
    assert auth.consume_password_reset_token(token, "AnotherPass3!") is False

    expired = auth.create_password_reset_token("user@example.com", ttl_minutes=30)
    assert expired
    conn = sqlite3.connect(db_path)
    try:
        token_hash = auth._hash_reset_token(expired)
        conn.execute(
            "UPDATE password_reset_tokens SET expires_at = datetime('now', '-1 day') WHERE token_hash = ?",
            (token_hash,),
        )
        conn.commit()
    finally:
        conn.close()
    assert auth.consume_password_reset_token(expired, "NewStrongPass4!") is False


def test_invoice_tenant_isolation_blocks_cross_user_access(tmp_path):
    db_path = tmp_path / "tenant_invoice.db"
    _setup_invoice_db(db_path)
    svc = InvoiceService(str(db_path))
    invoice_id = svc.create_invoice(
        customer_id=1,
        items=[("Item A", 1, 100.0)],
        description="Tenant one invoice",
        due_days=7,
        user_id=1,
    )
    assert invoice_id is not None
    assert svc.get_invoice(invoice_id, user_id=1) is not None
    assert svc.get_invoice(invoice_id, user_id=2) is None


def test_send_readiness_issues(monkeypatch):
    class DummyOAuth:
        def is_google_connected(self, _user_id):
            return False

    class DummyEmail:
        def is_user_smtp_authenticated(self, _user_id):
            return False

    monkeypatch.setattr(invoices_router, "OAuthService", lambda: DummyOAuth())
    monkeypatch.setattr(invoices_router, "EmailService", lambda: DummyEmail())

    issues = invoices_router._send_readiness_issues(
        profile={
            "business_name": "",
            "business_email": "",
            "banking_details": "",
            "smtp_server": "",
            "smtp_port": "",
            "smtp_username": "",
        },
        user_id=10,
    )

    joined = " | ".join(issues)
    assert "Business Name" in joined
    assert "Business Email" in joined
    assert "Banking Details" in joined
    assert "missing" in joined
