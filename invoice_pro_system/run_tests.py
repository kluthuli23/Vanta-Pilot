# run_tests.py - Test Runner for InvoicePro
import sys
import os

def check_and_create_files():
    """Check if test files exist and create them if missing."""
    
    test_files = [
        "tests/__init__.py",
        "tests/conftest.py",
        "tests/test_database.py",
        "tests/test_customers.py",
        "tests/test_invoices.py",
        "tests/test_cli.py",
        "tests/test_models.py"
    ]
    
    # Check which files exist
    missing_files = []
    for file in test_files:
        if not os.path.exists(file):
            missing_files.append(file)
    
    return missing_files

def create_test_files():
    """Create basic test files."""
    
    # Create tests directory if it doesn't exist
    if not os.path.exists("tests"):
        os.makedirs("tests")
        print("✅ Created tests directory")
    
    # Create __init__.py
    init_content = "# Tests package\n"
    with open("tests/__init__.py", "w") as f:
        f.write(init_content)
    
    # Create minimal conftest.py
    conftest_content = '''
import pytest
import tempfile
import os

@pytest.fixture
def sample_customer_data():
    return {
        "name": "Test",
        "surname": "User",
        "id_number": "1234567890123",
        "company": "Test Company"
    }
'''
    with open("tests/conftest.py", "w") as f:
        f.write(conftest_content)
    
    # Create a simple test file
    test_content = '''
def test_example():
    """Example test."""
    assert 1 + 1 == 2
'''
    with open("tests/test_example.py", "w") as f:
        f.write(test_content)
    
    print("✅ Created basic test files")
    return True

def main():
    """Main function to run or setup tests."""
    
    print("🔍 InvoicePro Test Runner")
    print("=" * 50)
    
    # Check if pytest is installed
    try:
        import pytest
        print("✅ pytest is installed")
    except ImportError:
        print("❌ pytest is not installed")
        print("   Install it with: pip install pytest")
        return 1
    
    # Check test files
    missing = check_and_create_files()
    
    if missing:
        print(f"⚠️  Missing {len(missing)} test files")
        response = input("Create basic test files? (y/n): ")
        if response.lower() == 'y':
            create_test_files()
        else:
            print("Please create test files first")
            return 1
    
    # Run tests
    print("\n🚀 Running tests...")
    print("-" * 50)
    
    # Import and run pytest
    import pytest
    return_code = pytest.main(["-v", "tests/"])
    
    print("=" * 50)
    if return_code == 0:
        print("✅ All tests passed!")
    else:
        print("❌ Some tests failed")
    
    return return_code

if __name__ == "__main__":
    sys.exit(main())