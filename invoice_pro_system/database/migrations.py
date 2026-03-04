# database/migrations.py
import sqlite3
from pathlib import Path
from config.settings import config
from config.logging_config import logger

def init_database():
    """Initialize database with latest schema."""
    
    schema_sql = [
        # Customers Table
        """
        CREATE TABLE IF NOT EXISTS customers (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            owner_user_id INTEGER,
            name TEXT NOT NULL,
            surname TEXT NOT NULL,
            id_number TEXT NOT NULL,
            company TEXT,
            email TEXT,
            phone TEXT,
            date_registered TIMESTAMP NOT NULL,
            is_active BOOLEAN DEFAULT 1,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            
            CHECK (name <> '' AND surname <> ''),
            CHECK (id_number <> '')
        )
        """,
        
        # Invoices Table
        """
        CREATE TABLE IF NOT EXISTS invoices (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            customer_id INTEGER NOT NULL,
            invoice_number TEXT UNIQUE NOT NULL,
            description TEXT,
            status TEXT DEFAULT 'draft' CHECK (status IN ('draft', 'sent', 'paid', 'overdue', 'cancelled')),
            subtotal REAL DEFAULT 0.0,
            tax_amount REAL DEFAULT 0.0,
            total_amount REAL DEFAULT 0.0,
            currency TEXT DEFAULT 'ZAR',
            due_date TIMESTAMP,
            invoice_date TIMESTAMP NOT NULL,
            paid_date TIMESTAMP,
            notes TEXT,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            
            FOREIGN KEY (customer_id) REFERENCES customers(id) ON DELETE RESTRICT,
            CHECK (subtotal >= 0),
            CHECK (tax_amount >= 0),
            CHECK (total_amount >= 0)
        )
        """,
        
        # Invoice Items Table
        """
        CREATE TABLE IF NOT EXISTS invoice_items (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            invoice_id INTEGER NOT NULL,
            item_description TEXT NOT NULL,
            quantity INTEGER NOT NULL DEFAULT 1,
            unit_price REAL NOT NULL,
            tax_rate REAL DEFAULT 0.15,
            discount REAL DEFAULT 0.0,
            line_total REAL NOT NULL,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            
            FOREIGN KEY (invoice_id) REFERENCES invoices(id) ON DELETE CASCADE,
            CHECK (quantity > 0),
            CHECK (unit_price >= 0),
            CHECK (tax_rate BETWEEN 0 AND 1),
            CHECK (discount BETWEEN 0 AND 1),
            CHECK (line_total >= 0)
        )
        """,
        
        # Payments Table
        """
        CREATE TABLE IF NOT EXISTS payments (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            invoice_id INTEGER NOT NULL,
            amount REAL NOT NULL,
            payment_method TEXT CHECK (payment_method IN ('cash', 'credit_card', 'bank_transfer', 'check', 'digital_wallet')),
            reference_number TEXT,
            payment_date TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            notes TEXT,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            
            FOREIGN KEY (invoice_id) REFERENCES invoices(id) ON DELETE RESTRICT,
            CHECK (amount > 0)
        )
        """
    ]
    
    indexes_sql = [
        "CREATE INDEX IF NOT EXISTS idx_customers_id_number ON customers(id_number)",
        "CREATE INDEX IF NOT EXISTS idx_customers_owner_user_id ON customers(owner_user_id)",
        "CREATE UNIQUE INDEX IF NOT EXISTS idx_customers_owner_id_number ON customers(owner_user_id, id_number)",
        "CREATE INDEX IF NOT EXISTS idx_invoices_customer_id ON invoices(customer_id)",
        "CREATE INDEX IF NOT EXISTS idx_invoices_status ON invoices(status)",
        "CREATE INDEX IF NOT EXISTS idx_invoices_invoice_number ON invoices(invoice_number)",
        "CREATE INDEX IF NOT EXISTS idx_invoice_items_invoice_id ON invoice_items(invoice_id)",
        "CREATE INDEX IF NOT EXISTS idx_payments_invoice_id ON payments(invoice_id)",
        "CREATE INDEX IF NOT EXISTS idx_customers_name ON customers(name, surname)",
    ]
    
    triggers_sql = [
        """
        CREATE TRIGGER IF NOT EXISTS update_customers_timestamp 
        AFTER UPDATE ON customers
        BEGIN
            UPDATE customers SET updated_at = CURRENT_TIMESTAMP WHERE id = NEW.id;
        END;
        """,
        """
        CREATE TRIGGER IF NOT EXISTS update_invoices_timestamp 
        AFTER UPDATE ON invoices
        BEGIN
            UPDATE invoices SET updated_at = CURRENT_TIMESTAMP WHERE id = NEW.id;
        END;
        """
    ]
    
    try:
        conn = sqlite3.connect(config.DB_PATH)
        cursor = conn.cursor()
        
        # Enable foreign keys
        cursor.execute("PRAGMA foreign_keys = ON")
        
        # Create tables
        for sql in schema_sql:
            cursor.execute(sql)
        
        # Create indexes
        for sql in indexes_sql:
            cursor.execute(sql)
        
        # Create triggers
        for sql in triggers_sql:
            try:
                cursor.execute(sql)
            except sqlite3.OperationalError as e:
                if "already exists" not in str(e):
                    raise
        
        # Verify tables
        cursor.execute("SELECT name FROM sqlite_master WHERE type='table' ORDER BY name")
        tables = cursor.fetchall()
        
        conn.commit()
        conn.close()
        
        logger.info(f"Database initialized with {len(tables)} tables")
        print(f"✅ Database initialized at: {config.DB_PATH}")
        print("📊 Tables created:")
        for table in tables:
            print(f"   - {table[0]}")
        
        return True
        
    except sqlite3.Error as e:
        logger.error(f"Database initialization failed: {e}")
        print(f"❌ Database initialization failed: {e}")
        return False
