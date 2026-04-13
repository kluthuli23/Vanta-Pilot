"""Compatibility wrapper for database initialization.

Historically the app had two competing schema initializers:
- `database.init.init_database`
- `database.migrations.init_database`

That split is risky in production because different startup paths can create
different tables/columns, which leads to account loss, missing relationships,
and foreign key errors. This module now delegates to the canonical initializer
so every environment uses the same schema evolution path.
"""

from config.logging_config import logger

from database.init import init_database as _init_database


def init_database(force: bool = False):
    """Initialize or migrate the database using the canonical schema path."""
    try:
        return _init_database(force=force)
    except TypeError:
        # Backward compatibility in case older callers import this module with
        # a different function signature somewhere outside the main app.
        logger.warning("Falling back to init_database() without force parameter support.")
        return _init_database()
