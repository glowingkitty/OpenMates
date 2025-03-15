import logging
import os
from pythonjsonlogger import jsonlogger
from app.utils.log_filters import SensitiveDataFilter

def setup_worker_logging():
    """
    Configure consistent logging for Celery workers with sensitive data filtering.
    Should be called at the start of each worker process.
    """
    # Create sensitive data filter instance
    sensitive_filter = SensitiveDataFilter()
    
    # Configure handlers with JSON formatter
    console_handler = logging.StreamHandler()
    formatter = jsonlogger.JsonFormatter(
        '%(asctime)s %(name)s %(levelname)s %(message)s',
        rename_fields={
            'asctime': 'timestamp',
            'levelname': 'level'
        }
    )
    console_handler.setFormatter(formatter)
    console_handler.addFilter(sensitive_filter)
    
    # Get the root logger and apply settings
    root_logger = logging.getLogger()
    
    # Remove existing handlers and add our configured one
    for handler in root_logger.handlers:
        root_logger.removeHandler(handler)
    root_logger.addHandler(console_handler)
    
    # Set level based on environment variable or default to INFO
    log_level = os.getenv("LOG_LEVEL", "INFO")
    root_logger.setLevel(log_level)
    
    # Make sure all modules use the filter
    for logger_name in logging.root.manager.loggerDict:
        module_logger = logging.getLogger(logger_name)
        if not module_logger.filters or not any(isinstance(f, SensitiveDataFilter) for f in module_logger.filters):
            module_logger.addFilter(sensitive_filter)
