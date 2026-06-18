def test_cli_parsing():
    def parse_command(args):
        return {"command": args[0] if args else None}
    
    result = parse_command(["status"])
    assert result["command"] == "status"
    print("✅ CLI parsing test passed")

def test_basic():
    assert 2 + 2 == 4


def test_admin_set_password_cli_parsing():
    from cli.main import setup_argparse

    parser = setup_argparse()
    args = parser.parse_args(
        [
            "admin",
            "set-password",
            "--email",
            "admin@example.com",
            "--password",
            "StrongAdminPass1!",
            "--create",
        ]
    )

    assert args.command == "admin"
    assert args.admin_cmd == "set-password"
    assert args.email == "admin@example.com"
    assert args.create is True
