from celery import Celery
import os
import logging

# Set up logging
logger = logging.getLogger(__name__)

# Get Redis password from environment variable
redis_password = os.getenv('REDIS_PASSWORD', 'openmates_cache')

# Build proper authenticated connection URLs
broker_url = os.getenv('CELERY_BROKER_URL', f'redis://default:{redis_password}@cache:6379/0')
result_backend = os.getenv('CELERY_RESULT_BACKEND', f'redis://default:{redis_password}@cache:6379/0')

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

# Set task routes for organizing tasks
app.conf.task_routes = {
    'app.tasks.email_tasks.*': {'queue': 'email'},
    # Add other task routes as needed
}

# For backward compatibility
celery_app = app
