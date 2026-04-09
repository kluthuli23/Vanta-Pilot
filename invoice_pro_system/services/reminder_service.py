import sqlite3
from datetime import datetime
from typing import Dict, List, Optional

from database.safety import ensure_schema_backup, get_db_path
from services.audit_service import AuditService
from services.business_profile_service import BusinessProfileService
from services.email_service import EmailService
from services.invoice_service import InvoiceService
from services.oauth_service import OAuthService
from services.pdf_service import PDFInvoiceService


class ReminderService:
    """Automatic overdue reminder management."""

    def __init__(self, db_path=None):
        self.db_path = get_db_path(db_path)
        self.db_path.parent.mkdir(exist_ok=True)
        self.audit_service = AuditService(str(self.db_path))
        self._ensure_tables()

    def _get_connection(self):
        conn = sqlite3.connect(self.db_path)
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA foreign_keys = ON")
        return conn

    def _ensure_tables(self):
        ensure_schema_backup(self.db_path, reason="reminders")
        conn = self._get_connection()
        cursor = conn.cursor()
        try:
            cursor.execute(
                """
                CREATE TABLE IF NOT EXISTS reminder_settings (
                    id INTEGER PRIMARY KEY CHECK (id = 1),
                    enabled INTEGER NOT NULL DEFAULT 1,
                    interval_days INTEGER NOT NULL DEFAULT 7,
                    start_after_days_overdue INTEGER NOT NULL DEFAULT 0,
                    max_reminders INTEGER NOT NULL DEFAULT 12,
                    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
                )
                """
            )
            cursor.execute(
                """
                INSERT OR IGNORE INTO reminder_settings
                (id, enabled, interval_days, start_after_days_overdue, max_reminders, updated_at)
                VALUES (1, 1, 7, 0, 12, ?)
                """,
                (datetime.now().isoformat(),),
            )
            cursor.execute(
                """
                CREATE TABLE IF NOT EXISTS customer_reminder_settings (
                    customer_id INTEGER PRIMARY KEY,
                    enabled INTEGER,
                    interval_days INTEGER,
                    start_after_days_overdue INTEGER,
                    max_reminders INTEGER,
                    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                    FOREIGN KEY (customer_id) REFERENCES customers(id) ON DELETE CASCADE
                )
                """
            )
            cursor.execute(
                """
                CREATE TABLE IF NOT EXISTS reminder_events (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    invoice_id INTEGER NOT NULL,
                    customer_id INTEGER NOT NULL,
                    recipient_email TEXT,
                    sent_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                    status TEXT NOT NULL,
                    error_message TEXT,
                    days_overdue INTEGER,
                    next_due_at TIMESTAMP,
                    FOREIGN KEY (invoice_id) REFERENCES invoices(id) ON DELETE RESTRICT,
                    FOREIGN KEY (customer_id) REFERENCES customers(id) ON DELETE RESTRICT
                )
                """
            )
            cursor.execute(
                "CREATE INDEX IF NOT EXISTS idx_reminder_events_invoice ON reminder_events(invoice_id, sent_at)"
            )
            conn.commit()
        finally:
            conn.close()

    def get_global_settings(self) -> Dict:
        conn = self._get_connection()
        cursor = conn.cursor()
        try:
            cursor.execute("SELECT * FROM reminder_settings WHERE id = 1")
            row = cursor.fetchone()
            return dict(row) if row else {}
        finally:
            conn.close()

    def update_global_settings(
        self,
        enabled: bool,
        interval_days: int,
        start_after_days_overdue: int,
        max_reminders: int,
    ) -> bool:
        interval_days = max(1, int(interval_days))
        start_after_days_overdue = max(0, int(start_after_days_overdue))
        max_reminders = max(1, int(max_reminders))
        conn = self._get_connection()
        cursor = conn.cursor()
        try:
            cursor.execute(
                """
                UPDATE reminder_settings
                SET enabled = ?, interval_days = ?, start_after_days_overdue = ?,
                    max_reminders = ?, updated_at = ?
                WHERE id = 1
                """,
                (
                    1 if enabled else 0,
                    interval_days,
                    start_after_days_overdue,
                    max_reminders,
                    datetime.now().isoformat(),
                ),
            )
            conn.commit()
            self.audit_service.log_action(
                event_type="reminder_settings_updated",
                entity_type="system",
                source="web",
                details={
                    "enabled": enabled,
                    "interval_days": interval_days,
                    "start_after_days_overdue": start_after_days_overdue,
                    "max_reminders": max_reminders,
                },
            )
            return True
        except Exception:
            conn.rollback()
            return False
        finally:
            conn.close()

    def get_customer_override(self, customer_id: int) -> Optional[Dict]:
        conn = self._get_connection()
        cursor = conn.cursor()
        try:
            cursor.execute(
                "SELECT * FROM customer_reminder_settings WHERE customer_id = ?",
                (customer_id,),
            )
            row = cursor.fetchone()
            return dict(row) if row else None
        finally:
            conn.close()

    def set_customer_override(
        self,
        customer_id: int,
        enabled: Optional[bool],
        interval_days: Optional[int],
        start_after_days_overdue: Optional[int],
        max_reminders: Optional[int],
    ) -> bool:
        conn = self._get_connection()
        cursor = conn.cursor()
        try:
            cursor.execute(
                """
                INSERT INTO customer_reminder_settings
                (customer_id, enabled, interval_days, start_after_days_overdue, max_reminders, updated_at)
                VALUES (?, ?, ?, ?, ?, ?)
                ON CONFLICT(customer_id) DO UPDATE SET
                    enabled = excluded.enabled,
                    interval_days = excluded.interval_days,
                    start_after_days_overdue = excluded.start_after_days_overdue,
                    max_reminders = excluded.max_reminders,
                    updated_at = excluded.updated_at
                """,
                (
                    customer_id,
                    None if enabled is None else (1 if enabled else 0),
                    None if interval_days is None else max(1, int(interval_days)),
                    None
                    if start_after_days_overdue is None
                    else max(0, int(start_after_days_overdue)),
                    None if max_reminders is None else max(1, int(max_reminders)),
                    datetime.now().isoformat(),
                ),
            )
            conn.commit()
            self.audit_service.log_action(
                event_type="customer_reminder_override_updated",
                entity_type="customer",
                entity_id=customer_id,
                source="web",
            )
            return True
        except Exception:
            conn.rollback()
            return False
        finally:
            conn.close()

    def clear_customer_override(self, customer_id: int) -> bool:
        conn = self._get_connection()
        cursor = conn.cursor()
        try:
            cursor.execute(
                "DELETE FROM customer_reminder_settings WHERE customer_id = ?",
                (customer_id,),
            )
            conn.commit()
            self.audit_service.log_action(
                event_type="customer_reminder_override_cleared",
                entity_type="customer",
                entity_id=customer_id,
                source="web",
            )
            return True
        except Exception:
            conn.rollback()
            return False
        finally:
            conn.close()

    def get_customer_reminder_overview(self, customer_ids: List[int]) -> Dict[int, Dict]:
        """Return last/next reminder timestamps per customer."""
        if not customer_ids:
            return {}
        conn = self._get_connection()
        cursor = conn.cursor()
        try:
            placeholders = ",".join("?" for _ in customer_ids)
            cursor.execute(
                f"""
                SELECT
                    customer_id,
                    MAX(CASE WHEN status = 'sent' THEN sent_at END) AS last_sent_at,
                    MIN(
                        CASE
                            WHEN status = 'sent'
                             AND next_due_at IS NOT NULL
                             AND date(next_due_at) >= date('now')
                            THEN next_due_at
                        END
                    ) AS next_due_at
                FROM reminder_events
                WHERE customer_id IN ({placeholders})
                GROUP BY customer_id
                """,
                customer_ids,
            )
            results = {}
            for row in cursor.fetchall():
                results[int(row["customer_id"])] = {
                    "last_sent_at": row["last_sent_at"],
                    "next_due_at": row["next_due_at"],
                }
            return results
        finally:
            conn.close()

    def _get_due_reminders(self, limit: int = 100) -> List[Dict]:
        conn = self._get_connection()
        cursor = conn.cursor()
        try:
            cursor.execute(
                """
                SELECT
                    i.id AS invoice_id,
                    i.customer_id,
                    i.invoice_number,
                    i.due_date,
                    i.total_amount,
                    COALESCE(i.balance_due, i.total_amount) AS balance_due,
                    c.name AS customer_name,
                    c.surname AS customer_surname,
                    c.email AS customer_email,
                    COALESCE(crs.enabled, rs.enabled) AS cfg_enabled,
                    COALESCE(crs.interval_days, rs.interval_days) AS cfg_interval_days,
                    COALESCE(crs.start_after_days_overdue, rs.start_after_days_overdue) AS cfg_start_after_days,
                    COALESCE(crs.max_reminders, rs.max_reminders) AS cfg_max_reminders,
                    re.last_sent,
                    COALESCE(re.sent_count, 0) AS sent_count
                FROM invoices i
                JOIN customers c ON c.id = i.customer_id
                JOIN reminder_settings rs ON rs.id = 1
                LEFT JOIN customer_reminder_settings crs ON crs.customer_id = i.customer_id
                LEFT JOIN (
                    SELECT
                        invoice_id,
                        MAX(sent_at) AS last_sent,
                        COUNT(*) AS sent_count
                    FROM reminder_events
                    WHERE status = 'sent'
                    GROUP BY invoice_id
                ) re ON re.invoice_id = i.id
                WHERE i.status IN ('sent', 'partial', 'overdue')
                  AND COALESCE(i.balance_due, 0) > 0.01
                  AND c.is_active = 1
                  AND c.email IS NOT NULL
                  AND TRIM(c.email) <> ''
                  AND COALESCE(crs.enabled, rs.enabled) = 1
                  AND date(i.due_date, '+' || COALESCE(crs.start_after_days_overdue, rs.start_after_days_overdue) || ' day') <= date('now')
                  AND (
                        re.last_sent IS NULL
                        OR date(re.last_sent, '+' || COALESCE(crs.interval_days, rs.interval_days) || ' day') <= date('now')
                  )
                  AND COALESCE(re.sent_count, 0) < COALESCE(crs.max_reminders, rs.max_reminders)
                ORDER BY date(i.due_date) ASC
                LIMIT ?
                """,
                (limit,),
            )
            return [dict(row) for row in cursor.fetchall()]
        finally:
            conn.close()

    def _record_event(
        self,
        invoice_id: int,
        customer_id: int,
        recipient_email: str,
        status: str,
        days_overdue: int,
        next_due_at: Optional[str],
        error_message: Optional[str] = None,
    ):
        conn = self._get_connection()
        cursor = conn.cursor()
        try:
            cursor.execute(
                """
                INSERT INTO reminder_events
                (invoice_id, customer_id, recipient_email, sent_at, status, error_message, days_overdue, next_due_at)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    invoice_id,
                    customer_id,
                    recipient_email,
                    datetime.now().isoformat(),
                    status,
                    error_message,
                    days_overdue,
                    next_due_at,
                ),
            )
            conn.commit()
        finally:
            conn.close()

    def _has_delivery_channel(self, owner_user_id: Optional[int], business_profile: Optional[Dict]) -> bool:
        """Return True when reminders can actually be delivered for this tenant."""
        if owner_user_id is None:
            return False
        # Preferred: Gmail OAuth connection.
        if OAuthService(str(self.db_path)).is_google_connected(int(owner_user_id)):
            return True
        # Fallback: explicitly configured SMTP creds on profile.
        profile = business_profile or {}
        return bool(
            str(profile.get("smtp_server") or "").strip()
            and str(profile.get("smtp_port") or "").strip()
            and str(profile.get("smtp_username") or "").strip()
            and str(profile.get("smtp_password") or "").strip()
        )

    def process_due_reminders(self, limit: int = 100) -> Dict[str, int]:
        """Send due reminders according to configured intervals."""
        InvoiceService(str(self.db_path)).update_overdue_statuses()
        due = self._get_due_reminders(limit=limit)
        sent = 0
        failed = 0
        skipped = 0
        email_service = EmailService()
        pdf_service = PDFInvoiceService()
        invoice_service = InvoiceService(str(self.db_path))
        profile_service = BusinessProfileService(str(self.db_path))

        for row in due:
            try:
                invoice = invoice_service.get_invoice(row["invoice_id"])
                if not invoice:
                    failed += 1
                    continue
                owner_user_id = invoice.get("owner_user_id")
                business_profile = (
                    profile_service.get_profile(int(owner_user_id))
                    if owner_user_id is not None
                    else None
                )
                if not self._has_delivery_channel(owner_user_id, business_profile):
                    skipped += 1
                    self._record_event(
                        invoice_id=row["invoice_id"],
                        customer_id=row["customer_id"],
                        recipient_email=row["customer_email"],
                        status="skipped",
                        days_overdue=0,
                        next_due_at=None,
                        error_message="No email delivery channel configured for tenant.",
                    )
                    continue

                due_date = datetime.fromisoformat(str(row["due_date"]))
                days_overdue = max((datetime.now().date() - due_date.date()).days, 0)
                interval_days = int(row["cfg_interval_days"])
                next_due_at = datetime.now().date().fromordinal(
                    datetime.now().date().toordinal() + interval_days
                ).isoformat()

                pdf_path = pdf_service.generate_invoice_from_db(
                    invoice,
                    business_profile=business_profile,
                )
                to_name = f"{row.get('customer_name', '')} {row.get('customer_surname', '')}".strip()

                ok = email_service.send_payment_reminder(
                    to_email=row["customer_email"],
                    to_name=to_name or "Customer",
                    invoice_number=row["invoice_number"],
                    due_date=str(row["due_date"])[:10],
                    balance_due=float(row["balance_due"] or 0),
                    days_overdue=days_overdue,
                    pdf_path=Path(pdf_path) if pdf_path else None,
                    business_profile=business_profile,
                )

                if ok:
                    sent += 1
                    self._record_event(
                        invoice_id=row["invoice_id"],
                        customer_id=row["customer_id"],
                        recipient_email=row["customer_email"],
                        status="sent",
                        days_overdue=days_overdue,
                        next_due_at=next_due_at,
                    )
                    self.audit_service.log_action(
                        event_type="reminder_sent",
                        entity_type="invoice",
                        entity_id=row["invoice_id"],
                        source="scheduler",
                        details={
                            "invoice_number": row["invoice_number"],
                            "recipient": row["customer_email"],
                            "days_overdue": days_overdue,
                        },
                    )
                else:
                    failed += 1
                    self._record_event(
                        invoice_id=row["invoice_id"],
                        customer_id=row["customer_id"],
                        recipient_email=row["customer_email"],
                        status="failed",
                        days_overdue=days_overdue,
                        next_due_at=None,
                        error_message="SMTP send failed",
                    )
                    self.audit_service.log_action(
                        event_type="reminder_failed",
                        entity_type="invoice",
                        entity_id=row["invoice_id"],
                        source="scheduler",
                        details={"invoice_number": row["invoice_number"]},
                    )
            except Exception as exc:
                failed += 1
                self._record_event(
                    invoice_id=row["invoice_id"],
                    customer_id=row["customer_id"],
                    recipient_email=row.get("customer_email", ""),
                    status="failed",
                    days_overdue=0,
                    next_due_at=None,
                    error_message=str(exc),
                )

        return {"scanned": len(due), "sent": sent, "failed": failed, "skipped": skipped}
