# database/migrate.py - Add payment tracking columns
import sqlite3
from pathlib import Path
import sys
from datetime import datetime  # ← MOVED IMPORT HERE

def migrate_database():
    """Add payment tracking columns to existing database."""
    
    db_path = Path(__file__).parent.parent / "data" / "business.db"
    
    if not db_path.exists():
        print("❌ Database not found. Run init.py first.")
        return False
    
    print(f"🔧 Migrating database: {db_path}")
    
    # Create backup first
    backup_path = db_path.parent / f"business_pre_migration_{datetime.now().strftime('%Y%m%d_%H%M%S')}.db"
    import shutil
    shutil.copy2(db_path, backup_path)
    print(f"✅ Backup created: {backup_path}")
    
    conn = sqlite3.connect(db_path)
    cursor = conn.cursor()
    
    try:
        # Check if columns already exist
        cursor.execute("PRAGMA table_info(invoices)")
        columns = [col[1] for col in cursor.fetchall()]
        
        # Add amount_paid column if missing
        if 'amount_paid' not in columns:
            cursor.execute("ALTER TABLE invoices ADD COLUMN amount_paid REAL DEFAULT 0.0")
            print("✅ Added column: amount_paid")
        
        # Add balance_due column if missing
        if 'balance_due' not in columns:
            cursor.execute("ALTER TABLE invoices ADD COLUMN balance_due REAL DEFAULT 0.0")
            print("✅ Added column: balance_due")
        
        # Update existing records
        cursor.execute("""
            UPDATE invoices 
            SET balance_due = total_amount - COALESCE(amount_paid, 0)
        """)
        print("✅ Updated balance_due for existing invoices")
        
        # Create payments table if not exists
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
        print("✅ Created payments table")
        
        # Create payment_methods table
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS payment_methods (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                name TEXT UNIQUE NOT NULL,
                description TEXT,
                is_active BOOLEAN DEFAULT 1
            )
        """)
        
        # Insert default payment methods
        default_methods = [
            ('cash', 'Cash payment'),
            ('credit_card', 'Credit Card payment'),
            ('bank_transfer', 'Bank Transfer / EFT'),
            ('cheque', 'Cheque payment'),
            ('digital_wallet', 'Digital Wallet (PayPal, SnapScan, etc.)')
        ]
        
        for name, desc in default_methods:
            cursor.execute("INSERT OR IGNORE INTO payment_methods (name, description) VALUES (?, ?)", (name, desc))
        print("✅ Added payment methods")
        
        # Create indexes
        cursor.execute("CREATE INDEX IF NOT EXISTS idx_payments_invoice_id ON payments(invoice_id)")
        cursor.execute("CREATE INDEX IF NOT EXISTS idx_payments_payment_date ON payments(payment_date)")
        cursor.execute("CREATE INDEX IF NOT EXISTS idx_invoices_balance ON invoices(balance_due)")
        cursor.execute("CREATE INDEX IF NOT EXISTS idx_invoices_status ON invoices(status)")
        print("✅ Created indexes")
        
        conn.commit()
        print("\n✅ Migration completed successfully!")
        
        # Show updated schema
        cursor.execute("PRAGMA table_info(invoices)")
        columns = cursor.fetchall()
        print("\n📊 Invoices table columns:")
        for col in columns:
            print(f"   • {col[1]} ({col[2]})")
        
        return True
        
    except Exception as e:
        conn.rollback()
        print(f"❌ Migration failed: {e}")
        return False
    finally:
        conn.close()

if __name__ == "__main__":
    success = migrate_database()
    sys.exit(0 if success else 1)
