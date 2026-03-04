import sqlite3

from services.business_profile_service import BusinessProfileService


def test_business_profile_stores_banking_details_per_user(tmp_path):
    db_path = tmp_path / "profile_test.db"
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
            "INSERT INTO users (email, password_hash) VALUES ('u1@example.com', 'x')"
        )
        conn.execute(
            "INSERT INTO users (email, password_hash) VALUES ('u2@example.com', 'x')"
        )
        conn.commit()
    finally:
        conn.close()

    svc = BusinessProfileService(str(db_path))
    assert svc.upsert_profile(
        user_id=1,
        business_name="One Co",
        business_address="Address 1",
        business_phone="111",
        business_email="one@example.com",
        vat_number="VAT1",
        banking_details="Bank A\nAcc 123",
    )
    assert svc.upsert_profile(
        user_id=2,
        business_name="Two Co",
        business_address="Address 2",
        business_phone="222",
        business_email="two@example.com",
        vat_number="VAT2",
        banking_details="Bank B\nAcc 999",
    )

    p1 = svc.get_profile(1)
    p2 = svc.get_profile(2)
    assert p1["business_name"] == "One Co"
    assert p2["business_name"] == "Two Co"
    assert p1["banking_details"] == "Bank A\nAcc 123"
    assert p2["banking_details"] == "Bank B\nAcc 999"
