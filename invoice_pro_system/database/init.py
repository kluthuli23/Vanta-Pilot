# database/init.py - ADD PAYMENTS TABLE
import sqlite3
from pathlib import Path
import sys

def init_database(force=False):
    """Initialize database with complete schema including payments."""
    
    data_dir = Path(__file__).parent.parent / "data"
    data_dir.mkdir(exist_ok=True)
    
    db_path = data_dir / "business.db"
    
    # Backup if force=True
    if force and db_path.exists():
        backup_path = data_dir / f"business_backup_{Path(db_path).stat().st_mtime}.db"
        import shutil
        shutil.copy2(db_path, backup_path)
        print(f"✅ Database backed up to: {backup_path}")
    
    print(f"🔧 Initializing database: {db_path}")
    
    conn = sqlite3.connect(db_path)
    cursor = conn.cursor()
    
    # Enable foreign keys
    cursor.execute("PRAGMA foreign_keys = ON")
    
    # Existing tables (keep as is)
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS customers (
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
            updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            FOREIGN KEY (owner_user_id) REFERENCES users(id) ON DELETE SET NULL
        )
    """)

    cursor.execute("""
        CREATE TABLE IF NOT EXISTS users (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            email TEXT UNIQUE NOT NULL,
            password_hash TEXT NOT NULL,
            role TEXT NOT NULL DEFAULT 'admin',
            is_active BOOLEAN DEFAULT 1,
            trial_starts_at TEXT,
            trial_ends_at TEXT,
            subscription_status TEXT DEFAULT 'trialing',
            subscription_started_at TEXT,
            subscription_ends_at TEXT,
            billing_provider TEXT,
            billing_customer_id TEXT,
            billing_subscription_id TEXT,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )
    """)
    cursor.execute("PRAGMA table_info(users)")
    _user_cols = {row[1] for row in cursor.fetchall()}
    if "trial_starts_at" not in _user_cols:
        cursor.execute("ALTER TABLE users ADD COLUMN trial_starts_at TEXT")
    if "trial_ends_at" not in _user_cols:
        cursor.execute("ALTER TABLE users ADD COLUMN trial_ends_at TEXT")
    if "subscription_status" not in _user_cols:
        cursor.execute("ALTER TABLE users ADD COLUMN subscription_status TEXT DEFAULT 'trialing'")
    if "subscription_started_at" not in _user_cols:
        cursor.execute("ALTER TABLE users ADD COLUMN subscription_started_at TEXT")
    if "subscription_ends_at" not in _user_cols:
        cursor.execute("ALTER TABLE users ADD COLUMN subscription_ends_at TEXT")
    if "billing_provider" not in _user_cols:
        cursor.execute("ALTER TABLE users ADD COLUMN billing_provider TEXT")
    if "billing_customer_id" not in _user_cols:
        cursor.execute("ALTER TABLE users ADD COLUMN billing_customer_id TEXT")
    if "billing_subscription_id" not in _user_cols:
        cursor.execute("ALTER TABLE users ADD COLUMN billing_subscription_id TEXT")

    cursor.execute("""
        CREATE TABLE IF NOT EXISTS business_profiles (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id INTEGER UNIQUE NOT NULL,
            business_name TEXT,
            business_address TEXT,
            business_phone TEXT,
            business_email TEXT,
            vat_number TEXT,
            banking_details TEXT,
            smtp_server TEXT,
            smtp_port INTEGER,
            smtp_username TEXT,
            smtp_password TEXT,
            smtp_from_email TEXT,
            smtp_use_tls INTEGER DEFAULT 1,
            smtp_use_ssl INTEGER DEFAULT 0,
            logo_file_path TEXT,
            logo_web_path TEXT,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            FOREIGN KEY (user_id) REFERENCES users(id) ON DELETE CASCADE
        )
    """)
    cursor.execute("PRAGMA table_info(business_profiles)")
    _bp_cols = {row[1] for row in cursor.fetchall()}
    if "banking_details" not in _bp_cols:
        cursor.execute("ALTER TABLE business_profiles ADD COLUMN banking_details TEXT")
    if "smtp_server" not in _bp_cols:
        cursor.execute("ALTER TABLE business_profiles ADD COLUMN smtp_server TEXT")
    if "smtp_port" not in _bp_cols:
        cursor.execute("ALTER TABLE business_profiles ADD COLUMN smtp_port INTEGER")
    if "smtp_username" not in _bp_cols:
        cursor.execute("ALTER TABLE business_profiles ADD COLUMN smtp_username TEXT")
    if "smtp_password" not in _bp_cols:
        cursor.execute("ALTER TABLE business_profiles ADD COLUMN smtp_password TEXT")
    if "smtp_from_email" not in _bp_cols:
        cursor.execute("ALTER TABLE business_profiles ADD COLUMN smtp_from_email TEXT")
    if "smtp_use_tls" not in _bp_cols:
        cursor.execute("ALTER TABLE business_profiles ADD COLUMN smtp_use_tls INTEGER DEFAULT 1")
    if "smtp_use_ssl" not in _bp_cols:
        cursor.execute("ALTER TABLE business_profiles ADD COLUMN smtp_use_ssl INTEGER DEFAULT 0")
    
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS invoices (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            owner_user_id INTEGER,
            customer_id INTEGER NOT NULL,
            invoice_number TEXT UNIQUE NOT NULL,
            description TEXT,
            status TEXT DEFAULT 'draft' CHECK (status IN ('draft', 'sent', 'paid', 'overdue', 'cancelled', 'partial')),
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
            FOREIGN KEY (owner_user_id) REFERENCES users(id) ON DELETE SET NULL,
            FOREIGN KEY (customer_id) REFERENCES customers(id) ON DELETE RESTRICT
        )
    """)
    
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS invoice_items (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            invoice_id INTEGER NOT NULL,
            item_description TEXT NOT NULL,
            quantity INTEGER NOT NULL DEFAULT 1,
            unit_price REAL NOT NULL,
            tax_rate REAL DEFAULT 0.15,
            line_total REAL NOT NULL,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            FOREIGN KEY (invoice_id) REFERENCES invoices(id) ON DELETE CASCADE
        )
    """)
    
    # NEW: Payments table for tracking payments
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS payments (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            invoice_id INTEGER NOT NULL,
            amount REAL NOT NULL,
            payment_date TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            payment_method TEXT CHECK (payment_method IN ('cash', 'credit_card', 'bank_transfer', 'cheque', 'digital_wallet', 'other')),
            reference_number TEXT,
            notes TEXT,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            FOREIGN KEY (invoice_id) REFERENCES invoices(id) ON DELETE RESTRICT,
            CHECK (amount > 0)
        )
    """)
    
    # NEW: Payment methods table for future expansion
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS payment_methods (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            name TEXT UNIQUE NOT NULL,
            description TEXT,
            is_active BOOLEAN DEFAULT 1
        )
    """)

    # NEW: Audit logs table
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS audit_logs (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            event_type TEXT NOT NULL,
            entity_type TEXT NOT NULL,
            entity_id INTEGER,
            actor TEXT DEFAULT 'system',
            source TEXT DEFAULT 'system',
            details_json TEXT,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )
    """)

    # NEW: Reminder settings
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS reminder_settings (
            id INTEGER PRIMARY KEY CHECK (id = 1),
            enabled INTEGER NOT NULL DEFAULT 1,
            interval_days INTEGER NOT NULL DEFAULT 7,
            start_after_days_overdue INTEGER NOT NULL DEFAULT 0,
            max_reminders INTEGER NOT NULL DEFAULT 12,
            updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )
    """)
    cursor.execute("""
        INSERT OR IGNORE INTO reminder_settings
        (id, enabled, interval_days, start_after_days_overdue, max_reminders)
        VALUES (1, 1, 7, 0, 12)
    """)
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS customer_reminder_settings (
            customer_id INTEGER PRIMARY KEY,
            enabled INTEGER,
            interval_days INTEGER,
            start_after_days_overdue INTEGER,
            max_reminders INTEGER,
            updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            FOREIGN KEY (customer_id) REFERENCES customers(id) ON DELETE CASCADE
        )
    """)
    cursor.execute("""
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
    """)
    
    # Insert default payment methods
    cursor.execute("INSERT OR IGNORE INTO payment_methods (name, description) VALUES (?, ?)", 
                  ('cash', 'Cash payment'))
    cursor.execute("INSERT OR IGNORE INTO payment_methods (name, description) VALUES (?, ?)", 
                  ('credit_card', 'Credit Card payment'))
    cursor.execute("INSERT OR IGNORE INTO payment_methods (name, description) VALUES (?, ?)", 
                  ('bank_transfer', 'Bank Transfer / EFT'))
    cursor.execute("INSERT OR IGNORE INTO payment_methods (name, description) VALUES (?, ?)", 
                  ('cheque', 'Cheque payment'))
    cursor.execute("INSERT OR IGNORE INTO payment_methods (name, description) VALUES (?, ?)", 
                  ('digital_wallet', 'Digital Wallet (PayPal, SnapScan, etc.)'))
    
    # Create indexes
    cursor.execute("CREATE INDEX IF NOT EXISTS idx_payments_invoice_id ON payments(invoice_id)")
    cursor.execute("CREATE INDEX IF NOT EXISTS idx_payments_payment_date ON payments(payment_date)")
    cursor.execute("CREATE INDEX IF NOT EXISTS idx_invoices_status ON invoices(status)")
    cursor.execute("CREATE INDEX IF NOT EXISTS idx_customers_owner_user_id ON customers(owner_user_id)")
    cursor.execute("CREATE INDEX IF NOT EXISTS idx_invoices_owner_user_id ON invoices(owner_user_id)")
    cursor.execute(
        "CREATE UNIQUE INDEX IF NOT EXISTS idx_customers_owner_id_number ON customers(owner_user_id, id_number)"
    )
    cursor.execute("CREATE INDEX IF NOT EXISTS idx_customers_id_number ON customers(id_number)")
    cursor.execute("CREATE INDEX IF NOT EXISTS idx_invoices_due_date ON invoices(due_date)")
    cursor.execute("CREATE INDEX IF NOT EXISTS idx_invoices_balance ON invoices(balance_due)")
    cursor.execute("CREATE INDEX IF NOT EXISTS idx_audit_logs_created_at ON audit_logs(created_at)")
    cursor.execute("CREATE INDEX IF NOT EXISTS idx_audit_logs_entity ON audit_logs(entity_type, entity_id)")
    cursor.execute("CREATE INDEX IF NOT EXISTS idx_reminder_events_invoice ON reminder_events(invoice_id, sent_at)")
    
    conn.commit()
    
    # Verify tables
    cursor.execute("SELECT name FROM sqlite_master WHERE type='table' ORDER BY name")
    tables = [row[0] for row in cursor.fetchall()]
    
    conn.close()
    
    print(f"✅ Database initialized successfully!")
    print(f"   Tables: {', '.join(tables)}")
    print(f"   ✅ Payments table added!")
    
    return True

if __name__ == "__main__":
    import sys
    force = '--force' in sys.argv or '-f' in sys.argv
    success = init_database(force=force)
    sys.exit(0 if success else 1)
