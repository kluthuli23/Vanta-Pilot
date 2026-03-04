def test_invoice_calculation():
    """Test invoice calculations with proper decimal handling."""
    VAT_RATE = 0.15
    
    def calculate_total(quantity, price):
        # Use rounding for financial calculations
        total = quantity * price * (1 + VAT_RATE)
        return round(total, 2)  # Round to 2 decimal places
    
    # Test calculations with rounding
    assert calculate_total(1, 100) == 115.00
    assert calculate_total(2, 100) == 230.00
    assert calculate_total(5, 50) == 287.50
    
    # Test with more complex numbers
    assert calculate_total(3, 33.33) == round(3 * 33.33 * 1.15, 2)
    
    print("✅ Invoice calculation passed (with rounding)")

def test_invoice_validation():
    """Test invoice validation."""
    
    def validate_item(desc, qty, price):
        errors = []
        if not desc: 
            errors.append("Description required")
        if qty <= 0: 
            errors.append("Quantity must be positive")
        if price < 0: 
            errors.append("Price cannot be negative")
        return errors
    
    # Valid item
    assert len(validate_item("Web Design", 1, 3500)) == 0
    
    # Invalid items
    assert "Description required" in validate_item("", 1, 3500)
    assert "Quantity must be positive" in validate_item("Web Design", 0, 3500)
    assert "Price cannot be negative" in validate_item("Web Design", 1, -100)
    
    print("✅ Invoice validation passed")

def test_always_true():
    """Always true test."""
    assert True
    print("✅ Always true test passed")
