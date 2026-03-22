import logging
import logging.config
import os
import sys
from pythonjsonlogger import jsonlogger  # noqa: F401 — used by dictConfig string refs
from backend.core.api.app.utils.log_filters import SensitiveDataFilter
from backend.core.api.app.utils.request_context import RequestIdLogFilter

# Determine environment
SERVER_ENVIRONMENT = os.getenv("SERVER_ENVIRONMENT", "development").lower()
IS_PRODUCTION = SERVER_ENVIRONMENT == "production"

# Set default log level based on environment
DEFAULT_LOG_LEVEL = "WARNING" if IS_PRODUCTION else "INFO"
LOG_LEVEL = os.getenv("LOG_LEVEL", DEFAULT_LOG_LEVEL).upper()

# Log rotation configuration: prevent log files from growing infinitely
# Regular logs (api.log): Size-based rotation with limited retention
# Default: 10MB per file, keep 5 backup files (50MB total per log file)
# Can be overridden via environment variables LOG_MAX_BYTES and LOG_BACKUP_COUNT
LOG_MAX_BYTES = int(os.getenv("LOG_MAX_BYTES", "10485760"))  # 10MB in bytes (10 * 1024 * 1024)
LOG_BACKUP_COUNT = int(os.getenv("LOG_BACKUP_COUNT", "5"))  # Keep 5 backup files

# Compliance logs (compliance.log): Time-based rotation with long retention for legal compliance
# CRITICAL: Compliance logs must be retained per legal requirements (e.g., 10 years for tax/commercial law)
# These logs are NEVER automatically deleted - only rotated by time to prevent single-file growth
# Default: Daily rotation, keep ALL backups (backupCount=0 means unlimited retention)
# Can be overridden via environment variables:
#   COMPLIANCE_LOG_WHEN: 'D' (daily), 'W' (weekly), 'M' (monthly) - default: 'D'
#   COMPLIANCE_LOG_BACKUP_COUNT: Number of backup files to keep (0 = keep all, default: 0)
#   COMPLIANCE_LOG_INTERVAL: Rotation interval (default: 1, meaning 1 day/week/month based on 'when')
COMPLIANCE_LOG_WHEN = os.getenv("COMPLIANCE_LOG_WHEN", "D")  # Daily rotation
COMPLIANCE_LOG_INTERVAL = int(os.getenv("COMPLIANCE_LOG_INTERVAL", "1"))  # Every 1 day
# backupCount=0 means keep ALL rotated files (no automatic deletion)
# Set to a number if you want to limit (e.g., 3650 for ~10 years of daily logs)
COMPLIANCE_LOG_BACKUP_COUNT = int(os.getenv("COMPLIANCE_LOG_BACKUP_COUNT", "0"))  # 0 = keep all

# Determine logs directory: use LOG_DIR env var if set, otherwise use /app/logs if it exists,
# otherwise fall back to calculated path relative to this file
# This allows Docker containers to use /app/logs (mounted volume) while local dev uses relative path
if os.getenv("LOG_DIR"):
    LOGS_DIR = os.getenv("LOG_DIR")
elif os.path.exists("/app/logs"):
    LOGS_DIR = "/app/logs"
else:
    LOGS_DIR = os.path.join(os.path.dirname(os.path.dirname(os.path.dirname(__file__))), "logs")

API_LOG_PATH = os.path.join(LOGS_DIR, "api.log")
AUDIT_COMPLIANCE_LOG_PATH = os.path.join(LOGS_DIR, "audit-compliance.log")
FINANCIAL_COMPLIANCE_LOG_PATH = os.path.join(LOGS_DIR, "financial-compliance.log")

# Create logs directory if it doesn't exist, with proper permissions
# Use mode 0o777 to ensure all users can write (needed for Docker containers with different users)
try:
    os.makedirs(LOGS_DIR, mode=0o777, exist_ok=True)
except (OSError, PermissionError):
    # If we can't create the directory, we'll fall back to console-only logging
    # This prevents import failures when services don't have write permissions
    pass

# Helper function to check if we can write to a file path
def can_write_to_file(filepath: str) -> bool:
    """
    Check if we have write permissions to a file path.
    Returns True if we can write, False otherwise.
    """
    try:
        # Check if directory exists and is writable
        dir_path = os.path.dirname(filepath)
        if not os.path.exists(dir_path):
            return False
        
        # Try to open the file for writing (or create it if it doesn't exist)
        # Use 'a' mode to append (won't truncate existing files)
        test_file = os.path.join(dir_path, '.write_test')
        try:
            with open(test_file, 'w') as f:
                f.write('test')
            os.remove(test_file)
            return True
        except (OSError, PermissionError):
            return False
    except (OSError, PermissionError):
        return False

# Check if we can write to log files before including them in the config
# This prevents permission errors during logging setup
CAN_WRITE_API_LOG = can_write_to_file(API_LOG_PATH)
CAN_WRITE_COMPLIANCE_LOG = can_write_to_file(AUDIT_COMPLIANCE_LOG_PATH)

# Create sensitive data filter instance
sensitive_filter = SensitiveDataFilter() # Keep the filter instance

