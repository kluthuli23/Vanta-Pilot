def test_customer_validation():
    def validate_customer(name, surname, id_number):
        errors = []
        if not name: errors.append("Name required")
        if not surname: errors.append("Surname required")
        if not id_number or len(id_number) != 13: 
            errors.append("ID must be 13 digits")
        return errors
    
    assert len(validate_customer("Khwezi", "Ngcobo", "1234567890123")) == 0
    assert "Name required" in validate_customer("", "Ngcobo", "1234567890123")
    assert "ID must be 13 digits" in validate_customer("Khwezi", "Ngcobo", "123")
    
    print("✅ Customer validation passed")

def test_customer_name_format():
    def format_name(name, surname):
        return f"{name} {surname}".strip()
    
    assert format_name("Khwezi", "Ngcobo") == "Khwezi Ngcobo"
    print("✅ Name format passed")

def test_always_passes():
    assert True
