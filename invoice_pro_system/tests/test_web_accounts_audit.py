from datetime import datetime, timedelta
import sqlite3

from fastapi.testclient import TestClient

from services.invoice_service import InvoiceService
from web.main import app


def _create_min_schema(db_path):
    conn = sqlite3.connect(db_path)
    cur = conn.cursor()
    cur.executescript(
        """
        CREATE TABLE customers (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            name TEXT NOT NULL,
            surname TEXT NOT NULL,
            id_number TEXT UNIQUE NOT NULL,
            company TEXT,
            email TEXT,
            phone TEXT,
            is_active BOOLEAN DEFAULT 1,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        );

        CREATE TABLE invoices (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
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
            updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            FOREIGN KEY (customer_id) REFERENCES customers(id)
        );
        """
    )
    conn.commit()
    conn.close()


def test_accounts_and_audit_pages_available():
    client = TestClient(app)
    r_accounts = client.get("/accounts")
    r_audit = client.get("/audit")

    assert r_accounts.status_code == 200
    assert "Accounts" in r_accounts.text
    assert r_audit.status_code == 200
    assert "Audit Trail" in r_audit.text


def test_update_overdue_statuses_marks_sent_invoice_overdue(tmp_path):
    db_path = tmp_path / "test_business.db"
    _create_min_schema(db_path)

    conn = sqlite3.connect(db_path)
    cur = conn.cursor()
    cur.execute(
        """
        INSERT INTO customers (name, surname, id_number, email, is_active)
        VALUES (?, ?, ?, ?, 1)
        """,
        ("Test", "Customer", "1234567890123", "test@example.com"),
    )
    customer_id = cur.lastrowid

    yesterday = (datetime.now() - timedelta(days=1)).isoformat()
    cur.execute(
        """
        INSERT INTO invoices (
            customer_id, invoice_number, status, subtotal, tax_amount,
            total_amount, amount_paid, balance_due, due_date, invoice_date
        )
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
        (
            customer_id,
            "INV-TEST-001",
            "sent",
            100.0,
            15.0,
            115.0,
            0.0,
            115.0,
            yesterday,
            datetime.now().isoformat(),
        ),
    )
    invoice_id = cur.lastrowid
    conn.commit()
    conn.close()

    service = InvoiceService(str(db_path))
    changed = service.update_overdue_statuses()
    assert changed == 1

    conn = sqlite3.connect(db_path)
    cur = conn.cursor()
    cur.execute("SELECT status FROM invoices WHERE id = ?", (invoice_id,))
    status = cur.fetchone()[0]
    conn.close()
    assert status == "overdue"
