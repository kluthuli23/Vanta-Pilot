#!/usr/bin/env python3
"""Seed realistic demo data for Vanta Pilot."""

from __future__ import annotations

import argparse
import sqlite3
import sys
from datetime import datetime, timedelta
from pathlib import Path

from database.init import init_database
from services.auth_service import AuthService
from services.business_profile_service import BusinessProfileService
from services.customer_service import CustomerService
from services.invoice_service import InvoiceService
from services.payment_service import PaymentService

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")


PROJECT_ROOT = Path(__file__).resolve().parent
DB_PATH = PROJECT_ROOT / "data" / "business.db"
DEMO_EMAILS = [
    "demo_owner_1@vantapilot.demo",
    "demo_owner_2@vantapilot.demo",
]


def _connect():
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    return conn


def _demo_user_ids() -> list[int]:
    conn = _connect()
    try:
        cur = conn.cursor()
        cur.execute(
            """
            SELECT id
            FROM users
            WHERE email IN (?, ?)
            """,
            (DEMO_EMAILS[0], DEMO_EMAILS[1]),
        )
        return [int(r["id"]) for r in cur.fetchall()]
    finally:
        conn.close()


def _reset_demo_data() -> None:
    user_ids = _demo_user_ids()
    if not user_ids:
        return
    conn = _connect()
    try:
        cur = conn.cursor()
        placeholders = ",".join(["?"] * len(user_ids))
        # Invoices owned by demo users
        cur.execute(
            f"SELECT id FROM invoices WHERE owner_user_id IN ({placeholders})",
            user_ids,
        )
        invoice_ids = [int(r["id"]) for r in cur.fetchall()]

        if invoice_ids:
            inv_ph = ",".join(["?"] * len(invoice_ids))
            cur.execute(f"DELETE FROM reminder_events WHERE invoice_id IN ({inv_ph})", invoice_ids)
            cur.execute(f"DELETE FROM payments WHERE invoice_id IN ({inv_ph})", invoice_ids)
            cur.execute(f"DELETE FROM invoice_items WHERE invoice_id IN ({inv_ph})", invoice_ids)
            cur.execute(f"DELETE FROM invoices WHERE id IN ({inv_ph})", invoice_ids)

        # Customers owned by demo users
        cur.execute(
            f"SELECT id FROM customers WHERE owner_user_id IN ({placeholders})",
            user_ids,
        )
        customer_ids = [int(r["id"]) for r in cur.fetchall()]
        if customer_ids:
            c_ph = ",".join(["?"] * len(customer_ids))
            cur.execute(
                f"DELETE FROM customer_reminder_settings WHERE customer_id IN ({c_ph})",
                customer_ids,
            )
            cur.execute(f"DELETE FROM customers WHERE id IN ({c_ph})", customer_ids)

        # User-linked tables
        cur.execute(f"DELETE FROM oauth_connections WHERE user_id IN ({placeholders})", user_ids)
        cur.execute(f"DELETE FROM password_reset_tokens WHERE user_id IN ({placeholders})", user_ids)
        cur.execute(f"DELETE FROM business_profiles WHERE user_id IN ({placeholders})", user_ids)
        cur.execute(f"DELETE FROM users WHERE id IN ({placeholders})", user_ids)
        conn.commit()
    finally:
        conn.close()


def _set_invoice_due_date(invoice_id: int, due_date: datetime) -> None:
    conn = _connect()
    try:
        conn.execute(
            """
            UPDATE invoices
            SET due_date = ?, updated_at = ?
            WHERE id = ?
            """,
            (due_date.isoformat(), datetime.now().isoformat(), int(invoice_id)),
        )
        conn.commit()
    finally:
        conn.close()


def _create_invoice_with_status(
    invoice_service: InvoiceService,
    payment_service: PaymentService,
    user_id: int,
    customer_id: int,
    description: str,
    items: list[tuple[str, int, float]],
    due_days: int,
    target_status: str,
) -> int:
    invoice_id = invoice_service.create_invoice(
        customer_id=customer_id,
        items=items,
        description=description,
        due_days=due_days,
        user_id=user_id,
    )
    if not invoice_id:
        raise RuntimeError(invoice_service.get_last_error() or "Failed to create invoice")

    if target_status in {"sent", "partial", "overdue", "paid"}:
        ok = invoice_service.update_invoice_status(invoice_id, "sent", user_id=user_id)
        if not ok:
            raise RuntimeError(invoice_service.get_last_error() or "Failed to set sent status")

    if target_status == "partial":
        inv = invoice_service.get_invoice(invoice_id, user_id=user_id)
        amount = round(float(inv["total_amount"]) * 0.4, 2)
        payment_id = payment_service.record_payment(
            invoice_id=invoice_id,
            amount=amount,
            payment_method="bank_transfer",
            reference_number=inv["invoice_number"],
            notes="Demo partial payment",
            user_id=user_id,
        )
        if not payment_id:
            raise RuntimeError(payment_service.get_last_error() or "Failed partial payment")

    if target_status == "paid":
        inv = invoice_service.get_invoice(invoice_id, user_id=user_id)
        payment_id = payment_service.record_payment(
            invoice_id=invoice_id,
            amount=float(inv["total_amount"]),
            payment_method="bank_transfer",
            reference_number=inv["invoice_number"],
            notes="Demo full payment",
            user_id=user_id,
        )
        if not payment_id:
            raise RuntimeError(payment_service.get_last_error() or "Failed full payment")

    if target_status == "overdue":
        _set_invoice_due_date(invoice_id, datetime.now() - timedelta(days=14))
        invoice_service.update_overdue_statuses(user_id=user_id)

    return invoice_id


