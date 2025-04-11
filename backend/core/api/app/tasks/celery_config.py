from celery import Celery, signals
import os
import logging
import sys
from app.utils.log_filters import SensitiveDataFilter
from app.utils.setup_logging import setup_worker_logging

# Set up logging with a direct approach for Celery
logger = logging.getLogger(__name__)

# Force immediate logger configuration for Celery
def setup_celery_logging():
    """Configure logging for Celery workers directly."""
    # Create a handler that writes to stdout
    handler = logging.StreamHandler(sys.stdout)
    formatter = logging.Formatter('%(asctime)s [%(levelname)s] %(name)s: %(message)s')
    handler.setFormatter(formatter)
    
    # Set log level from environment or default to INFO
    log_level = os.getenv('LOG_LEVEL', 'INFO')
    
    # Configure root logger with our handler
    root_logger = logging.getLogger()
    root_logger.setLevel(log_level)
    
    # Remove existing handlers to avoid duplicates
    for h in root_logger.handlers[:]:
        root_logger.removeHandler(h)
    
    # Add our handler
    root_logger.addHandler(handler)
    
    # Add sensitive data filter to root logger
    sensitive_filter = SensitiveDataFilter()
    root_logger.addFilter(sensitive_filter)
    
    # Also add filter to key loggers
    for logger_name in ['celery', 'app', 'app.services', 'app.tasks']:
        module_logger = logging.getLogger(logger_name)
        module_logger.addFilter(sensitive_filter)
    
    logger.info("Celery logging configured with sensitive data filtering")

# Run the setup immediately
setup_celery_logging()

# Get Redis password from environment variable
DRAGONFLY_PASSWORD = os.getenv('DRAGONFLY_PASSWORD')

# Build proper authenticated connection URLs
broker_url = os.getenv('CELERY_BROKER_URL', f'redis://default:{DRAGONFLY_PASSWORD}@cache:6379/0')
result_backend = os.getenv('CELERY_RESULT_BACKEND', f'redis://default:{DRAGONFLY_PASSWORD}@cache:6379/0')

# Log the connection information
logger.info(f"Celery broker URL: {broker_url}")
logger.info(f"Celery result backend: {result_backend}")

# Explicitly configure Redis backend settings
broker_connection_retry_on_startup = True
broker_connection_max_retries = 10
redis_socket_timeout = 15  # Increased from 5
redis_socket_connect_timeout = 15  # Increased from 5
redis_retry_on_timeout = True

# Create Celery app
app = Celery(
    'openmates',
    broker=broker_url,
    backend=result_backend,
    include=['app.tasks.email_tasks']  # Add other task modules here as they're created
)

# Configure Celery
app.conf.update(
    result_expires=3600,  # Results expire after 1 hour
    task_serializer='json',
    accept_content=['json'],
    result_serializer='json',
    timezone='UTC',
    enable_utc=True,
    broker_connection_retry_on_startup=broker_connection_retry_on_startup,
    broker_connection_max_retries=broker_connection_max_retries,
    broker_transport_options={
        'socket_timeout': redis_socket_timeout,
        'socket_connect_timeout': redis_socket_connect_timeout,
        'retry_on_timeout': redis_retry_on_timeout,
    },
    redis_socket_timeout=redis_socket_timeout,
    redis_socket_connect_timeout=redis_socket_connect_timeout,
    redis_retry_on_timeout=redis_retry_on_timeout,
)

# Configure logging on worker start as well
@signals.worker_process_init.connect
def init_worker_process(*args, **kwargs):
    """
    Set up consistent logging across Celery worker processes.
    """
    setup_celery_logging()
    logger.info("Worker process initialized with sensitive data filtering")

# Set task routes for organizing tasks
app.conf.task_routes = {
    'app.tasks.email_tasks.*': {'queue': 'email'},
    # Add other task routes as needed
}

# For backward compatibility
celery_app = app
