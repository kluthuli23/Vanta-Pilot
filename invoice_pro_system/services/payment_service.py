# services/payment_service.py - Complete Payment Tracking System
import sqlite3
from datetime import datetime, timedelta
from typing import List, Dict, Optional, Tuple
from decimal import Decimal

from database.safety import get_db_path
from services.audit_service import AuditService

class PaymentService:
    """Service for tracking payments on invoices."""
    ALLOWED_METHODS = {
        "cash",
        "credit_card",
        "bank_transfer",
        "cheque",
        "digital_wallet",
        "other",
    }
    PAYABLE_STATUSES = {"sent", "partial", "overdue"}
    
    def __init__(self, db_path=None):
        self.db_path = get_db_path(db_path)
        
        self.db_path.parent.mkdir(exist_ok=True)
        self.last_error: Optional[str] = None
        self.audit_service = AuditService(str(self.db_path))

    def _set_error(self, message: str):
        self.last_error = message
        print(f"❌ {message}")

    def get_last_error(self) -> Optional[str]:
        return self.last_error
    
    def _get_connection(self):
        """Get database connection with row factory."""
        conn = sqlite3.connect(self.db_path)
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA foreign_keys = ON")
        return conn
    
    def record_payment(self, invoice_id: int, amount: float, 
                      payment_method: str = 'bank_transfer',
                      reference_number: str = None,
                      notes: str = None,
                      user_id: Optional[int] = None) -> Optional[int]:
        """
        Record a payment against an invoice.
        
        Args:
            invoice_id: ID of the invoice being paid
            amount: Payment amount
            payment_method: cash/credit_card/bank_transfer/cheque/digital_wallet
            reference_number: Optional reference (EFT reference, cheque number, etc.)
            notes: Optional payment notes
        
        Returns:
            payment_id if successful, None if failed
        """
        self.last_error = None
        payment_method = (payment_method or "").strip().lower()
        if payment_method not in self.ALLOWED_METHODS:
            self._set_error(
                f"Invalid payment method. Must be one of: {', '.join(sorted(self.ALLOWED_METHODS))}"
            )
            return None

        if amount <= 0:
            self._set_error("Payment amount must be positive")
            return None

        conn = self._get_connection()
        cursor = conn.cursor()
        
        try:
            # Start transaction
            cursor.execute("BEGIN IMMEDIATE")
            
            # Get invoice details
            query = """
                SELECT id, invoice_number, total_amount, amount_paid, balance_due, status
                FROM invoices WHERE id = ?
            """
            params = [invoice_id]
            if user_id is not None:
                query += " AND owner_user_id = ?"
                params.append(int(user_id))
            cursor.execute(query, params)
            
            invoice = cursor.fetchone()
            if not invoice:
                self._set_error(f"Invoice {invoice_id} not found")
                return None

            if invoice["status"] == "cancelled":
                self._set_error("Cannot record payment for a cancelled invoice")
                return None

            if invoice["status"] == "paid":
                self._set_error("Invoice is already fully paid")
                return None

            if invoice["status"] == "draft":
                self._set_error("Cannot record payment while invoice is in draft status")
                return None
            
            # Calculate new paid amount and balance
            current_paid = invoice['amount_paid'] or 0
            new_paid = current_paid + amount
            total = invoice['total_amount']
            new_balance = total - new_paid
            
            if new_paid > total + 0.01:  # Small tolerance for floating point
                self._set_error(
                    f"Payment exceeds invoice total by R {new_paid - total:.2f}"
                )
                return None
            
            # Determine new status
            if abs(new_balance) < 0.01:  # Fully paid
                new_status = 'paid'
                paid_date = datetime.now()
            elif new_paid > 0:
                new_status = 'partial'
                paid_date = None
            else:
                new_status = invoice['status']
                paid_date = None
            
            # Insert payment record
            cursor.execute("""
                INSERT INTO payments 
                (invoice_id, amount, payment_method, reference_number, notes, payment_date)
                VALUES (?, ?, ?, ?, ?, ?)
            """, (invoice_id, amount, payment_method, reference_number, notes, datetime.now()))
            
            payment_id = cursor.lastrowid
            
            # Update invoice
            cursor.execute("""
                UPDATE invoices 
                SET amount_paid = ?, balance_due = ?, status = ?, 
                    paid_date = ?, updated_at = ?
                WHERE id = ?
            """, (new_paid, new_balance, new_status, paid_date, datetime.now(), invoice_id))
            
            conn.commit()
            self.audit_service.log_action(
                event_type="payment_recorded",
                entity_type="invoice",
                entity_id=invoice_id,
                source="service",
                details={
                    "payment_id": payment_id,
                    "amount": amount,
                    "method": payment_method,
                    "status_after": new_status,
                    "balance_due": new_balance,
                },
            )
            
            # Print summary
            print(f"\n✅ Payment recorded successfully!")
            print(f"   Payment ID: {payment_id}")
            print(f"   Invoice: {invoice['invoice_number']}")
            print(f"   Amount: R {amount:,.2f}")
            print(f"   Method: {payment_method}")
            print(f"   Status: {new_status.upper()}")
            print(f"   Paid to date: R {new_paid:,.2f} / R {total:,.2f}")
            print(f"   Balance due: R {new_balance:,.2f}")
            
            return payment_id
            
        except sqlite3.Error as e:
            conn.rollback()
            self._set_error(f"Database error: {e}")
            return None
        finally:
            conn.close()
    
    def get_payments_for_invoice(self, invoice_id: int, user_id: Optional[int] = None) -> List[Dict]:
        """Get all payments for an invoice."""
        conn = self._get_connection()
        cursor = conn.cursor()
        
        try:
            query = """
                SELECT p.*
                FROM payments p
                JOIN invoices i ON p.invoice_id = i.id
                WHERE p.invoice_id = ?
            """
            params = [invoice_id]
            if user_id is not None:
                query += " AND i.owner_user_id = ?"
                params.append(int(user_id))
            query += " ORDER BY p.payment_date DESC"
            cursor.execute(query, params)
            
            rows = cursor.fetchall()
            return [dict(row) for row in rows]
            
        except Exception as e:
            print(f"❌ Error fetching payments: {e}")
            return []
        finally:
            conn.close()
    
    def get_payment(self, payment_id: int, user_id: Optional[int] = None) -> Optional[Dict]:
        """Get payment details by ID."""
        conn = self._get_connection()
        cursor = conn.cursor()
        
        try:
            query = """
                SELECT p.*, i.invoice_number, i.customer_id,
                       c.name as customer_name, c.surname as customer_surname
                FROM payments p
                JOIN invoices i ON p.invoice_id = i.id
                JOIN customers c ON i.customer_id = c.id
                WHERE p.id = ?
            """
            params = [payment_id]
            if user_id is not None:
                query += " AND i.owner_user_id = ?"
                params.append(int(user_id))
            cursor.execute(query, params)
            
            row = cursor.fetchone()
            return dict(row) if row else None
            
        except Exception as e:
            print(f"❌ Error fetching payment: {e}")
            return None
        finally:
            conn.close()
    
    def get_outstanding_invoices(
        self, customer_id: Optional[int] = None, user_id: Optional[int] = None
    ) -> List[Dict]:
        """Get all invoices with outstanding balances."""
        from services.invoice_service import InvoiceService
        InvoiceService(str(self.db_path)).update_overdue_statuses(user_id=user_id)
        conn = self._get_connection()
        cursor = conn.cursor()
        
        try:
            query = """
                SELECT i.*, c.name as customer_name, c.surname as customer_surname,
                       c.company as customer_company
                FROM invoices i
                JOIN customers c ON i.customer_id = c.id
                WHERE i.balance_due > 0.01 
                  AND i.status IN ('sent', 'partial', 'overdue')
            """
            params = []
            
            if customer_id:
                query += " AND i.customer_id = ?"
                params.append(customer_id)
            if user_id is not None:
                query += " AND i.owner_user_id = ?"
                params.append(int(user_id))
            
            query += " ORDER BY i.due_date ASC"
            
            cursor.execute(query, params)
            rows = cursor.fetchall()
            
            return [dict(row) for row in rows]
            
        except Exception as e:
            print(f"❌ Error fetching outstanding invoices: {e}")
            return []
        finally:
            conn.close()
    
    def get_payment_summary(self, days: int = 30, user_id: Optional[int] = None) -> Dict:
        """Get payment summary for recent period."""
        from services.invoice_service import InvoiceService
        InvoiceService(str(self.db_path)).update_overdue_statuses(user_id=user_id)
        conn = self._get_connection()
        cursor = conn.cursor()
        
        try:
            cutoff_date = (datetime.now() - timedelta(days=days)).strftime('%Y-%m-%d')
            
            summary = {}
            
            # Total payments received
            query = """
                SELECT COALESCE(SUM(p.amount), 0)
                FROM payments p
                JOIN invoices i ON p.invoice_id = i.id
                WHERE date(p.payment_date) >= ?
            """
            params = [cutoff_date]
            if user_id is not None:
                query += " AND i.owner_user_id = ?"
                params.append(int(user_id))
            cursor.execute(query, params)
            summary['total_received'] = cursor.fetchone()[0]
            
            # Payments by method
            query = """
                SELECT p.payment_method, COUNT(*) as count, SUM(p.amount) as total
                FROM payments p
                JOIN invoices i ON p.invoice_id = i.id
                WHERE date(p.payment_date) >= ?
            """
            params = [cutoff_date]
            if user_id is not None:
                query += " AND i.owner_user_id = ?"
                params.append(int(user_id))
            query += """
                GROUP BY p.payment_method
                ORDER BY total DESC
            """
            cursor.execute(query, params)
            
            summary['by_method'] = []
            for row in cursor.fetchall():
                summary['by_method'].append({
                    'method': row[0],
                    'count': row[1],
                    'total': row[2]
                })
            
            # Daily payment totals
            query = """
                SELECT date(p.payment_date) as day, COUNT(*) as count, SUM(p.amount) as total
                FROM payments p
                JOIN invoices i ON p.invoice_id = i.id
                WHERE date(p.payment_date) >= ?
            """
            params = [cutoff_date]
            if user_id is not None:
                query += " AND i.owner_user_id = ?"
                params.append(int(user_id))
            query += """
                GROUP BY date(p.payment_date)
                ORDER BY day DESC
            """
            cursor.execute(query, params)
            
            summary['daily'] = []
            for row in cursor.fetchall():
                summary['daily'].append({
                    'date': row[0],
                    'count': row[1],
                    'total': row[2]
                })
            
            # Total outstanding
            if user_id is None:
                cursor.execute(
                    "SELECT COALESCE(SUM(balance_due), 0) FROM invoices WHERE balance_due > 0.01"
                )
            else:
                cursor.execute(
                    """
                    SELECT COALESCE(SUM(balance_due), 0)
                    FROM invoices
                    WHERE balance_due > 0.01
                      AND owner_user_id = ?
                    """,
                    (int(user_id),),
                )
            summary['total_outstanding'] = cursor.fetchone()[0]
            
            # Overdue total
            if user_id is None:
                cursor.execute(
                    """
                    SELECT COALESCE(SUM(balance_due), 0) FROM invoices
                    WHERE balance_due > 0.01 AND date(due_date) < date('now')
                    """
                )
            else:
                cursor.execute(
                    """
                    SELECT COALESCE(SUM(balance_due), 0) FROM invoices
                    WHERE balance_due > 0.01
                      AND date(due_date) < date('now')
                      AND owner_user_id = ?
                    """,
                    (int(user_id),),
                )
            summary['total_overdue'] = cursor.fetchone()[0]
            
            return summary
            
        except Exception as e:
            print(f"❌ Error generating payment summary: {e}")
            return {}
        finally:
            conn.close()
    
    def mark_invoice_as_paid(self, invoice_id: int, 
                            payment_method: str = 'bank_transfer',
                            reference: str = None,
                            user_id: Optional[int] = None) -> bool:
        """Mark an invoice as fully paid (convenience method)."""
        conn = self._get_connection()
        cursor = conn.cursor()
        
        try:
            # Get invoice total
            query = "SELECT total_amount FROM invoices WHERE id = ?"
            params = [invoice_id]
            if user_id is not None:
                query += " AND owner_user_id = ?"
                params.append(int(user_id))
            cursor.execute(query, params)
            row = cursor.fetchone()
            if not row:
                print(f"❌ Invoice {invoice_id} not found")
                return False
            
            total = row[0]
            
            # Record full payment
            payment_id = self.record_payment(
                invoice_id=invoice_id,
                amount=total,
                payment_method=payment_method,
                reference_number=reference,
                notes="Invoice paid in full",
                user_id=user_id,
            )
            
            return payment_id is not None
            
        finally:
            conn.close()

# For testing
if __name__ == "__main__":
    service = PaymentService()
    print("✅ PaymentService initialized")
    
    # Show summary
    summary = service.get_payment_summary(30)
    print(f"\n📊 Payment Summary (last 30 days):")
    print(f"   Received: R {summary.get('total_received', 0):,.2f}")
    print(f"   Outstanding: R {summary.get('total_outstanding', 0):,.2f}")
    print(f"   Overdue: R {summary.get('total_overdue', 0):,.2f}")
