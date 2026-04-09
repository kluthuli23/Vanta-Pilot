# config/settings.py
import os
from pathlib import Path

class Config:
    """Application configuration for Vanta Pilot."""
    
    # Base paths
    BASE_DIR = Path(__file__).parent.parent
    DATA_DIR = BASE_DIR / "data"
    LOGS_DIR = BASE_DIR / "logs"
    
    # Ensure directories exist
    DATA_DIR.mkdir(exist_ok=True)
    LOGS_DIR.mkdir(exist_ok=True)
    
    # Database
    DB_PATH = Path(os.getenv("DB_PATH", str(DATA_DIR / "business.db"))).expanduser()
    DB_TIMEOUT = 30
    
    # Application
    APP_NAME = "Vanta Pilot"
    DEFAULT_CURRENCY = "ZAR"
    VAT_RATE = 0.15  # South Africa VAT rate
    INVOICE_PREFIX = "INV"
    
    # Business defaults
    BUSINESS_NAME = "Your Business Name"
    BUSINESS_VAT_NUMBER = ""
    
    # Logging
    LOG_LEVEL = "INFO"
    LOG_FILE = LOGS_DIR / "invoice_system.log"
    
    @classmethod
    def validate(cls):
        """Validate configuration."""
        cls.DATA_DIR.mkdir(parents=True, exist_ok=True)
        cls.LOGS_DIR.mkdir(parents=True, exist_ok=True)
        cls.DB_PATH.parent.mkdir(parents=True, exist_ok=True)
        return True

# Create config instance
config = Config()

# For testing
if __name__ == "__main__":
    config.validate()
    print("? Configuration loaded successfully!")
    print(f"   Application: {config.APP_NAME}")
    print(f"   Database: {config.DB_PATH}")
    print(f"   Logs: {config.LOG_FILE}")
    print(f"   VAT Rate: {config.VAT_RATE:.1%}")

