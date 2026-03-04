# config/logging_config.py
import sys
import logging
from pathlib import Path

# Import settings
try:
    from config.settings import config
except ImportError:
    # Fallback configuration if import fails
    class FallbackConfig:
        LOG_LEVEL = "INFO"
        LOGS_DIR = Path("logs")
        LOG_FILE = Path("logs") / "invoice_system.log"
    
    config = FallbackConfig()
    config.LOGS_DIR.mkdir(exist_ok=True)

def setup_logging():
    """Setup logging for the application."""
    
    # Ensure logs directory exists
    config.LOGS_DIR.mkdir(exist_ok=True)
    
    # Create formatters
    detailed_formatter = logging.Formatter(
        fmt='%(asctime)s | %(levelname)-8s | %(name)s | %(message)s',
        datefmt='%Y-%m-%d %H:%M:%S'
    )
    
    simple_formatter = logging.Formatter(
        fmt='%(levelname)-8s | %(message)s'
    )
    
    # Console handler (simple)
    console_handler = logging.StreamHandler(sys.stdout)
    console_handler.setLevel(getattr(logging, config.LOG_LEVEL))
    console_handler.setFormatter(simple_formatter)
    
    # File handler (detailed)
    file_handler = logging.FileHandler(config.LOG_FILE)
    file_handler.setLevel(logging.DEBUG)
    file_handler.setFormatter(detailed_formatter)
    
    # Configure root logger
    root_logger = logging.getLogger()
    root_logger.setLevel(logging.DEBUG)
    
    # Remove existing handlers to avoid duplicates
    root_logger.handlers.clear()
    
    # Add new handlers
    root_logger.addHandler(console_handler)
    root_logger.addHandler(file_handler)
    
    # Set third-party loggers to WARNING
    logging.getLogger('sqlite3').setLevel(logging.WARNING)
    
    return root_logger

# Setup logging
logger = setup_logging()

# Test function
if __name__ == "__main__":
    logger.info("? Logging system initialized successfully!")
    logger.debug("This is a debug message")
    logger.warning("This is a warning message")
    logger.error("This is an error message")
    
    print(f"\n?? Log file location: {config.LOG_FILE}")
    print("? Logging configuration test complete!")

