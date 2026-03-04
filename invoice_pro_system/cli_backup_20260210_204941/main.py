# cli/main.py - CLEAN VERSION
import sys

def main():
    print("=" * 50)
    print("InvoicePro CLI")
    print("=" * 50)
    print("\nAvailable commands:")
    print("  python -m cli.main status    - Check system status")
    print("  python -m cli.main init      - Initialize database")
    print("  python -m cli.main test      - Run tests")
    print("\nExamples:")
    print("  python -m cli.main init")
    print("  python -m pytest tests/ -v")
    print("\n" + "=" * 50)
    return 0

if __name__ == "__main__":
    sys.exit(main())