# Build handlers dictionary dynamically based on what we can write to
handlers_config = {
    "console": {
        "class": "logging.StreamHandler",
        "level": LOG_LEVEL,
        "formatter": "json",
        "filters": ["request_id", "sensitive_data"],
        "stream": sys.stdout,
    },
}

# Only add file handlers if we can write to the files
if CAN_WRITE_API_LOG:
    handlers_config["api_file"] = {
        "class": "logging.handlers.RotatingFileHandler",
        "level": "INFO", # Log INFO and above to file as per original main.py
        "formatter": "json",
        "filters": ["sensitive_data"], # Apply filter to handler
        "filename": API_LOG_PATH,
        "mode": "a",
        "encoding": "utf-8",
        "maxBytes": LOG_MAX_BYTES,  # Rotate when file reaches this size (default: 10MB)
        "backupCount": LOG_BACKUP_COUNT,  # Keep this many backup files (default: 5)
    }

# Compliance log handlers are configured by setup_compliance_logging.py (called from main.py startup).
# The compliance.audit and compliance.financial loggers are declared in the dictConfig below as
# propagate=False so they don't double-log to root, but their file handlers are added by
# setup_compliance_logging() which creates TimedRotatingFileHandlers for each stream.
# This approach avoids dictConfig limitations around TimedRotatingFileHandler backupCount=0.

# Build logger handlers list based on available file handlers
# Default to console-only if file handlers aren't available
default_handlers = ["console"]
if CAN_WRITE_API_LOG:
    default_handlers.append("api_file")

LOGGING_CONFIG = {
    "version": 1,
    "disable_existing_loggers": False, # Keep this False initially to avoid disabling logs unexpectedly
    "formatters": {
        "json": {
            # Use the standard jsonlogger formatter directly
            "()": "pythonjsonlogger.jsonlogger.JsonFormatter",
            "format": "%(asctime)s %(name)s %(levelname)s %(message)s",
            "rename_fields": {
                "asctime": "timestamp",
                "levelname": "level"
                },
        },
        "compliance_json": {
                # Use the standard jsonlogger formatter directly
            "()": "pythonjsonlogger.jsonlogger.JsonFormatter",
            "format": "%(message)s", # Only the message for compliance
            },
            "simple": { # Keep a simple formatter for potential debugging if needed
                "format": "%(asctime)s - %(name)s - %(levelname)s - %(message)s",
            },
        },
        "filters": {
            "sensitive_data": {
                "()": SensitiveDataFilter,
            },
            "request_id": {
                "()": RequestIdLogFilter,
            },
            "warning_and_above": {
                "()": "logging.Filter",
                "name": "",
            },
        },
        "handlers": handlers_config,
        "loggers": {
            # Base backend logger — catches all backend.* modules not explicitly listed
            "backend": {
                "handlers": default_handlers,
                "level": LOG_LEVEL,
                "propagate": False,
            },
            # Compliance loggers — handlers are configured by setup_compliance_logging() in main.py startup.
            # Declaring them here with propagate=False prevents double-logging to root.
            # Streams: audit-compliance.log (2yr/GDPR) and financial-compliance.log (10yr/AO§147).
            "compliance.audit": {
                "handlers": [],  # Handlers added by setup_compliance_logging() at startup
                "level": "INFO",
                "propagate": False,
            },
            "compliance.financial": {
                "handlers": [],  # Handlers added by setup_compliance_logging() at startup
                "level": "INFO",
                "propagate": False,
            },
            # Configure noisy third-party loggers
            "uvicorn": {
                "handlers": default_handlers,
                "level": "WARNING" if IS_PRODUCTION else "INFO",
                "propagate": False,
            },
            "uvicorn.error": {
                "handlers": default_handlers,
                "level": "WARNING" if IS_PRODUCTION else "INFO",
                "propagate": False,
            },
            "uvicorn.access": {
                "handlers": default_handlers,
                "level": "WARNING", # Always suppress verbose access logs
                "propagate": False,
            },
            "httpx": {
                "handlers": default_handlers,
                "level": "WARNING",
                "propagate": False,
            },
            "httpcore": {
                "handlers": default_handlers,
                "level": "WARNING",
                "propagate": False,
            },

            # ── Middleware: suppress per-request logging (errors still flow via code) ──
            "backend.core.api.app.middleware.logging_middleware": {
                "handlers": default_handlers,
                "level": "WARNING",
                "propagate": False,
            },

            # ── Loggers that contain sensitive information — restrict in production ──
            "backend.core.api.app.routes.auth_ws": {
                "handlers": default_handlers,
                "level": "WARNING" if IS_PRODUCTION else "INFO",
                "propagate": False,
            },
            "backend.core.api.app.routes.connection_manager": {
                "handlers": default_handlers,
                "level": "WARNING" if IS_PRODUCTION else "INFO",
                "propagate": False,
            },
            "backend.core.api.app.routes.websockets": {
                "handlers": default_handlers,
                "level": "WARNING" if IS_PRODUCTION else "INFO",
                "propagate": False,
            },
            "backend.core.api.app.services.cache_chat_mixin": {
                "handlers": default_handlers,
                "level": "WARNING" if IS_PRODUCTION else "INFO",
                "propagate": False,
            },
            "backend.core.api.app.utils.encryption": {
                "handlers": default_handlers,
                "level": "WARNING" if IS_PRODUCTION else "INFO",
                "propagate": False,
            },
            "backend.core.api.app.routes.handlers.websocket_handlers": {
                "handlers": default_handlers,
                "level": "WARNING" if IS_PRODUCTION else "INFO",
                "propagate": False,
            },

            # ── Noisy service loggers — restrict in production ──
            "backend.core.api.app.routes.auth": {
                "handlers": default_handlers,
                "level": "WARNING" if IS_PRODUCTION else "INFO",
                "propagate": False,
            },
            "backend.core.api.app.services.s3": {
                "handlers": default_handlers,
                "level": "WARNING" if IS_PRODUCTION else "INFO",
                "propagate": False,
            },
            "backend.core.api.app.services.cache": {
                "handlers": default_handlers,
                "level": "WARNING" if IS_PRODUCTION else "INFO",
                "propagate": False,
            },
            "backend.core.api.app.services.metrics": {
                "handlers": default_handlers,
                "level": "WARNING" if IS_PRODUCTION else "INFO",
                "propagate": False,
            },
            "backend.core.api.app.services.directus": {
                "handlers": default_handlers,
                "level": "WARNING" if IS_PRODUCTION else "INFO",
                "propagate": False,
            },
        },
    "root": {
        # Remove handlers from the root logger.
        # If specific loggers are configured correctly with propagate=False,
        # the root logger shouldn't need to handle their messages directly.
        # It will still act as a fallback for unconfigured loggers if needed,
        # but won't output anything itself unless handlers are added elsewhere.
        "handlers": [],
        "level": LOG_LEVEL,
    },
}

