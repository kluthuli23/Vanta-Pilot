import sqlite3

from services.customer_service import CustomerService


def test_customer_id_number_is_unique_per_owner(tmp_path):
    db_path = tmp_path / "tenant_test.db"
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
                name TEXT NOT NULL,
                surname TEXT NOT NULL,
                id_number TEXT UNIQUE NOT NULL,
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
            "INSERT INTO users (email, password_hash) VALUES ('owner1@example.com', 'x')"
        )
        conn.execute(
            "INSERT INTO users (email, password_hash) VALUES ('owner2@example.com', 'x')"
        )
        conn.commit()
    finally:
        conn.close()

    service = CustomerService(str(db_path))

    first = service.create_customer(
        name="Alice",
        surname="One",
        id_number="1234567890123",
        user_id=1,
    )
    second = service.create_customer(
        name="Bob",
        surname="Two",
        id_number="1234567890123",
        user_id=2,
    )
    duplicate_same_owner = service.create_customer(
        name="Alice",
        surname="Again",
        id_number="1234567890123",
        user_id=1,
    )

    assert first is not None
    assert second is not None
    assert second != first
    assert duplicate_same_owner == first

    owner_one_customers = service.get_all_customers(user_id=1)
    owner_two_customers = service.get_all_customers(user_id=2)
    assert len(owner_one_customers) == 1
    assert len(owner_two_customers) == 1
