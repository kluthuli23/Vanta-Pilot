# logo_manager.py - Company Logo Management
import os
import shutil
from pathlib import Path
from datetime import datetime

class LogoManager:
    """Manage company logos for invoices."""
    
    def __init__(self, logo_dir="logos"):
        self.logo_dir = Path(logo_dir)
        self.logo_dir.mkdir(exist_ok=True)
        self.supported_formats = ['.png', '.jpg', '.jpeg', '.gif', '.bmp']
    
    def add_logo(self, source_path):
        """
        Add a new company logo.
        
        Args:
            source_path: Path to the logo image file
        Returns:
            bool: True if successful, False otherwise
        """
        source = Path(source_path)
        
        # Check if file exists
        if not source.exists():
            print(f" File not found: {source}")
            return False
        
        # Check file extension
        if source.suffix.lower() not in self.supported_formats:
            print(f" Unsupported format: {source.suffix}")
            print(f"   Supported: {', '.join(self.supported_formats)}")
            return False
        
        # Create backup of existing logo
        existing = self.logo_dir / f"logo{source.suffix}"
        if existing.exists():
            backup_name = f"logo_backup_{datetime.now().strftime('%Y%m%d_%H%M%S')}{source.suffix}"
            backup_path = self.logo_dir / backup_name
            shutil.copy2(existing, backup_path)
            print(f" Backup created: {backup_name}")
        
        # Copy new logo
        destination = self.logo_dir / f"logo{source.suffix}"
        shutil.copy2(source, destination)
        
        # Also save as default logo.png for compatibility
        if source.suffix.lower() != '.png':
            png_destination = self.logo_dir / "logo.png"
            try:
                from PIL import Image
                img = Image.open(source)
                img.save(png_destination, 'PNG')
                print(f" Converted to PNG format")
            except ImportError:
                print("  Install Pillow for PNG conversion: pip install Pillow")
        
        print(f" Logo added successfully: {destination}")
        print(f"   Original: {source.name}")
        print(f"   Size: {destination.stat().st_size:,} bytes")
        
        return True
    
    def remove_logo(self):
        """Remove current logo."""
        removed = False
        for ext in self.supported_formats + ['.txt']:
            logo_path = self.logo_dir / f"logo{ext}"
            if logo_path.exists():
                backup_name = f"logo_removed_{datetime.now().strftime('%Y%m%d_%H%M%S')}{ext}"
                backup_path = self.logo_dir / backup_name
                shutil.move(logo_path, backup_path)
                print(f" Logo moved to backup: {backup_name}")
                removed = True
        
        if removed:
            print(" Logo removed successfully")
        else:
            print(" No logo found to remove")
        
        return removed
    
    def list_logos(self):
        """List all logos and backups."""
        print("\n Current Logos:")
        print("-" * 50)
        
        # Current active logo
        active = None
        for ext in self.supported_formats:
            logo_path = self.logo_dir / f"logo{ext}"
            if logo_path.exists():
                size = logo_path.stat().st_size
                modified = datetime.fromtimestamp(logo_path.stat().st_mtime)
                active = (logo_path.name, size, modified)
                print(f" ACTIVE: {logo_path.name}")
                print(f"   Size: {size:,} bytes")
                print(f"   Updated: {modified.strftime('%Y-%m-%d %H:%M:%S')}")
        
        if not active:
            print(" No active logo found")
        
        # Backups
        backups = list(self.logo_dir.glob("logo_backup_*")) + \
                  list(self.logo_dir.glob("logo_removed_*"))
        
        if backups:
            print(f"\n Backups ({len(backups)}):")
            for backup in sorted(backups, key=lambda x: x.stat().st_mtime, reverse=True)[:5]:
                size = backup.stat().st_size
                modified = datetime.fromtimestamp(backup.stat().st_mtime)
                print(f"    {backup.name}")
                print(f"      Size: {size:,} bytes")
                print(f"      Date: {modified.strftime('%Y-%m-%d %H:%M:%S')}")
        
        return active

def main():
    """Command-line interface for logo management."""
    import sys
    manager = LogoManager()
    
    if len(sys.argv) < 2:
        print(" Logo Manager Commands:")
        print("  python logo_manager.py add <path_to_logo>  - Add new logo")
        print("  python logo_manager.py remove              - Remove current logo")
        print("  python logo_manager.py list                - List logos")
        print("  python logo_manager.py test                - Test with sample logo")
        return
    
    command = sys.argv[1]
    
    if command == "add" and len(sys.argv) > 2:
        manager.add_logo(sys.argv[2])
    elif command == "remove":
        manager.remove_logo()
    elif command == "list":
        manager.list_logos()
    elif command == "test":
        # Create a simple test logo
        test_logo = manager.logo_dir / "test_logo.txt"
        test_logo.write_text("""

                                    
       YOUR COMPANY LOGO HERE       
                                    

        """)
        print(" Test logo created")
        manager.add_logo(test_logo)
    else:
        print(f" Unknown command: {command}")

if __name__ == "__main__":
    main()
