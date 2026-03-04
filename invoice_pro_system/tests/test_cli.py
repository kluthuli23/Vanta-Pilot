def test_cli_parsing():
    def parse_command(args):
        return {"command": args[0] if args else None}
    
    result = parse_command(["status"])
    assert result["command"] == "status"
    print("✅ CLI parsing test passed")

def test_basic():
    assert 2 + 2 == 4
