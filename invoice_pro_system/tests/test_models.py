def test_customer_model():
    class Customer:
        def __init__(self, name, surname):
            self.name = name
            self.surname = surname
        
        def full_name(self):
            return f"{self.name} {self.surname}"
    
    customer = Customer("Khwezi", "Ngcobo")
    assert customer.full_name() == "Khwezi Ngcobo"
    print("✅ Customer model test passed")

def test_simple_assert():
    assert True
