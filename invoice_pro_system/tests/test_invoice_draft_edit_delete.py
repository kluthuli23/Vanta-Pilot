import sqlite3

from services.invoice_service import InvoiceService


def _setup_db(db_path):
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
            "INSERT INTO users (email, password_hash) VALUES ('u1@example.com', 'x')"
        )
        conn.execute(
            """
            INSERT INTO customers (owner_user_id, name, surname, id_number, email)
            VALUES (1, 'Test', 'Customer', '1234567890123', 'customer@example.com')
            """
        )
        conn.commit()
    finally:
        conn.close()


def test_edit_and_delete_draft_invoice(tmp_path):
    db_path = tmp_path / "invoice_edit.db"
    _setup_db(db_path)
    svc = InvoiceService(str(db_path))

    invoice_id = svc.create_invoice(
        customer_id=1,
        items=[("Item A", 1, 100.0)],
        description="Original",
        due_days=7,
        user_id=1,
    )
    assert invoice_id is not None

    ok_edit = svc.update_draft_invoice(
        invoice_id=invoice_id,
        items=[("Item B", 2, 200.0)],
        description="Updated",
        due_date="2026-03-01",
        user_id=1,
    )
    assert ok_edit is True
    inv = svc.get_invoice(invoice_id, user_id=1)
    assert inv["description"] == "Updated"
    assert len(inv["items"]) == 1
    assert inv["items"][0]["item_description"] == "Item B"
    assert float(inv["total_amount"]) > 0

    assert svc.update_invoice_status(invoice_id, "sent", user_id=1) is True
    assert (
        svc.update_draft_invoice(
            invoice_id=invoice_id,
            items=[("Nope", 1, 1.0)],
            description="Should fail",
            user_id=1,
        )
        is False
    )
    assert "draft" in (svc.get_last_error() or "").lower()

    draft_to_delete = svc.create_invoice(
        customer_id=1,
        items=[("Delete me", 1, 10.0)],
        description="Temp",
        due_days=7,
        user_id=1,
    )
    assert draft_to_delete is not None
    assert svc.delete_draft_invoice(draft_to_delete, user_id=1) is True
    assert svc.get_invoice(draft_to_delete, user_id=1) is None
