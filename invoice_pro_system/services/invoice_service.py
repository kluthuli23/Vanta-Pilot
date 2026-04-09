# services/invoice_service.py - REAL DATABASE OPERATIONS
import sqlite3
import re
from datetime import datetime, timedelta
from typing import Dict, List, Optional, Tuple

from database.safety import ensure_schema_backup, get_db_path
from services.audit_service import AuditService


class InvoiceService:
    """Real database operations for invoice management."""

    VALID_STATUSES = ("draft", "sent", "paid", "overdue", "cancelled", "partial")
    STATUS_TRANSITIONS = {
        "draft": {"sent", "cancelled"},
        "sent": {"partial", "paid", "overdue", "cancelled"},
        "partial": {"paid", "overdue", "cancelled"},
        "overdue": {"partial", "paid", "cancelled"},
        "paid": set(),
        "cancelled": set(),
    }

    def __init__(self, db_path=None):
        self.db_path = get_db_path(db_path)

        self.db_path.parent.mkdir(exist_ok=True)
        self.vat_rate = 0.15  # South African VAT
        self.last_error: Optional[str] = None
        self.audit_service = AuditService(str(self.db_path))
        self._ensure_owner_column()
        self._ensure_sequence_table()

    def _set_error(self, message: str):
        self.last_error = message
        print(f"Error: {message}")

    def get_last_error(self) -> Optional[str]:
        return self.last_error

    def _get_connection(self):
        """Get database connection with row factory."""
        conn = sqlite3.connect(self.db_path)
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA foreign_keys = ON")
        return conn

    def _ensure_owner_column(self):
        """Ensure customer/invoice owner columns exist and are backfilled."""
        ensure_schema_backup(self.db_path, reason="invoices")
        conn = self._get_connection()
        cursor = conn.cursor()
        try:
            cursor.execute("PRAGMA table_info(customers)")
            customer_columns = {row["name"] for row in cursor.fetchall()}
            if "owner_user_id" not in customer_columns:
                cursor.execute("ALTER TABLE customers ADD COLUMN owner_user_id INTEGER")
                cursor.execute(
                    "CREATE INDEX IF NOT EXISTS idx_customers_owner_user_id ON customers(owner_user_id)"
                )
                user_row = None
                try:
                    cursor.execute("SELECT id FROM users ORDER BY id LIMIT 1")
                    user_row = cursor.fetchone()
                except sqlite3.Error:
                    user_row = None
                if user_row:
                    cursor.execute(
                        """
                        UPDATE customers
                        SET owner_user_id = ?
                        WHERE owner_user_id IS NULL
                        """,
                        (int(user_row["id"]),),
                    )
                customer_columns.add("owner_user_id")

            cursor.execute("PRAGMA table_info(invoices)")
            columns = {row["name"] for row in cursor.fetchall()}
            if "owner_user_id" not in columns:
                cursor.execute("ALTER TABLE invoices ADD COLUMN owner_user_id INTEGER")
                cursor.execute(
                    "CREATE INDEX IF NOT EXISTS idx_invoices_owner_user_id ON invoices(owner_user_id)"
                )

            if "owner_user_id" in customer_columns:
                cursor.execute(
                    """
                    UPDATE invoices
                    SET owner_user_id = (
                        SELECT c.owner_user_id
                        FROM customers c
                        WHERE c.id = invoices.customer_id
                    )
                    WHERE owner_user_id IS NULL
                    """
                )
            conn.commit()
        finally:
            conn.close()

    def _ensure_sequence_table(self):
        """Create sequence table used for atomic daily invoice numbering."""
        ensure_schema_backup(self.db_path, reason="invoices")
        conn = self._get_connection()
        cursor = conn.cursor()
        try:
            cursor.execute(
                """
                CREATE TABLE IF NOT EXISTS invoice_sequences (
                    invoice_date TEXT PRIMARY KEY,
                    last_seq INTEGER NOT NULL DEFAULT 0
                )
                """
            )
            conn.commit()
        finally:
            conn.close()

    def _tax_rate_for_user(self, user_id: Optional[int]) -> float:
        """Return VAT rate only when user has a valid VAT number configured."""
        if user_id is None:
            return self.vat_rate
        conn = self._get_connection()
        cursor = conn.cursor()
        try:
            cursor.execute("PRAGMA table_info(business_profiles)")
            cols = {row["name"] for row in cursor.fetchall()}
            if "vat_number" not in cols:
                return 0.0
            cursor.execute(
                """
                SELECT vat_number
                FROM business_profiles
                WHERE user_id = ?
                """,
                (int(user_id),),
            )
            row = cursor.fetchone()
            vat_number = (row["vat_number"] if row else "") or ""
            vat_digits = re.sub(r"\D", "", str(vat_number))
            # South African VAT numbers are typically 10 digits.
            return self.vat_rate if len(vat_digits) == 10 else 0.0
        except Exception:
            return 0.0
        finally:
            conn.close()

    def _generate_invoice_number(self, cursor: sqlite3.Cursor) -> str:
        """
        Generate the next invoice number for today.
        Must be called inside a write transaction.
        """
        today = datetime.now().strftime("%Y%m%d")
        like_pattern = f"INV-{today}-%"

        # Keep sequence in sync with existing records for today.
        cursor.execute(
            """
            SELECT COALESCE(MAX(CAST(SUBSTR(invoice_number, 14) AS INTEGER)), 0) AS max_seq
            FROM invoices
            WHERE invoice_number LIKE ?
            """,
            (like_pattern,),
        )
        max_existing = cursor.fetchone()["max_seq"]

        cursor.execute(
            """
            INSERT OR IGNORE INTO invoice_sequences (invoice_date, last_seq)
            VALUES (?, ?)
            """,
            (today, max_existing),
        )
        cursor.execute(
            """
            UPDATE invoice_sequences
            SET last_seq = ?
            WHERE invoice_date = ? AND last_seq < ?
            """,
            (max_existing, today, max_existing),
        )
        cursor.execute(
            """
            UPDATE invoice_sequences
            SET last_seq = last_seq + 1
            WHERE invoice_date = ?
            """,
            (today,),
        )
        cursor.execute(
            "SELECT last_seq FROM invoice_sequences WHERE invoice_date = ?",
            (today,),
        )
        seq = cursor.fetchone()["last_seq"]
        return f"INV-{today}-{seq:03d}"

    def create_invoice(
        self,
        customer_id: int,
        items: List[Tuple[str, int, float]],
        description: str = "",
        due_days: int = 30,
        user_id: Optional[int] = None,
    ) -> Optional[int]:
        """
        Create a new invoice with items in the database.

        Args:
            customer_id: ID of the customer
            items: List of (description, quantity, unit_price)
            description: Optional invoice description
            due_days: Days until payment is due

        Returns:
            invoice_id if successful, None if failed
        """
        self.last_error = None
        from services.customer_service import CustomerService

        customer_service = CustomerService(str(self.db_path))
        customer = customer_service.get_customer_by_id(
            customer_id,
            active_only=True,
            user_id=user_id,
        )

        if not customer:
            self._set_error(f"Customer ID {customer_id} not found or inactive")
            return None

        if not items:
            self._set_error("No invoice items provided")
            return None

        if due_days <= 0:
            self._set_error("Due days must be greater than 0")
            return None

        if due_days > 3650:
            self._set_error("Due days is too large")
            return None

        for desc, qty, price in items:
            if not str(desc or "").strip():
                self._set_error("Item description is required")
                return None
            if qty <= 0:
                self._set_error(f"Invalid quantity for '{desc}': must be positive")
                return None
            if price < 0:
                self._set_error(f"Invalid price for '{desc}': cannot be negative")
                return None

        conn = self._get_connection()
        cursor = conn.cursor()

        try:
            # Acquire a write lock to make number generation + insert atomic.
            cursor.execute("BEGIN IMMEDIATE")

            invoice_number = self._generate_invoice_number(cursor)

            applied_tax_rate = self._tax_rate_for_user(user_id)
            subtotal = sum(qty * price for _, qty, price in items)
            tax_amount = subtotal * applied_tax_rate
            total_amount = subtotal + tax_amount

            invoice_date = datetime.now()
            due_date = invoice_date + timedelta(days=due_days)

            cursor.execute(
                """
                INSERT INTO invoices
                (customer_id, invoice_number, description, status,
                 subtotal, tax_amount, total_amount, amount_paid, balance_due, currency,
                 due_date, invoice_date, created_at, updated_at, owner_user_id)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    customer_id,
                    invoice_number,
                    description[:200] if description else None,
                    "draft",
                    subtotal,
                    tax_amount,
                    total_amount,
                    0.0,
                    total_amount,
                    "ZAR",
                    due_date.isoformat(),
                    invoice_date.isoformat(),
                    invoice_date.isoformat(),
                    invoice_date.isoformat(),
                    int(user_id) if user_id is not None else customer.get("owner_user_id"),
                ),
            )

            invoice_id = cursor.lastrowid

            for desc, qty, price in items:
                line_subtotal = qty * price
                line_total = line_subtotal * (1 + applied_tax_rate)
                cursor.execute(
                    """
                    INSERT INTO invoice_items
                    (invoice_id, item_description, quantity, unit_price,
                     tax_rate, line_total, created_at)
                    VALUES (?, ?, ?, ?, ?, ?, ?)
                    """,
                    (
                        invoice_id,
                        desc[:255],
                        qty,
                        price,
                        applied_tax_rate,
                        line_total,
                        invoice_date.isoformat(),
                    ),
                )

            conn.commit()
            self.audit_service.log_action(
                event_type="invoice_created",
                entity_type="invoice",
                entity_id=invoice_id,
                source="service",
                details={
                    "invoice_number": invoice_number,
                    "customer_id": customer_id,
                    "status": "draft",
                    "total_amount": total_amount,
                },
            )

            print("Invoice created successfully!")
            print(f"   Invoice #: {invoice_number}")
            print(f"   Customer: {customer['name']} {customer['surname']}")
            print(f"   Amount: R {total_amount:,.2f}")
            print("   Status: draft")
            return invoice_id

        except sqlite3.IntegrityError as e:
            conn.rollback()
            self._set_error(f"Database integrity error: {e}")
            return None
        except Exception as e:
            conn.rollback()
            self._set_error(f"Failed to create invoice: {e}")
            return None
        finally:
            conn.close()

    def get_invoice(self, invoice_id: int, user_id: Optional[int] = None) -> Optional[Dict]:
        """Get complete invoice with items and customer details."""
        self.update_overdue_statuses(user_id=user_id)
        conn = self._get_connection()
        cursor = conn.cursor()

        try:
            if user_id is not None:
                cursor.execute(
                    """
                    SELECT
                        i.*,
                        c.name as customer_name,
                        c.surname as customer_surname,
                        c.company as customer_company,
                        c.id_number as customer_id_number,
                        c.email as customer_email,
                        c.phone as customer_phone,
                        c.address as customer_address
                    FROM invoices i
                    JOIN customers c ON i.customer_id = c.id
                    WHERE i.id = ?
                      AND i.owner_user_id = ?
                    """,
                    (invoice_id, int(user_id)),
                )
            else:
                cursor.execute(
                    """
                    SELECT
                        i.*,
                        c.name as customer_name,
                        c.surname as customer_surname,
                        c.company as customer_company,
                        c.id_number as customer_id_number,
                        c.email as customer_email,
                        c.phone as customer_phone,
                        c.address as customer_address
                    FROM invoices i
                    JOIN customers c ON i.customer_id = c.id
                    WHERE i.id = ?
                    """,
                    (invoice_id,),
                )

            invoice_row = cursor.fetchone()
            if not invoice_row:
                return None

            invoice = dict(invoice_row)

            cursor.execute(
                """
                SELECT * FROM invoice_items
                WHERE invoice_id = ?
                ORDER BY id
                """,
                (invoice_id,),
            )

            items = cursor.fetchall()
            invoice["items"] = [dict(item) for item in items]
            return invoice

        except Exception as e:
            print(f"Error fetching invoice: {e}")
            return None
        finally:
            conn.close()

    def get_invoice_by_number(
        self, invoice_number: str, user_id: Optional[int] = None
    ) -> Optional[Dict]:
        """Get invoice by invoice number."""
        conn = self._get_connection()
        cursor = conn.cursor()

        try:
            if user_id is None:
                cursor.execute(
                    "SELECT id FROM invoices WHERE invoice_number = ?",
                    (invoice_number,),
                )
            else:
                cursor.execute(
                    "SELECT id FROM invoices WHERE invoice_number = ? AND owner_user_id = ?",
                    (invoice_number, int(user_id)),
                )
            row = cursor.fetchone()
            if row:
                return self.get_invoice(row["id"], user_id=user_id)
            return None
        finally:
            conn.close()

    def get_customer_invoices(
        self, customer_id: int, user_id: Optional[int] = None
    ) -> List[Dict]:
        """Get all invoices for a customer."""
        self.update_overdue_statuses(user_id=user_id)
        conn = self._get_connection()
        cursor = conn.cursor()

        try:
            query = """
                SELECT id, invoice_number, total_amount, status,
                       invoice_date, due_date, amount_paid, balance_due
                FROM invoices
                WHERE customer_id = ?
            """
            params = [customer_id]
            if user_id is not None:
                query += " AND owner_user_id = ?"
                params.append(int(user_id))
            query += " ORDER BY invoice_date DESC"
            cursor.execute(query, params)
            rows = cursor.fetchall()
            return [dict(row) for row in rows]
        except Exception as e:
            print(f"Error fetching invoices: {e}")
            return []
        finally:
            conn.close()

    def get_all_invoices(
        self, limit: int = 100, offset: int = 0, user_id: Optional[int] = None
    ) -> List[Dict]:
        """Get all invoices with pagination."""
        self.update_overdue_statuses(user_id=user_id)
        conn = self._get_connection()
        cursor = conn.cursor()

        try:
            query = """
                SELECT
                    i.id, i.invoice_number, i.total_amount, i.status,
                    i.invoice_date, i.due_date, i.amount_paid, i.balance_due,
                    c.name, c.surname, c.company
                FROM invoices i
                JOIN customers c ON i.customer_id = c.id
            """
            params: List[object] = []
            if user_id is not None:
                query += " WHERE i.owner_user_id = ?"
                params.append(int(user_id))
            query += " ORDER BY i.invoice_date DESC LIMIT ? OFFSET ?"
            params.extend([limit, offset])
            cursor.execute(query, params)
            rows = cursor.fetchall()
            return [dict(row) for row in rows]
        except Exception as e:
            print(f"Error fetching invoices: {e}")
            return []
        finally:
            conn.close()

    def update_invoice_status(
        self, invoice_id: int, status: str, user_id: Optional[int] = None
    ) -> bool:
        """Update invoice status."""
        self.last_error = None
        status = (status or "").strip().lower()
        if status not in self.VALID_STATUSES:
            self._set_error(
                f"Invalid status. Must be one of: {', '.join(self.VALID_STATUSES)}"
            )
            return False

        conn = self._get_connection()
        cursor = conn.cursor()

        try:
            query = """
                SELECT id, status, total_amount, amount_paid, balance_due
                FROM invoices
                WHERE id = ?
            """
            params = [invoice_id]
            if user_id is not None:
                query += " AND owner_user_id = ?"
                params.append(int(user_id))
            cursor.execute(query, params)
            invoice = cursor.fetchone()
            if not invoice:
                self._set_error(f"Invoice {invoice_id} not found")
                return False

            current_status = invoice["status"]
            if status == current_status:
                return True

            allowed = self.STATUS_TRANSITIONS.get(current_status, set())
            if status not in allowed:
                self._set_error(
                    f"Invalid transition: {current_status} -> {status}"
                )
                return False

            amount_paid = float(invoice["amount_paid"] or 0)
            balance_due = float(invoice["balance_due"] or 0)

            if status == "paid" and balance_due > 0.01:
                self._set_error(
                    "Cannot mark invoice as paid while balance is still due"
                )
                return False

            if status == "partial" and (amount_paid <= 0 or balance_due <= 0.01):
                self._set_error(
                    "Partial status requires some payment and a remaining balance"
                )
                return False

            update_data = {"status": status, "updated_at": datetime.now().isoformat()}
            if status == "paid":
                update_data["paid_date"] = datetime.now().isoformat()
            elif status in {"draft", "sent", "partial", "overdue", "cancelled"}:
                update_data["paid_date"] = None

            set_clause = ", ".join([f"{k} = ?" for k in update_data.keys()])
            values = list(update_data.values())
            values.append(invoice_id)
            where_clause = "WHERE id = ?"
            if user_id is not None:
                where_clause += " AND owner_user_id = ?"
                values.append(int(user_id))

            cursor.execute(
                f"""
                UPDATE invoices
                SET {set_clause}
                {where_clause}
                """,
                values,
            )
            conn.commit()
            success = cursor.rowcount > 0
            if success:
                print(f"Invoice {invoice_id} status updated to: {status}")
                self.audit_service.log_action(
                    event_type="invoice_status_updated",
                    entity_type="invoice",
                    entity_id=invoice_id,
                    source="service",
                    details={
                        "from_status": current_status,
                        "to_status": status,
                    },
                )
            else:
                self._set_error(f"No changes applied to invoice {invoice_id}")
            return success
        except Exception as e:
            self._set_error(f"Error updating invoice status: {e}")
            return False
        finally:
            conn.close()

    def get_invoice_summary(self, user_id: Optional[int] = None) -> Dict:
        """Get summary statistics for invoices."""
        self.update_overdue_statuses(user_id=user_id)
        conn = self._get_connection()
        cursor = conn.cursor()

        try:
            summary = {}

            if user_id is None:
                cursor.execute("SELECT COUNT(*) FROM invoices")
            else:
                cursor.execute(
                    "SELECT COUNT(*) FROM invoices WHERE owner_user_id = ?",
                    (int(user_id),),
                )
            summary["total_invoices"] = cursor.fetchone()[0]

            query = """
                SELECT COALESCE(SUM(total_amount), 0)
                FROM invoices
                WHERE status = 'paid'
            """
            params = []
            if user_id is not None:
                query += " AND owner_user_id = ?"
                params.append(int(user_id))
            cursor.execute(query, params)
            summary["total_revenue"] = cursor.fetchone()[0]

            query = """
                SELECT COALESCE(SUM(total_amount), 0)
                FROM invoices
                WHERE status IN ('draft', 'sent', 'overdue', 'partial')
            """
            params = []
            if user_id is not None:
                query += " AND owner_user_id = ?"
                params.append(int(user_id))
            cursor.execute(query, params)
            summary["outstanding"] = cursor.fetchone()[0]

            query = """
                SELECT COUNT(*) FROM invoices
                WHERE (
                    status = 'overdue'
                    OR (status IN ('sent', 'draft', 'partial')
                        AND date(due_date) < date('now'))
                )
            """
            params = []
            if user_id is not None:
                query += " AND owner_user_id = ?"
                params.append(int(user_id))
            cursor.execute(query, params)
            summary["overdue_count"] = cursor.fetchone()[0]

            return summary
        except Exception as e:
            print(f"Error getting summary: {e}")
            return {}
        finally:
            conn.close()

    def update_overdue_statuses(self, user_id: Optional[int] = None) -> int:
        """Automatically mark eligible invoices as overdue."""
        conn = self._get_connection()
        cursor = conn.cursor()
        try:
            now = datetime.now().isoformat()
            query = """
                UPDATE invoices
                SET status = 'overdue',
                    updated_at = ?
                WHERE status IN ('sent', 'partial')
                  AND COALESCE(balance_due, 0) > 0.01
                  AND due_date IS NOT NULL
                  AND date(due_date) < date('now')
            """
            params = [now]
            if user_id is not None:
                query += " AND owner_user_id = ?"
                params.append(int(user_id))
            cursor.execute(query, params)
            changed = cursor.rowcount
            conn.commit()
            if changed > 0:
                self.audit_service.log_action(
                    event_type="overdue_auto_updated",
                    entity_type="invoice_batch",
                    entity_id=None,
                    source="service",
                    details={"count": changed},
                )
            return changed
        except Exception:
            conn.rollback()
            return 0
        finally:
            conn.close()

    def update_draft_invoice(
        self,
        invoice_id: int,
        items: List[Tuple[str, int, float]],
        description: str = "",
        due_date: Optional[str] = None,
        user_id: Optional[int] = None,
    ) -> bool:
        """Update invoice content for draft invoices only."""
        self.last_error = None
        if not items:
            self._set_error("At least one item is required")
            return False
        for desc, qty, price in items:
            if not str(desc or "").strip():
                self._set_error("Item description is required")
                return False
            if qty <= 0:
                self._set_error("Item quantity must be positive")
                return False
            if price < 0:
                self._set_error("Item price cannot be negative")
                return False

        conn = self._get_connection()
        cursor = conn.cursor()
        try:
            cursor.execute("BEGIN IMMEDIATE")
            query = """
                SELECT id, status
                FROM invoices
                WHERE id = ?
            """
            params: List[object] = [invoice_id]
            if user_id is not None:
                query += " AND owner_user_id = ?"
                params.append(int(user_id))
            cursor.execute(query, params)
            row = cursor.fetchone()
            if not row:
                self._set_error(f"Invoice {invoice_id} not found")
                conn.rollback()
                return False
            if row["status"] != "draft":
                self._set_error("Only draft invoices can be edited")
                conn.rollback()
                return False

            owner_id = int(user_id) if user_id is not None else None
            if owner_id is None:
                cursor.execute("SELECT owner_user_id FROM invoices WHERE id = ?", (invoice_id,))
                owner_row = cursor.fetchone()
                owner_id = int(owner_row["owner_user_id"]) if owner_row and owner_row["owner_user_id"] is not None else None

            applied_tax_rate = self._tax_rate_for_user(owner_id)
            subtotal = sum(qty * price for _, qty, price in items)
            tax_amount = subtotal * applied_tax_rate
            total_amount = subtotal + tax_amount
            now_iso = datetime.now().isoformat()
            if due_date:
                try:
                    parsed_due = datetime.fromisoformat(str(due_date))
                    due_date_value = parsed_due.isoformat()
                except ValueError:
                    self._set_error("Invalid due date format")
                    conn.rollback()
                    return False
            else:
                cursor.execute("SELECT due_date FROM invoices WHERE id = ?", (invoice_id,))
                due_row = cursor.fetchone()
                due_date_value = due_row["due_date"] if due_row else None

            cursor.execute(
                """
                UPDATE invoices
                SET description = ?,
                    subtotal = ?,
                    tax_amount = ?,
                    total_amount = ?,
                    balance_due = ?,
                    updated_at = ?,
                    due_date = ?
                WHERE id = ?
                """,
                (
                    description[:200] if description else None,
                    subtotal,
                    tax_amount,
                    total_amount,
                    total_amount,
                    now_iso,
                    due_date_value,
                    invoice_id,
                ),
            )

            cursor.execute("DELETE FROM invoice_items WHERE invoice_id = ?", (invoice_id,))
            for desc, qty, price in items:
                line_subtotal = qty * price
                line_total = line_subtotal * (1 + applied_tax_rate)
                cursor.execute(
                    """
                    INSERT INTO invoice_items
                    (invoice_id, item_description, quantity, unit_price, tax_rate, line_total, created_at)
                    VALUES (?, ?, ?, ?, ?, ?, ?)
                    """,
                    (
                        invoice_id,
                        desc[:255],
                        qty,
                        price,
                        applied_tax_rate,
                        line_total,
                        now_iso,
                    ),
                )
            conn.commit()
            self.audit_service.log_action(
                event_type="invoice_updated",
                entity_type="invoice",
                entity_id=invoice_id,
                source="service",
                details={"status": "draft"},
            )
            return True
        except Exception as e:
            conn.rollback()
            self._set_error(f"Failed to update draft invoice: {e}")
            return False
        finally:
            conn.close()

    def delete_draft_invoice(self, invoice_id: int, user_id: Optional[int] = None) -> bool:
        """Delete invoice only if it is still draft."""
        self.last_error = None
        conn = self._get_connection()
        cursor = conn.cursor()
        try:
            cursor.execute("BEGIN IMMEDIATE")
            query = "SELECT id, status FROM invoices WHERE id = ?"
            params: List[object] = [invoice_id]
            if user_id is not None:
                query += " AND owner_user_id = ?"
                params.append(int(user_id))
            cursor.execute(query, params)
            row = cursor.fetchone()
            if not row:
                self._set_error(f"Invoice {invoice_id} not found")
                conn.rollback()
                return False
            if row["status"] != "draft":
                self._set_error("Only draft invoices can be deleted")
                conn.rollback()
                return False

            cursor.execute("DELETE FROM invoice_items WHERE invoice_id = ?", (invoice_id,))
            cursor.execute("DELETE FROM invoices WHERE id = ?", (invoice_id,))
            conn.commit()
            self.audit_service.log_action(
                event_type="invoice_deleted",
                entity_type="invoice",
                entity_id=invoice_id,
                source="service",
                details={"status": "draft"},
            )
            return True
        except Exception as e:
            conn.rollback()
            self._set_error(f"Failed to delete draft invoice: {e}")
            return False
        finally:
            conn.close()


if __name__ == "__main__":
    service = InvoiceService()
    print("InvoiceService initialized")
    print(f"   Database: {service.db_path}")

    conn = service._get_connection()
    cursor = conn.cursor()
    cursor.execute("SELECT COUNT(*) FROM invoices")
    count = cursor.fetchone()[0]
    conn.close()
    print(f"   Invoices in database: {count}")

    summary = service.get_invoice_summary()
    if summary:
        print("\nInvoice Summary:")
        print(f"   Total Invoices: {summary.get('total_invoices', 0)}")
        print(f"   Total Revenue: R {summary.get('total_revenue', 0):,.2f}")
        print(f"   Outstanding: R {summary.get('outstanding', 0):,.2f}")
        print(f"   Overdue: {summary.get('overdue_count', 0)}")
