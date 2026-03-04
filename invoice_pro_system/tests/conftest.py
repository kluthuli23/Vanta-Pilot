import pytest

@pytest.fixture
def sample_customer():
    return {
        "name": "Khwezi",
        "surname": "Ngcobo", 
        "id_number": "1234567890123",
        "company": "KN Solutions"
    }

@pytest.fixture  
def sample_invoice_items():
    return [
        ("Web Design", 1, 3500.00),
        ("Hosting", 12, 100.00)
    ]
