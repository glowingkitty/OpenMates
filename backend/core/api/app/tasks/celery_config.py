from celery import Celery, signals
from kombu import Queue
import os
import logging
import sys
from backend.core.api.app.utils.log_filters import SensitiveDataFilter
# Remove the unused import below, as this file defines its own setup_celery_logging
# from backend.core.api.app.utils.setup_logging import setup_worker_logging
from pythonjsonlogger import jsonlogger # Import the JSON formatter
# Set up logging with a direct approach for Celery
logger = logging.getLogger(__name__)

# --- Centralized Task Configuration ---
# Define task groups, their modules, and associated queues in one place.
# This simplifies adding new task types.
TASK_CONFIG = [
    {'name': 'email',       'module': 'backend.core.api.app.tasks.email_tasks'},
    {'name': 'user_init',   'module': 'backend.core.api.app.tasks.user_cache_tasks'},
    {'name': 'persistence', 'module': 'backend.core.api.app.tasks.persistence_tasks'},
    {'name': 'app_ai',      'module': 'backend.apps.ai.tasks'},
    # Add new task configurations here, e.g.:
    # {'name': 'new_queue', 'module': 'backend.core.api.app.tasks.new_tasks'}, # Example updated
]


# Force immediate logger configuration for Celery
def setup_celery_logging():
    """Configure logging for Celery workers directly."""
    # Create a handler that writes to stdout
    handler = logging.StreamHandler(sys.stdout)
    # Use JSON formatter to match API logs
    formatter = jsonlogger.JsonFormatter(
        '%(asctime)s %(name)s %(levelname)s %(message)s',
        rename_fields={
            'asctime': 'timestamp',
            'levelname': 'level'
        }
    )
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
    
    # Configure key application loggers directly
    # Start with base loggers
    loggers_to_configure = [
        'celery',
        'app', # Generic app logger
        'app.services', # Services used by the core app or tasks
        'app.tasks', # General core app tasks
        'backend.apps', # Catch-all for logs from any module under backend.apps.*
    ]
    # Add loggers for specific task modules defined in TASK_CONFIG
    # These will get specific handling; other backend.apps.* logs will be caught by 'backend.apps'
    loggers_to_configure.extend([config['module'] for config in TASK_CONFIG])

    for logger_name in loggers_to_configure:
        module_logger = logging.getLogger(logger_name)
        # Ensure handler is attached
        if handler not in module_logger.handlers: # Avoid adding multiple times
            module_logger.addHandler(handler)
        # Ensure filter is attached
        if sensitive_filter not in module_logger.filters:
            module_logger.addFilter(sensitive_filter)
        # Set level (inherit from root or set explicitly)
        module_logger.setLevel(log_level) # Match root logger level
        # Prevent duplicate logs by stopping propagation to root
        module_logger.propagate = False
    
    logger.info("Celery logging configured with JSON formatter, sensitive data filtering, and direct handler attachment")

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



# Dynamically generate configuration values from TASK_CONFIG
include_modules = [config['module'] for config in TASK_CONFIG]
task_queues = tuple(Queue(config['name'], exchange=config['name'], routing_key=config['name']) for config in TASK_CONFIG)


# Create Celery app
app = Celery(
    'openmates',
    broker=broker_url,
    backend=result_backend,
    include=include_modules # Dynamically include task modules
)

# Configure Celery
app.conf.update(
    task_queues=task_queues, # Dynamically set queues
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
    logger.info("Worker process initialized with JSON logging and sensitive data filtering")

# Dynamically generate task routes from TASK_CONFIG
app.conf.task_routes = {
    f"{config['module']}.*": {'queue': config['name']} for config in TASK_CONFIG
}