def _seed_user(
    auth: AuthService,
    profile_service: BusinessProfileService,
    customer_service: CustomerService,
    invoice_service: InvoiceService,
    payment_service: PaymentService,
    *,
    email: str,
    password: str,
    business_name: str,
    vat_number: str,
    suffix: str,
) -> dict:
    user = auth.get_user_by_email(email)
    if not user:
        user = auth.create_user(email=email, password=password, role="owner")
    if not user:
        raise RuntimeError(f"Failed to create/load user: {email}")
    user_id = int(user["id"])

    profile_service.upsert_profile(
        user_id=user_id,
        business_name=business_name,
        business_address=f"{suffix} Market Street, Cape Town",
        business_phone="+27 21 123 4567",
        business_email=email,
        vat_number=vat_number,
        banking_details=(
            "Bank: First National Bank\n"
            f"Account Holder: {business_name}\n"
            "Account Number: 6281 2345 6789\n"
            "Branch Code: 250655"
        ),
        smtp_server="smtp.gmail.com",
        smtp_port=587,
        smtp_username=email,
        smtp_password="",
        smtp_from_email=email,
        smtp_use_tls=True,
        smtp_use_ssl=False,
    )

    customers = [
        {
            "name": "Ferlando",
            "surname": "Young",
            "id_number": f"900101500000{suffix}",
            "company": "FY Entertainment",
            "email": f"accounts{suffix}@fyent.example",
            "phone": "0211234567",
            "address": f"{suffix} Waterfront Ave, Cape Town",
        },
        {
            "name": "Anele",
            "surname": "Mokoena",
            "id_number": f"920202500000{suffix}",
            "company": "Studio AM",
            "email": f"billing{suffix}@studioam.example",
            "phone": "0825557788",
            "address": f"{suffix} Long Street, Cape Town",
        },
    ]

    customer_ids: list[int] = []
    for c in customers:
        cid = customer_service.create_customer(
            name=c["name"],
            surname=c["surname"],
            id_number=c["id_number"],
            company=c["company"],
            email=c["email"],
            phone=c["phone"],
            address=c["address"],
            user_id=user_id,
        )
        if not cid:
            existing = customer_service.get_customer_by_id_number(c["id_number"], user_id=user_id)
            if not existing:
                raise RuntimeError(f"Failed to create customer {c['name']} for {email}")
            cid = int(existing["id"])
        customer_ids.append(int(cid))

    existing_invoices = invoice_service.get_all_invoices(limit=1, user_id=user_id)
    if not existing_invoices:
        _create_invoice_with_status(
            invoice_service,
            payment_service,
            user_id,
            customer_ids[0],
            "Brand shoot package",
            [("Photography Session", 1, 8500.0), ("Post Production", 1, 2500.0)],
            due_days=30,
            target_status="draft",
        )
        _create_invoice_with_status(
            invoice_service,
            payment_service,
            user_id,
            customer_ids[0],
            "Monthly retainer",
            [("Creative Retainer", 1, 6000.0)],
            due_days=10,
            target_status="sent",
        )
        _create_invoice_with_status(
            invoice_service,
            payment_service,
            user_id,
            customer_ids[1],
            "Campaign production",
            [("Video Production", 1, 18000.0)],
            due_days=5,
            target_status="partial",
        )
        _create_invoice_with_status(
            invoice_service,
            payment_service,
            user_id,
            customer_ids[1],
            "Website refresh",
            [("UI/UX Design", 1, 12000.0)],
            due_days=2,
            target_status="overdue",
        )
        _create_invoice_with_status(
            invoice_service,
            payment_service,
            user_id,
            customer_ids[0],
            "Consulting sprint",
            [("Strategy Workshop", 2, 4000.0)],
            due_days=15,
            target_status="paid",
        )

    return {"id": user_id, "email": email, "password": password}


def main() -> int:
    parser = argparse.ArgumentParser(description="Seed demo data for Vanta Pilot.")
    parser.add_argument(
        "--reset",
        action="store_true",
        help="Delete existing demo users/data first, then reseed.",
    )
    args = parser.parse_args()

    init_database(force=False)
    if args.reset:
        _reset_demo_data()

    auth = AuthService(str(DB_PATH), bootstrap_admin=True)
    profile_service = BusinessProfileService(str(DB_PATH))
    customer_service = CustomerService(str(DB_PATH))
    invoice_service = InvoiceService(str(DB_PATH))
    payment_service = PaymentService(str(DB_PATH))

    seeded = []
    seeded.append(
        _seed_user(
            auth,
            profile_service,
            customer_service,
            invoice_service,
            payment_service,
            email=DEMO_EMAILS[0],
            password="DemoPass123!",
            business_name="Demo Creative Studio",
            vat_number="4870212345",
            suffix="1",
        )
    )
    seeded.append(
        _seed_user(
            auth,
            profile_service,
            customer_service,
            invoice_service,
            payment_service,
            email=DEMO_EMAILS[1],
            password="DemoPass123!",
            business_name="Demo Growth Agency",
            vat_number="",
            suffix="2",
        )
    )

    print("\nDemo seed complete.")
    print("Use these accounts:")
    for u in seeded:
        print(f" - {u['email']} / {u['password']}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