def setup_logging():
    """
    Configures logging using dictConfig.
    
    This function handles permission errors gracefully by:
    1. Checking write permissions before creating file handlers
    2. Falling back to console-only logging if file handlers can't be created
    3. Catching any remaining permission errors during dictConfig setup
    
    This prevents import failures when services don't have write permissions
    to log files (e.g., task-worker service in Docker containers).
    """
    try:
        logging.config.dictConfig(LOGGING_CONFIG)
    except (ValueError, OSError, PermissionError) as e:
        # If we can't configure file handlers, fall back to console-only logging
        # This prevents import failures when services don't have write permissions
        fallback_config = {
            "version": 1,
            "disable_existing_loggers": False,
            "formatters": {
                "json": {
                    "()": "pythonjsonlogger.jsonlogger.JsonFormatter",
                    "format": "%(asctime)s %(name)s %(levelname)s %(message)s",
                    "rename_fields": {
                        "asctime": "timestamp",
                        "levelname": "level"
                    },
                },
            },
            "filters": {
                "sensitive_data": {
                    "()": SensitiveDataFilter,
                },
            },
            "handlers": {
                "console": {
                    "class": "logging.StreamHandler",
                    "level": LOG_LEVEL,
                    "formatter": "json",
                    "filters": ["sensitive_data"],
                    "stream": sys.stdout,
                },
            },
            "loggers": {
                "": {  # Root logger
                    "handlers": ["console"],
                    "level": LOG_LEVEL,
                },
            },
        }
        logging.config.dictConfig(fallback_config)
        
        # Log the fallback to console (this will work since console handler is always available)
        logger = logging.getLogger(__name__)
        logger.warning(
            f"Logging setup: Could not configure file handlers (permission error: {e}). "
            f"Falling back to console-only logging. Log files: API={CAN_WRITE_API_LOG}, "
            f"Compliance={CAN_WRITE_COMPLIANCE_LOG}"
        )
        return
    
    # Filters are applied via the dictConfig structure ('filters' key in handlers)
    # No need to add them manually here unless for very specific cases.

    # The WARNING filter for the logging middleware logger is now handled
    # via dictConfig (key: "backend.core.api.app.middleware.logging_middleware").
    # No manual addFilter needed.

    logger = logging.getLogger(__name__)
    
    # Log configuration status
    if not CAN_WRITE_API_LOG or not CAN_WRITE_COMPLIANCE_LOG:
        logger.warning(
            f"Logging configured with limited file access: "
            f"API log={'enabled' if CAN_WRITE_API_LOG else 'disabled'}, "
            f"Compliance log={'enabled' if CAN_WRITE_COMPLIANCE_LOG else 'disabled'}. "
            f"Using console logging as fallback."
        )
    
    if IS_PRODUCTION:
        logger.warning("Logging configured for PRODUCTION environment - sensitive INFO logs are disabled")
    else:
        logger.info("Logging configured for DEVELOPMENT environment - all log levels enabled")

# Example of how to use the compliance logger
# compliance_logger = logging.getLogger("compliance")
# compliance_logger.info({"event": "user_login", "user_id": "123", "status": "success"})

# Example of how to use the event logger
# event_logger = logging.getLogger("app.events")
# event_logger.info("User registration process started.")
