# services/customer_service.py - REAL DATABASE OPERATIONS
import sqlite3
import re
import uuid
from datetime import datetime
from typing import List, Dict, Any, Optional

from database.safety import ensure_schema_backup, get_db_path
from services.audit_service import AuditService

class CustomerService:
    """Real database operations for customer management."""
    
    def __init__(self, db_path=None):
        self.db_path = get_db_path(db_path)
        
        # Ensure directory exists
        self.db_path.parent.mkdir(exist_ok=True)
        self.audit_service = AuditService(str(self.db_path))
        self._ensure_owner_column()
        self._ensure_address_column()
    
    def _get_connection(self):
        """Get database connection with row factory."""
        conn = sqlite3.connect(self.db_path)
        conn.row_factory = sqlite3.Row  # This allows column access by name
        conn.execute("PRAGMA foreign_keys = ON")
        return conn

    def _ensure_owner_column(self):
        """Ensure customers schema supports tenant isolation."""
        ensure_schema_backup(self.db_path, reason="customers")
        conn = self._get_connection()
        cursor = conn.cursor()
        try:
            default_owner = None
            try:
                cursor.execute("SELECT id FROM users ORDER BY id LIMIT 1")
                row = cursor.fetchone()
                if row:
                    default_owner = int(row["id"])
            except sqlite3.Error:
                default_owner = None

            if self._needs_tenant_unique_migration(cursor):
                self._migrate_customers_for_tenant_isolation(
                    conn=conn,
                    cursor=cursor,
                    default_owner=default_owner,
                )

            cursor.execute("PRAGMA table_info(customers)")
            columns = {row["name"] for row in cursor.fetchall()}
            if "owner_user_id" not in columns:
                cursor.execute("ALTER TABLE customers ADD COLUMN owner_user_id INTEGER")
            cursor.execute(
                "CREATE INDEX IF NOT EXISTS idx_customers_owner_user_id ON customers(owner_user_id)"
            )
            cursor.execute(
                """
                CREATE UNIQUE INDEX IF NOT EXISTS idx_customers_owner_id_number
                ON customers(owner_user_id, id_number)
                """
            )
            cursor.execute(
                "CREATE INDEX IF NOT EXISTS idx_customers_id_number ON customers(id_number)"
            )

            if default_owner is not None:
                cursor.execute(
                    """
                    UPDATE customers
                    SET owner_user_id = ?
                    WHERE owner_user_id IS NULL
                    """,
                    (default_owner,),
                )
            conn.commit()
        finally:
            conn.close()

    def _ensure_address_column(self):
        """Ensure customers schema includes address field."""
        ensure_schema_backup(self.db_path, reason="customers")
        conn = self._get_connection()
        cursor = conn.cursor()
        try:
            cursor.execute("PRAGMA table_info(customers)")
            columns = {row["name"] for row in cursor.fetchall()}
            if "address" not in columns:
                cursor.execute("ALTER TABLE customers ADD COLUMN address TEXT")
                conn.commit()
        finally:
            conn.close()

    def _needs_tenant_unique_migration(self, cursor: sqlite3.Cursor) -> bool:
        """Return True if customers still enforces global unique id_number."""
        cursor.execute(
            "SELECT sql FROM sqlite_master WHERE type='table' AND name='customers'"
        )
        row = cursor.fetchone()
        if not row:
            return False
        table_sql = (row["sql"] or "").upper()
        if "ID_NUMBER TEXT UNIQUE" in table_sql:
            return True

        cursor.execute("PRAGMA index_list(customers)")
        for idx in cursor.fetchall():
            if int(idx["unique"]) != 1:
                continue
            idx_name = idx["name"]
            cursor.execute(f"PRAGMA index_info({idx_name})")
            cols = [c["name"] for c in cursor.fetchall()]
            if cols == ["id_number"]:
                return True
        return False

    def _migrate_customers_for_tenant_isolation(
        self,
        conn: sqlite3.Connection,
        cursor: sqlite3.Cursor,
        default_owner: Optional[int],
    ) -> None:
        """Rebuild customers table to remove global unique(id_number)."""
        cursor.execute("PRAGMA table_info(customers)")
        columns = {row["name"] for row in cursor.fetchall()}
        has_owner_col = "owner_user_id" in columns

        conn.execute("PRAGMA foreign_keys = OFF")
        try:
            cursor.execute("BEGIN")
            cursor.execute(
                """
                CREATE TABLE customers_new (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    owner_user_id INTEGER,
                    name TEXT NOT NULL,
                    surname TEXT NOT NULL,
                    id_number TEXT NOT NULL,
                    company TEXT,
                    email TEXT,
                    phone TEXT,
                    address TEXT,
                    date_registered TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                    is_active BOOLEAN DEFAULT 1,
                    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                    FOREIGN KEY (owner_user_id) REFERENCES users(id) ON DELETE SET NULL
                )
                """
            )

            if has_owner_col:
                owner_expr = "owner_user_id"
            elif default_owner is not None:
                owner_expr = str(int(default_owner))
            else:
                owner_expr = "NULL"

            cursor.execute(
                f"""
                INSERT INTO customers_new
                (
                    id, owner_user_id, name, surname, id_number, company, email, phone, address,
                    date_registered, is_active, created_at, updated_at
                )
                SELECT
                    id, {owner_expr}, name, surname, id_number, company, email, phone, NULL,
                    date_registered, is_active, created_at, updated_at
                FROM customers
                """
            )

            cursor.execute("DROP TABLE customers")
            cursor.execute("ALTER TABLE customers_new RENAME TO customers")
            cursor.execute(
                "CREATE INDEX IF NOT EXISTS idx_customers_owner_user_id ON customers(owner_user_id)"
            )
            cursor.execute(
                """
                CREATE UNIQUE INDEX IF NOT EXISTS idx_customers_owner_id_number
                ON customers(owner_user_id, id_number)
                """
            )
            cursor.execute(
                "CREATE INDEX IF NOT EXISTS idx_customers_id_number ON customers(id_number)"
            )
            conn.commit()
        except Exception:
            conn.rollback()
            raise
        finally:
            conn.execute("PRAGMA foreign_keys = ON")

    def _is_valid_email(self, email: str) -> bool:
        email = (email or "").strip()
        return "@" in email and "." in email.split("@")[-1]

    def _normalize_address(self, address: str) -> str:
        """Normalize address to first-letter-capitalized words."""
        text = re.sub(r"\s+", " ", str(address or "").strip())
        if not text:
            return ""
        words = text.split(" ")
        normalized = []
        for word in words:
            if not word:
                continue
            if word[0].isalpha():
                normalized.append(word[0].upper() + word[1:].lower())
            else:
                normalized.append(word)
        return " ".join(normalized)

    def _normalize_sa_phone(self, phone: str) -> Optional[str]:
        """Normalize SA phone to +27 XX XXX XXXX. Returns None when invalid."""
        raw = str(phone or "").strip()
        if not raw:
            return None
        digits = re.sub(r"\D", "", raw)
        if digits.startswith("27"):
            national = digits[2:]
        elif digits.startswith("0"):
            national = digits[1:]
        else:
            national = digits
        if len(national) != 9 or not national.isdigit():
            return None
        return f"+27 {national[0:2]} {national[2:5]} {national[5:9]}"
    
    def _ensure_id_number(self, id_number: Optional[str], user_id: Optional[int]) -> Optional[str]:
        """Return a non-empty id_number. Auto-generate when missing."""
        raw = str(id_number or "").strip()
        if raw:
            return raw
        # Generate a stable unique token per customer (not a personal ID).
        return f"AUTO-{uuid.uuid4().hex[:12]}"

    def create_customer(
        self,
        name: str,
        surname: str,
        id_number: Optional[str] = None,
        company: str = None,
        email: str = None,
        phone: str = None,
        address: str = None,
        user_id: Optional[int] = None,
    ) -> Optional[int]:
        """
        Create a new customer in the database.
        
        Args:
            name: First name
            surname: Last name
            id_number: SA ID number (13 digits)
            company: Company name (optional)
            email: Email address (optional)
            phone: Phone number (optional)
        
        Returns:
            customer_id if successful, None if failed
        """
        if not str(name or "").strip() or not str(surname or "").strip():
            print(" Name and surname are required")
            return None

        id_number = self._ensure_id_number(id_number, user_id)
        if not id_number:
            print(" Invalid customer identifier")
            return None

        if email and not self._is_valid_email(email):
            print(" Invalid email address")
            return None
        normalized_phone = None
        if phone:
            normalized_phone = self._normalize_sa_phone(phone)
            if not normalized_phone:
                print(" Invalid phone number: use SA number format")
                return None
        normalized_address = self._normalize_address(address) if address else None
        
        conn = self._get_connection()
        cursor = conn.cursor()
        
        try:
            # Check if customer already exists
            if user_id is None:
                cursor.execute(
                    "SELECT id FROM customers WHERE id_number = ?",
                    (id_number,),
                )
            else:
                cursor.execute(
                    "SELECT id FROM customers WHERE id_number = ? AND owner_user_id = ?",
                    (id_number, int(user_id)),
                )
            existing = cursor.fetchone()
            if existing:
                print(f" Customer with ID {id_number} already exists")
                return existing['id']
            
            # Insert new customer
            cursor.execute("""
                INSERT INTO customers 
                (name, surname, id_number, company, email, phone, address, date_registered, owner_user_id)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
            """, (name.strip(), surname.strip(), id_number.strip(),
                  company.strip() if company else None,
                  email.strip().lower() if email else None,
                  normalized_phone,
                  normalized_address,
                  datetime.now(),
                  int(user_id) if user_id is not None else None))
            
            customer_id = cursor.lastrowid
            conn.commit()
            self.audit_service.log_action(
                event_type="customer_created",
                entity_type="customer",
                entity_id=customer_id,
                source="service",
                details={
                    "name": name,
                    "surname": surname,
                    "company": company,
                    "email": email,
                },
            )
            
            print(f" Customer added successfully!")
            print(f"   ID: {customer_id}")
            print(f"   Name: {name} {surname}")
            print(f"   Customer Ref: {id_number}")
            if company:
                print(f"   Company: {company}")
            
            return customer_id
            
        except sqlite3.IntegrityError as e:
            print(f" Database error: {e}")
            return None
        except Exception as e:
            print(f" Error creating customer: {e}")
            return None
        finally:
            conn.close()
    
    
    def get_customer_by_id(
        self, customer_id: int, active_only: bool = True, user_id: Optional[int] = None
    ) -> Optional[Dict]:
        """Get customer by ID, optionally only active customers."""
        conn = self._get_connection()
        cursor = conn.cursor()
        
        try:
            query = "SELECT * FROM customers WHERE id = ?"
            if active_only:
                query += " AND is_active = 1"
            params = [customer_id]
            if user_id is not None:
                query += " AND owner_user_id = ?"
                params.append(int(user_id))
            cursor.execute(query, params)
            row = cursor.fetchone()
            
            if row:
                return dict(row)
            return None
            
        except Exception as e:
            print(f" Error fetching customer: {e}")
            return None
        finally:
            conn.close()

    def get_customer_by_id_number(
        self, id_number: str, active_only: bool = True, user_id: Optional[int] = None
    ) -> Optional[Dict]:
        """Get customer by ID number, optionally only active customers."""
        conn = self._get_connection()
        cursor = conn.cursor()
        
        try:
            query = "SELECT * FROM customers WHERE id_number = ?"
            if active_only:
                query += " AND is_active = 1"
            params = [id_number]
            if user_id is not None:
                query += " AND owner_user_id = ?"
                params.append(int(user_id))
            cursor.execute(query, params)
            row = cursor.fetchone()
            
            if row:
                return dict(row)
            return None
            
        except Exception as e:
            print(f" Error fetching customer: {e}")
            return None
        finally:
            conn.close()
    
    def get_all_customers(self, active_only: bool = True, user_id: Optional[int] = None) -> List[Dict]:
        """Get all customers from database."""
        conn = self._get_connection()
        cursor = conn.cursor()
        
        try:
            query = "SELECT * FROM customers"
            clauses = []
            params = []
            if active_only:
                clauses.append("is_active = 1")
            if user_id is not None:
                clauses.append("owner_user_id = ?")
                params.append(int(user_id))
            if clauses:
                query += " WHERE " + " AND ".join(clauses)
            query += " ORDER BY surname, name"
            
            cursor.execute(query, params)
            rows = cursor.fetchall()
            
            return [dict(row) for row in rows]
            
        except Exception as e:
            print(f" Error fetching customers: {e}")
            return []
        finally:
            conn.close()
    
    def update_customer(self, customer_id: int, user_id: Optional[int] = None, **kwargs) -> bool:
        """Update customer information."""
        allowed_fields = {'name', 'surname', 'company', 'email', 'phone', 'address', 'is_active'}
        updates = {k: v for k, v in kwargs.items() if k in allowed_fields}
        
        if not updates:
            print(" No valid fields to update")
            return False

        if "email" in updates and updates["email"]:
            email = str(updates["email"]).strip().lower()
            if not self._is_valid_email(email):
                print(" Invalid email address")
                return False
            updates["email"] = email
        if "phone" in updates:
            if updates["phone"]:
                normalized_phone = self._normalize_sa_phone(str(updates["phone"]))
                if not normalized_phone:
                    print(" Invalid phone number: use SA number format")
                    return False
                updates["phone"] = normalized_phone
            else:
                updates["phone"] = None
        if "address" in updates:
            if updates["address"]:
                updates["address"] = self._normalize_address(str(updates["address"]))
            else:
                updates["address"] = None
        
        # Add updated timestamp
        updates['updated_at'] = datetime.now()
        
        set_clause = ", ".join([f"{field} = ?" for field in updates.keys()])
        values = list(updates.values())
        values.append(customer_id)
        where_clause = "WHERE id = ?"
        if user_id is not None:
            where_clause += " AND owner_user_id = ?"
            values.append(int(user_id))
        
        conn = self._get_connection()
        cursor = conn.cursor()
        
        try:
            cursor.execute(f"""
                UPDATE customers 
                SET {set_clause}
                {where_clause}
            """, values)
            
            conn.commit()
            
            if cursor.rowcount > 0:
                print(f" Customer {customer_id} updated successfully")
                self.audit_service.log_action(
                    event_type="customer_updated",
                    entity_type="customer",
                    entity_id=customer_id,
                    source="service",
                    details=updates,
                )
                return True
            else:
                print(f" Customer {customer_id} not found")
                return False
                
        except Exception as e:
            print(f" Error updating customer: {e}")
            return False
        finally:
            conn.close()
    
    def delete_customer(self, customer_id: int, soft_delete: bool = True, user_id: Optional[int] = None) -> bool:
        """Delete a customer (soft delete by default)."""
        conn = self._get_connection()
        cursor = conn.cursor()
        
        try:
            if soft_delete:
                query = """
                    UPDATE customers
                    SET is_active = 0, updated_at = ?
                    WHERE id = ?
                """
                params = [datetime.now(), customer_id]
                if user_id is not None:
                    query += " AND owner_user_id = ?"
                    params.append(int(user_id))
                cursor.execute(query, params)
            else:
                # Check for existing invoices before hard delete
                query = "SELECT COUNT(*) FROM invoices WHERE customer_id = ?"
                params = [customer_id]
                if user_id is not None:
                    query += " AND owner_user_id = ?"
                    params.append(int(user_id))
                cursor.execute(query, params)
                count = cursor.fetchone()[0]
                if count > 0:
                    print(f" Cannot delete: customer has {count} invoices")
                    return False
                
                query = "DELETE FROM customers WHERE id = ?"
                params = [customer_id]
                if user_id is not None:
                    query += " AND owner_user_id = ?"
                    params.append(int(user_id))
                cursor.execute(query, params)
            
            conn.commit()
            success = cursor.rowcount > 0
            
            if success:
                print(f" Customer {customer_id} {'soft ' if soft_delete else ''}deleted")
                self.audit_service.log_action(
                    event_type="customer_deleted" if not soft_delete else "customer_deactivated",
                    entity_type="customer",
                    entity_id=customer_id,
                    source="service",
                    details={"soft_delete": soft_delete},
                )
            else:
                print(f" Customer {customer_id} not found")
            
            return success
            
        except Exception as e:
            print(f" Error deleting customer: {e}")
            return False
        finally:
            conn.close()
    
    def search_customers(self, search_term: str, user_id: Optional[int] = None) -> List[Dict]:
        """Search customers by name, surname, or company."""
        conn = self._get_connection()
        cursor = conn.cursor()
        
        try:
            query = """
                SELECT * FROM customers 
                WHERE is_active = 1 
                AND (
                    name LIKE ? 
                    OR surname LIKE ? 
                    OR company LIKE ?
                )
                ORDER BY surname, name
            """
            params = [
                f'%{search_term}%',
                f'%{search_term}%',
                f'%{search_term}%',
            ]
            if user_id is not None:
                query = query.replace("ORDER BY", "AND owner_user_id = ? ORDER BY")
                params.append(int(user_id))
            cursor.execute(query, params)
            
            rows = cursor.fetchall()
            return [dict(row) for row in rows]
            
        except Exception as e:
            print(f" Error searching customers: {e}")
            return []
        finally:
            conn.close()

# For testing
if __name__ == "__main__":
    service = CustomerService()
    print(f" CustomerService initialized")
    print(f"   Database: {service.db_path}")
    
    # Test connection
    conn = service._get_connection()
    cursor = conn.cursor()
    cursor.execute("SELECT COUNT(*) FROM customers")
    count = cursor.fetchone()[0]
    conn.close()
    print(f"   Customers in database: {count}")



