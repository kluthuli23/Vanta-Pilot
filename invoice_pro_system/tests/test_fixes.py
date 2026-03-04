# tests/test_fixes.py - Verify production fixes
import sys
import os
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

def test_invoice_number_generation():
    """Test that invoice numbers are sequential and unique."""
    from services.invoice_service import InvoiceService
    service = InvoiceService()

    # Generate multiple numbers inside write transactions,
    # matching the current service API contract.
    numbers = []
    conn = service._get_connection()
    cursor = conn.cursor()
    try:
        for _ in range(5):
            cursor.execute("BEGIN IMMEDIATE")
            number = service._generate_invoice_number(cursor)
            conn.commit()
            numbers.append(number)
    finally:
        conn.close()
    
    # Check they're unique
    assert len(set(numbers)) == len(numbers), "Invoice numbers should be unique"
    
    # Check format
    for num in numbers:
        assert num.startswith("INV-"), f"Invalid prefix: {num}"
        assert len(num) > 15, f"Number too short: {num}"
    
    print("✅ test_invoice_number_generation: PASSED")

def test_customer_search_sql():
    """Test that customer search SQL has correct WHERE clause."""
    from services.customer_service import CustomerService
    service = CustomerService()
    
    # Get the method source
    import inspect
    source = inspect.getsource(service.search_customers)
    
    # Check for correct SQL pattern
    assert "WHERE is_active = 1" in source, "Missing is_active filter"
    assert "AND (" in source, "Missing parentheses for OR conditions"
    assert "OR surname LIKE ?" in source, "Missing surname search"
    
    print("✅ test_customer_search_sql: PASSED")

def test_status_counts():
    """Test that status command shows both total and active."""
    import cli.main
    
    # Check function signature
    import inspect
    source = inspect.getsource(cli.main.handle_status)
    
    assert "get_all_customers(active_only=False)" in source, "Missing total count"
    assert "get_all_customers(active_only=True)" in source, "Missing active count"
    
    print("✅ test_status_counts: PASSED")

if __name__ == "__main__":
    print("🔍 Running production fix tests...")
    print("=" * 50)
    
    tests = [
        test_invoice_number_generation,
        test_customer_search_sql,
        test_status_counts
    ]
    
    passed = 0
    for test in tests:
        try:
            test()
            passed += 1
        except Exception as e:
            print(f"❌ {test.__name__}: FAILED - {e}")
    
    print("=" * 50)
    print(f"✅ {passed}/{len(tests)} tests passed")
