# database/fix_status_constraint.py - Add 'partial' to status options
import sqlite3
from pathlib import Path
import sys
from datetime import datetime

def fix_status_constraint():
    """Update the status constraint to include 'partial'."""
    
    db_path = Path(__file__).parent.parent / "data" / "business.db"
    
    if not db_path.exists():
        print("❌ Database not found")
        return False
    
    print(f"🔧 Fixing status constraint in: {db_path}")
    
    # Create backup
    backup_path = db_path.parent / f"business_status_fix_{datetime.now().strftime('%Y%m%d_%H%M%S')}.db"
    import shutil
    shutil.copy2(db_path, backup_path)
    print(f"✅ Backup created: {backup_path}")
    
    conn = sqlite3.connect(db_path)
    cursor = conn.cursor()
    
    try:
        # SQLite doesn't support dropping constraints directly
        # We need to recreate the table
        
        # 1. Get current table schema
        cursor.execute("PRAGMA table_info(invoices)")
        columns = cursor.fetchall()
        
        # 2. Create new table with correct constraint
        cursor.execute("""
            CREATE TABLE invoices_new (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
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
                FOREIGN KEY (customer_id) REFERENCES customers(id) ON DELETE RESTRICT
            )
        """)
        
        # 3. Copy data from old table
        cursor.execute("""
            INSERT INTO invoices_new 
            SELECT id, customer_id, invoice_number, description, status, 
                   subtotal, tax_amount, total_amount, 
                   COALESCE(amount_paid, 0) as amount_paid, 
                   COALESCE(balance_due, total_amount) as balance_due,
                   currency, due_date, invoice_date, paid_date, notes, 
                   created_at, updated_at
            FROM invoices
        """)
        
        # 4. Drop old table and rename new one
        cursor.execute("DROP TABLE invoices")
        cursor.execute("ALTER TABLE invoices_new RENAME TO invoices")
        
        # 5. Recreate indexes
        cursor.execute("CREATE INDEX IF NOT EXISTS idx_invoices_customer_id ON invoices(customer_id)")
        cursor.execute("CREATE INDEX IF NOT EXISTS idx_invoices_status ON invoices(status)")
        cursor.execute("CREATE INDEX IF NOT EXISTS idx_invoices_invoice_number ON invoices(invoice_number)")
        cursor.execute("CREATE INDEX IF NOT EXISTS idx_invoices_due_date ON invoices(due_date)")
        cursor.execute("CREATE INDEX IF NOT EXISTS idx_invoices_balance ON invoices(balance_due)")
        
        conn.commit()
        
        print("✅ Status constraint updated - 'partial' now allowed")
        
        # Verify
        cursor.execute("PRAGMA table_info(invoices)")
        print("\n📊 Updated invoices table structure:")
        for col in cursor.fetchall():
            print(f"   • {col[1]} ({col[2]})")
        
        return True
        
    except Exception as e:
        conn.rollback()
        print(f"❌ Fix failed: {e}")
        return False
    finally:
        conn.close()

if __name__ == "__main__":
    success = fix_status_constraint()
    sys.exit(0 if success else 1)
