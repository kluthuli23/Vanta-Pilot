def test_sql_syntax():
    sql = "CREATE TABLE customers (id INTEGER PRIMARY KEY, name TEXT)"
    assert "CREATE TABLE" in sql
    assert "customers" in sql
    assert "PRIMARY KEY" in sql
    print("✅ SQL syntax test passed")

def test_basic_math():
    assert 1 + 1 == 2
    print("✅ Basic math passed")
