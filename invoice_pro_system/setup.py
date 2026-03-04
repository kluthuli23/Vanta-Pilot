# setup.py - Vanta Pilot setup
import sys
import os
from pathlib import Path

def setup_project():
    """Setup the Vanta Pilot project."""
    print("=" * 60)
    print("Vanta Pilot Setup")
    print("=" * 60)
    
    current_dir = Path(__file__).parent
    
    # 1. Create required directories
    directories = ["data", "logs", "config", "database", "services", "cli", "tests"]
    for dir_name in directories:
        dir_path = current_dir / dir_name
        dir_path.mkdir(exist_ok=True)
        print(f"? Created: {dir_name}/")
    
    # 2. Install dependencies
    print("\n?? Installing dependencies...")
    os.system(f"{sys.executable} -m pip install python-dotenv pytest")
    
    # 3. Initialize database
    print("\n???  Initializing database...")
    init_file = current_dir / "database" / "init.py"
    if init_file.exists():
        with open(init_file, 'r') as f:
            exec(f.read())
        print("? Database initialized")
    else:
        print("??  database/init.py not found")
    
    print("\n" + "=" * 60)
    print("? Setup complete!")
    print("\nNext steps:")
    print("  1. python -m cli.main status")
    print("  2. python -m cli.main test")
    print("  3. Start building your business!")
    print("=" * 60)

if __name__ == "__main__":
    setup_project()
