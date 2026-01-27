from celery import Celery, signals
from kombu import Queue
import os
import logging
import sys
import importlib
from typing import Optional
from urllib.parse import quote
import asyncio
from datetime import timedelta
from celery.schedules import crontab

from backend.core.api.app.utils.log_filters import SensitiveDataFilter
from pythonjsonlogger import jsonlogger  # Import the JSON formatter
from backend.core.api.app.utils.config_manager import ConfigManager
from backend.core.api.app.services.invoiceninja.invoiceninja import InvoiceNinjaService
from backend.core.api.app.services.pdf.invoice import InvoiceTemplateService
from backend.core.api.app.utils.secrets_manager import SecretsManager

# Set up logging with a direct approach for Celery
logger = logging.getLogger(__name__)

# Global variable to hold the ConfigManager instance for the worker process
# Will be initialized lazily on first access via ConfigManager singleton pattern
# Use a class to make it a lazy property that initializes on first access
class _LazyConfigManager:
    """Lazy wrapper for ConfigManager that initializes on first access."""
    _instance: Optional[ConfigManager] = None
    
    def __getattr__(self, name):
        """Lazy initialization - create ConfigManager on first access."""
        if self._instance is None:
            self._instance = ConfigManager()  # Singleton pattern - only creates one instance per process
            logger.info(f"ConfigManager initialized on first access. Found {len(self._instance.get_provider_configs())} provider configurations.")
        return getattr(self._instance, name)
    
    def __bool__(self):
        """Support 'if config_manager:' checks."""
        if self._instance is None:
            self._instance = ConfigManager()
            logger.info(f"ConfigManager initialized on first access. Found {len(self._instance.get_provider_configs())} provider configurations.")
        return bool(self._instance)

# Create lazy config_manager that initializes on first access
config_manager = _LazyConfigManager()

invoice_ninja_service: Optional[InvoiceNinjaService] = None
invoice_template_service: Optional[InvoiceTemplateService] = None


# --- Centralized Task Configuration ---
# Define task groups, their modules, and associated queues in one place.
# This simplifies adding new task types.
TASK_CONFIG = [
    {'name': 'email',       'module': 'backend.core.api.app.tasks.email_tasks'},
    {'name': 'user_init',   'module': 'backend.core.api.app.tasks.user_cache_tasks'},
    {'name': 'persistence', 'module': 'backend.core.api.app.tasks.persistence_tasks'},
    {'name': 'app_ai',      'module': 'backend.apps.ai.tasks'},
    {'name': 'app_web',     'module': 'backend.apps.web.tasks'},  # Web app tasks (to be implemented)
    {'name': 'health_check', 'module': 'backend.core.api.app.tasks.health_check_tasks'},  # Health check tasks
    {'name': 'usage',       'module': 'backend.core.api.app.tasks.usage_archive_tasks'},  # Usage archive tasks
    {'name': 'app_images',  'module': 'backend.apps.images.tasks'},  # Image generation tasks
    {'name': 'server_stats', 'module': 'backend.core.api.app.tasks.server_stats_tasks'},  # Server stats
    {'name': 'demo',        'module': 'backend.core.api.app.tasks.demo_tasks'},  # Demo chat tasks
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
    # Convert string log level to logging constant (e.g., 'info' -> logging.INFO)
    log_level_str = os.getenv('LOG_LEVEL', 'INFO').upper()
    log_level = getattr(logging, log_level_str, logging.INFO)
    
    # Configure root logger with our handler
    root_logger = logging.getLogger()
    root_logger.setLevel(log_level)
    
    # Give our handler a unique name to avoid adding it multiple times.
    handler.name = "json_stdout_handler"
    
    # Avoid adding duplicate handlers.
    if not any(h.name == handler.name for h in root_logger.handlers):
        # Do not remove other handlers, as it can interfere with Celery's internal logging.
        # Just add our handler to the root logger.
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
        'backend.core', # Cover all core logs, including ConfigManager
        'backend.apps', # Catch-all for logs from any module under backend.apps.*
        'httpx', # HTTP client library
        'httpcore', # HTTP core library (used by httpx)
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
        # Use the same log_level constant that was set for root logger
        module_logger.setLevel(log_level) # Match root logger level
        # Prevent duplicate logs by stopping propagation to root
        module_logger.propagate = False
    
    logger.info("Celery logging configured with JSON formatter, sensitive data filtering, and direct handler attachment")

# Run the setup immediately
setup_celery_logging()

# Get Redis password from environment variable and ensure it's URL-encoded for connection strings.
raw_password = os.getenv('DRAGONFLY_PASSWORD')
encoded_password = quote(raw_password) if raw_password else ''

# Build proper authenticated connection URLs
# Use the encoded password in the default URL to handle special characters safely.
broker_url = os.getenv('CELERY_BROKER_URL', f'redis://default:{encoded_password}@cache:6379/0')
result_backend = os.getenv('CELERY_RESULT_BACKEND', f'redis://default:{encoded_password}@cache:6379/0')

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

# =================================================================
# WORKER-SPECIFIC QUEUE FILTERING
# =================================================================
# When running as a worker, CELERY_QUEUES env var specifies which queues
# this worker should consume from. We filter task_queues accordingly.
#
# This fixes a critical bug where workers were consuming from ALL queues
# despite --queues flag being set. By filtering at the config level,
# workers only ever know about their designated queues.
#
# For API/scheduler processes, we need ALL queues for routing tasks.

worker_queues_env = os.getenv('CELERY_QUEUES', '')
if worker_queues_env:
    # Worker mode: Only include designated queues
    designated_queue_names = {q.strip() for q in worker_queues_env.split(',')}
    task_queues = tuple(
        Queue(config['name'], exchange=config['name'], routing_key=config['name'])
        for config in TASK_CONFIG
        if config['name'] in designated_queue_names
    )
    logger.info(f"[WORKER_QUEUE_FILTER] Worker mode - filtered queues to: {[q.name for q in task_queues]}")
else:
    # API/scheduler mode: Include all queues for routing
    task_queues = tuple(
        Queue(config['name'], exchange=config['name'], routing_key=config['name'])
        for config in TASK_CONFIG
    )
    logger.info(f"[WORKER_QUEUE_FILTER] API/scheduler mode - all queues available for routing: {[q.name for q in task_queues]}")

# Create Celery app
app = Celery(
    'openmates',
    broker=broker_url,
    backend=result_backend,
    include=include_modules # Dynamically include task modules
)

# Explicitly import task modules to ensure tasks are registered
# This is important for tasks with custom names that might not be auto-discovered
for module_name in include_modules:
    try:
        importlib.import_module(module_name)
        logger.debug(f"Successfully imported task module: {module_name}")
    except Exception as e:
        logger.warning(f"Failed to import task module {module_name}: {e}")

# Configure Celery
app.conf.update(
    task_queues=task_queues, # Dynamically set queues
    # CRITICAL: Set task_default_queue to None to prevent fallback to default queue
    # This ensures tasks only go to explicitly routed queues
    task_default_queue=None,
    task_default_exchange=None,
    task_default_routing_key=None,
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
    
    # ===========================================================================
    # RELIABILITY SETTINGS - Ensures tasks are not lost
    # ===========================================================================
    
    # task_acks_late: Acknowledge tasks AFTER execution completes (not before)
    # This prevents task loss if worker crashes during execution
    # The task will be re-queued if the worker dies before acknowledging
    task_acks_late=True,
    
    # task_reject_on_worker_lost: Re-queue tasks if worker process dies abruptly
    # (e.g., SIGKILL, OOM kill, or container restart)
    # Combined with task_acks_late, ensures tasks are never lost
    # WARNING: Can cause message loops for tasks that always fail - ensure proper retry limits
    task_reject_on_worker_lost=True,
    
    # task_acks_on_failure_or_timeout: When True (default), tasks are ACKed even on failure
    # Set to False to re-queue failed tasks (useful with dead-letter queues)
    # We keep True because we handle retries explicitly per-task with max_retries
    task_acks_on_failure_or_timeout=True,
    
    # task_track_started: Track when tasks start execution (enables STARTED state)
    # Useful for monitoring - shows tasks that are currently being executed
    task_track_started=True,
    
    # worker_prefetch_multiplier: Number of messages to prefetch per worker process
    # Set to 1 for fair task distribution (prevents one worker from hogging tasks)
    # Important for long-running tasks like AI processing
    worker_prefetch_multiplier=1,
    
    # task_time_limit: Hard time limit in seconds (worker will be killed)
    # task_soft_time_limit: Soft time limit (raises SoftTimeLimitExceeded exception)
    # These are set per-task via decorators for more control
    
    # task_ignore_result: Whether to store task results
    # We want results for tracking and debugging
    task_ignore_result=False,
)

def _worker_needs_invoice_services():
    """
    Check if this worker needs InvoiceNinjaService and InvoiceTemplateService.
    These services are only needed for workers that handle email, user_init, or persistence queues.
    They are NOT needed for app-specific workers (app_ai, app_web, etc.).
    """
    # Get the queues this worker is consuming from environment or command line
    # Workers are started with --queues argument in docker-compose
    worker_queues_str = os.getenv('CELERY_QUEUES', '')
    if not worker_queues_str:
        # Try to get from command line arguments if available
        import sys
        for i, arg in enumerate(sys.argv):
            if arg == '--queues' and i + 1 < len(sys.argv):
                worker_queues_str = sys.argv[i + 1]
                break
    
    if worker_queues_str:
        worker_queues = [q.strip() for q in worker_queues_str.split(',')]
        # Invoice services are only needed for these queues
        queues_needing_invoice_services = {'email', 'user_init', 'persistence'}
        return bool(set(worker_queues) & queues_needing_invoice_services)
    
    # Default: assume invoice services are needed if we can't determine queues
    # This is safer than skipping initialization
    logger.warning("Could not determine worker queues, initializing invoice services by default")
    return True

async def initialize_services():
    """
    Asynchronously initialize all required services for a worker.
    
    Only initializes services that are needed at worker startup.
    For app workers (app_ai, app_web), services are initialized per-task as needed,
    which is more memory efficient since SecretsManager is now a singleton per process.
    """
    global invoice_ninja_service, invoice_template_service

    # Only initialize services for task-worker that handles email/persistence tasks
    # App workers (app_ai, app_web) don't need pre-initialization - tasks create their own
    # SecretsManager instances, which now share the same singleton per process
    if not _worker_needs_invoice_services():
        logger.info("Skipping service initialization - app workers initialize services per-task as needed")
        return

    # Only task-worker needs SecretsManager pre-initialized for invoice services
    # Since SecretsManager is now a singleton, this will be reused by all tasks
    logger.info("Initializing SecretsManager for invoice services...")
    secrets_manager = SecretsManager()
    try:
        await secrets_manager.initialize()
        logger.info("SecretsManager initialized successfully.")

        # Now initialize services that depend on SecretsManager
        if invoice_ninja_service is None:
            logger.info("Initializing InvoiceNinjaService for worker process...")
            try:
                invoice_ninja_service = await InvoiceNinjaService.create(secrets_manager)
                logger.info("InvoiceNinjaService initialized successfully.")
            except Exception:
                logger.exception("Failed to initialize InvoiceNinjaService.")
        else:
            logger.info("InvoiceNinjaService already initialized for this worker process.")

        if invoice_template_service is None:
            logger.info("Initializing InvoiceTemplateService for worker process...")
            try:
                invoice_template_service = await InvoiceTemplateService.create(secrets_manager)
                logger.info("InvoiceTemplateService initialized successfully.")
            except Exception:
                logger.exception("Failed to initialize InvoiceTemplateService.")
        else:
            logger.info("InvoiceTemplateService already initialized for this worker process.")
    finally:
        # CRITICAL: Close the httpx client after initialization is complete.
        # This prevents the singleton SecretsManager from holding a stale client
        # tied to the event loop created by asyncio.run(initialize_services()).
        # Subsequent tasks will create a new client for their own event loops.
        await secrets_manager.aclose()
        logger.info("SecretsManager httpx client closed after worker service initialization.")


# ===========================================================================
# CELERY SIGNAL HANDLERS - Task lifecycle monitoring for reliability
# ===========================================================================
# These signal handlers provide visibility into task processing, ensuring
# we can detect and debug any issues with task routing or execution.

@signals.task_prerun.connect
def task_prerun_handler(task_id, task, args, kwargs, **kw):
    """
    Called immediately before a task is executed.
    Logs task start with routing information for debugging.
    """
    queue = getattr(task.request, 'delivery_info', {}).get('routing_key', 'UNKNOWN_QUEUE')
    worker = getattr(task.request, 'hostname', 'UNKNOWN_WORKER')
    logger.info(
        f"[TASK_LIFECYCLE] TASK_STARTED: task_id={task_id}, "
        f"task_name={task.name}, queue={queue}, worker={worker}"
    )

@signals.task_postrun.connect
def task_postrun_handler(task_id, task, args, kwargs, retval, state, **kw):
    """
    Called after a task has been executed (success or failure).
    Logs task completion with state for monitoring.
    """
    queue = getattr(task.request, 'delivery_info', {}).get('routing_key', 'UNKNOWN_QUEUE')
    worker = getattr(task.request, 'hostname', 'UNKNOWN_WORKER')
    logger.info(
        f"[TASK_LIFECYCLE] TASK_COMPLETED: task_id={task_id}, "
        f"task_name={task.name}, state={state}, queue={queue}, worker={worker}"
    )

@signals.task_failure.connect
def task_failure_handler(task_id, exception, args, kwargs, traceback, einfo, **kw):
    """
    Called when a task fails.
    Logs detailed failure information for debugging and alerting.
    CRITICAL: This helps identify tasks that are failing without being processed.
    """
    sender = kw.get('sender')
    task_name = sender.name if sender else 'UNKNOWN_TASK'
    queue = 'UNKNOWN_QUEUE'
    worker = 'UNKNOWN_WORKER'
    if sender and hasattr(sender, 'request'):
        queue = getattr(sender.request, 'delivery_info', {}).get('routing_key', 'UNKNOWN_QUEUE')
        worker = getattr(sender.request, 'hostname', 'UNKNOWN_WORKER')
    
    logger.error(
        f"[TASK_LIFECYCLE] TASK_FAILED: task_id={task_id}, "
        f"task_name={task_name}, queue={queue}, worker={worker}, "
        f"exception_type={type(exception).__name__}, exception_msg={str(exception)[:200]}"
    )

@signals.task_success.connect
def task_success_handler(sender, result, **kwargs):
    """
    Called when a task completes successfully.
    Logs success for monitoring task throughput.
    """
    task_name = sender.name if sender else 'UNKNOWN_TASK'
    task_id = sender.request.id if sender and hasattr(sender, 'request') else 'UNKNOWN'
    queue = 'UNKNOWN_QUEUE'
    if sender and hasattr(sender, 'request'):
        queue = getattr(sender.request, 'delivery_info', {}).get('routing_key', 'UNKNOWN_QUEUE')
    
    logger.info(
        f"[TASK_LIFECYCLE] TASK_SUCCESS: task_id={task_id}, "
        f"task_name={task_name}, queue={queue}"
    )

@signals.task_rejected.connect
def task_rejected_handler(message, exc, **kwargs):
    """
    Called when a task is rejected (e.g., unknown task, routing failure).
    CRITICAL: This catches tasks that could NOT be processed!
    This is the key signal to detect unrouted or unknown tasks.
    """
    logger.error(
        f"[TASK_LIFECYCLE] TASK_REJECTED: message={message}, "
        f"exception_type={type(exc).__name__}, exception_msg={str(exc)[:200]}. "
        f"This task was NOT processed! Check task routing and worker queues."
    )

@signals.task_revoked.connect
def task_revoked_handler(request, terminated, signum, expired, **kwargs):
    """
    Called when a task is revoked (cancelled).
    Logs revocation for tracking cancelled tasks.
    """
    task_id = request.id if hasattr(request, 'id') else 'UNKNOWN'
    task_name = request.name if hasattr(request, 'name') else 'UNKNOWN'
    logger.warning(
        f"[TASK_LIFECYCLE] TASK_REVOKED: task_id={task_id}, "
        f"task_name={task_name}, terminated={terminated}, "
        f"signum={signum}, expired={expired}"
    )

@signals.task_retry.connect
def task_retry_handler(request, reason, einfo, **kwargs):
    """
    Called when a task is being retried.
    Logs retry attempts for monitoring retry behavior.
    """
    sender = kwargs.get('sender')
    task_name = sender.name if sender else (request.name if hasattr(request, 'name') else 'UNKNOWN')
    task_id = request.id if hasattr(request, 'id') else 'UNKNOWN'
    
    logger.warning(
        f"[TASK_LIFECYCLE] TASK_RETRY: task_id={task_id}, "
        f"task_name={task_name}, reason={str(reason)[:200]}"
    )

@signals.task_unknown.connect
def task_unknown_handler(message, exc, name, id, **kwargs):
    """
    Called when an unknown task is received.
    CRITICAL: This means a task was sent but no worker knows how to execute it!
    This could indicate a misconfiguration or missing task registration.
    """
    logger.error(
        f"[TASK_LIFECYCLE] TASK_UNKNOWN: task_id={id}, "
        f"task_name={name}, exception={exc}. "
        f"CRITICAL: No worker can process this task! Check task registration and routing."
    )


# ===========================================================================
# WORKER QUEUE ENFORCEMENT
# ===========================================================================
# This signal handler ensures workers only consume from their designated queues.
# Despite setting --queues on the command line, Celery workers were consuming from
# ALL queues defined in task_queues. This caused race conditions where multiple
# workers would process the same task from the persistence queue.
#
# The fix: After the worker is ready, cancel consumers for any queues that the
# worker should NOT be consuming from (based on CELERY_QUEUES env var or --queues arg).

def _get_designated_queues() -> set:
    """
    Get the set of queues this worker should consume from.
    Checks CELERY_QUEUES environment variable first, then --queues command line arg.
    """
    # First check environment variable (set in docker-compose)
    worker_queues_str = os.getenv('CELERY_QUEUES', '')
    
    if not worker_queues_str:
        # Try to get from command line arguments
        for i, arg in enumerate(sys.argv):
            if arg == '--queues' and i + 1 < len(sys.argv):
                worker_queues_str = sys.argv[i + 1]
                break
            elif arg.startswith('--queues='):
                worker_queues_str = arg.split('=', 1)[1]
                break
    
    if worker_queues_str:
        return {q.strip() for q in worker_queues_str.split(',')}
    
    # If no queues specified, return empty set (will consume from all - original behavior)
    return set()


@signals.celeryd_after_setup.connect
def enforce_queue_restrictions(sender, instance, **kwargs):
    """
    Called after the worker is set up but before it starts processing tasks.
    Cancels consumers for queues this worker should NOT be consuming from.
    
    This fixes a bug where workers with --queues=app_ai were still consuming from
    ALL queues (email, persistence, etc.) causing race conditions in task processing.
    """
    # Log immediately to confirm signal is firing
    print("[QUEUE_ENFORCEMENT] 🔧 Signal celeryd_after_setup received!")
    logger.info("[QUEUE_ENFORCEMENT] 🔧 Signal celeryd_after_setup received!")
    
    designated_queues = _get_designated_queues()
    
    print(f"[QUEUE_ENFORCEMENT] Designated queues from env/args: {designated_queues}")
    logger.info(f"[QUEUE_ENFORCEMENT] Designated queues from env/args: {designated_queues}")
    
    if not designated_queues:
        logger.info("[QUEUE_ENFORCEMENT] No queue restrictions specified, worker will consume from all declared queues")
        return
    
    logger.info(f"[QUEUE_ENFORCEMENT] Worker designated queues: {designated_queues}")
    
    # Get the list of all declared queues from task_queues config
    all_declared_queues = {q.name for q in app.conf.task_queues} if app.conf.task_queues else set()
    
    print(f"[QUEUE_ENFORCEMENT] All declared queues: {all_declared_queues}")
    logger.info(f"[QUEUE_ENFORCEMENT] All declared queues: {all_declared_queues}")
    
    # Find queues to remove (declared but not designated for this worker)
    queues_to_remove = all_declared_queues - designated_queues
    
    if queues_to_remove:
        print(f"[QUEUE_ENFORCEMENT] Cancelling consumers for non-designated queues: {queues_to_remove}")
        logger.info(f"[QUEUE_ENFORCEMENT] Cancelling consumers for non-designated queues: {queues_to_remove}")
        
        # Cancel consumers for unwanted queues
        # Use the instance (which is the worker) to cancel consumers
        for queue_name in queues_to_remove:
            try:
                # Cancel consumer for this queue on this worker
                instance.app.control.cancel_consumer(queue_name, destination=[instance.hostname])
                print(f"[QUEUE_ENFORCEMENT] ✅ Cancelled consumer for queue '{queue_name}'")
                logger.info(f"[QUEUE_ENFORCEMENT] ✅ Cancelled consumer for queue '{queue_name}'")
            except Exception as e:
                print(f"[QUEUE_ENFORCEMENT] ⚠️ Failed to cancel consumer for queue '{queue_name}': {e}")
                logger.warning(f"[QUEUE_ENFORCEMENT] ⚠️ Failed to cancel consumer for queue '{queue_name}': {e}")
    else:
        logger.info("[QUEUE_ENFORCEMENT] Worker is already subscribed only to designated queues")


# Configure logging on worker start as well
@signals.worker_process_init.connect
def init_worker_process(*args, **kwargs):
    """
    Set up consistent logging and pre-load configurations for Celery worker processes.
    
    Uses lazy initialization for ConfigManager - it will be initialized on first access
    via the singleton pattern. This saves memory if the worker never needs it.
    """
    setup_celery_logging()
    logger.info("Worker process initializing...")

    # Don't initialize ConfigManager here - use lazy initialization
    # ConfigManager uses singleton pattern, so first access will initialize it
    # This saves memory if the worker never needs it (though most workers do)
    # The lazy wrapper will initialize it on first access
    logger.info("ConfigManager will be initialized lazily on first access (singleton pattern)")

    # Only initialize services that are needed at worker startup
    # For app workers, services are initialized per-task as needed
    asyncio.run(initialize_services())

    logger.info("Worker process initialized with JSON logging and sensitive data filtering")

# Dynamically generate task routes from TASK_CONFIG
# Note: Task names can be explicitly set (e.g., "apps.ai.tasks.skill_ask") which may not match module path patterns
# So we need both pattern-based routing and explicit task name routing
# IMPORTANT: Explicit routing must come FIRST to take precedence over pattern-based routing
task_routes = {
    # Explicit routing for tasks with custom names that don't match module patterns
    # These must come first to ensure they take precedence over pattern-based routing
    "apps.ai.tasks.skill_ask": {'queue': 'app_ai'},
    "health_check.check_all_providers": {'queue': 'health_check'},  # Explicit routing for health check task
    "health_check.check_all_apps": {'queue': 'health_check'},  # Explicit routing for app health check task
    # Email tasks use custom names like "app.tasks.email_tasks.*" instead of full module paths
    # This pattern ensures all email tasks (verification, cleanup, notifications, etc.) route correctly
    "app.tasks.email_tasks.*": {'queue': 'email'},
    # Persistence tasks use custom names like "app.tasks.persistence_tasks.*" instead of full module paths
    # This pattern ensures all persistence tasks (user messages, chat metadata, AI responses, etc.) route correctly
    "app.tasks.persistence_tasks.*": {'queue': 'persistence'},
    # Demo tasks use custom names like "demo.*"
    "demo.*": {'queue': 'demo'},
    # Add other explicitly named tasks here as needed
}

# Add pattern-based routing AFTER explicit routing
# Pattern-based routing will only apply to tasks that don't have explicit routing
task_routes.update({
    f"{config['module']}.*": {'queue': config['name']} for config in TASK_CONFIG
})

app.conf.task_routes = task_routes

# Configure Celery Beat schedule for periodic tasks

# Health check runs every 5 minutes (for providers without health endpoints)
# Providers with health endpoints can be checked more frequently (1 minute) in the future
# IMPORTANT: Explicitly specify queue in Beat schedule to ensure tasks go to task-worker
# ===========================================================================
# TASK ROUTING VALIDATION HELPER
# ===========================================================================
# Helper function to validate that tasks are sent to the correct queue.
# This prevents silent failures where tasks are sent but never processed.

# Build a mapping of task name patterns to queues for validation
_TASK_QUEUE_MAPPING = {}
for config in TASK_CONFIG:
    queue_name = config['name']
    module_prefix = config['module']
    _TASK_QUEUE_MAPPING[module_prefix] = queue_name

# Add explicit task routes for custom-named tasks
# This comprehensive list ensures all tasks have known routing
_EXPLICIT_TASK_ROUTES = {
    # AI App tasks
    "apps.ai.tasks.skill_ask": "app_ai",
    "apps.ai.tasks.rate_limit_followup": "app_ai",
    
    # Health check tasks
    "health_check.check_all_providers": "health_check",
    "health_check.check_all_apps": "health_check",
    "health_check.check_external_services": "health_check",
    
    # Usage archive tasks
    "usage.archive_old_entries": "persistence",
    
    # Server stats tasks
    "server_stats.flush_to_directus": "server_stats",
    
    # Email tasks (custom names starting with app.tasks.email_tasks.*)
    "app.tasks.email_tasks.verification_email_task.generate_and_send_verification_email": "email",
    "app.tasks.email_tasks.account_created_email_task.send_account_created_email": "email",
    "app.tasks.email_tasks.new_device_email_task.send_new_device_email": "email",
    "app.tasks.email_tasks.backup_code_email_task.send_backup_code_used_email": "email",
    "app.tasks.email_tasks.recovery_key_email_task.send_recovery_key_used_email": "email",
    "app.tasks.email_tasks.recovery_email_task.send_account_recovery_email": "email",
    "app.tasks.email_tasks.purchase_confirmation_email_task.process_invoice_and_send_email": "email",
    "app.tasks.email_tasks.credit_note_email_task.process_credit_note_and_send_email": "email",
    "app.tasks.email_tasks.issue_report_email_task.send_issue_report_email": "email",
    "app.tasks.email_tasks.support_contribution_email_task.process_guest_support_contribution_receipt_and_send_email": "email",
    
    # Persistence tasks (custom names starting with app.tasks.persistence_tasks.*)
    "app.tasks.persistence_tasks.persist_chat_title": "persistence",
    "app.tasks.persistence_tasks.persist_user_draft": "persistence",
    "app.tasks.persistence_tasks.persist_new_chat_message": "persistence",
    "app.tasks.persistence_tasks.persist_chat_and_draft_on_logout": "persistence",
    "app.tasks.persistence_tasks.persist_delete_chat": "persistence",
    "app.tasks.persistence_tasks.persist_ai_response_to_directus": "persistence",
    "app.tasks.persistence_tasks.persist_encrypted_chat_metadata": "persistence",
    "app.tasks.persistence_tasks.persist_new_chat_suggestions": "persistence",
    
    # User cache tasks
    "app.tasks.user_cache_tasks.warm_user_cache": "user_init",
    "delete_user_account": "user_init",

    # Demo tasks
    "demo.translate_chat": "demo",
}

def get_expected_queue_for_task(task_name: str) -> Optional[str]:
    """
    Determine the expected queue for a task based on its name.
    
    Returns the queue name if a route is found, None otherwise.
    This is used to validate task routing and detect misconfigured tasks.
    
    Args:
        task_name: The full task name (e.g., 'app.tasks.persistence_tasks.persist_chat_title')
    
    Returns:
        Queue name (e.g., 'persistence') or None if no route found
    """
    # Check explicit routes first
    if task_name in _EXPLICIT_TASK_ROUTES:
        return _EXPLICIT_TASK_ROUTES[task_name]
    
    # Check pattern-based routes
    for route_pattern, route_config in task_routes.items():
        if route_pattern.endswith('.*'):
            prefix = route_pattern[:-2]  # Remove '.*'
            if task_name.startswith(prefix):
                return route_config['queue']
        elif route_pattern == task_name:
            return route_config['queue']
    
    return None


def send_task_validated(
    task_name: str,
    args: Optional[tuple] = None,
    kwargs: Optional[dict] = None,
    queue: Optional[str] = None,
    **options
):
    """
    Send a Celery task with routing validation.
    
    This wrapper ensures that:
    1. Tasks are always sent to a valid queue
    2. If no queue is specified, the expected queue is determined from routing rules
    3. A warning is logged if the specified queue doesn't match the expected queue
    4. An error is logged if no valid queue can be determined
    
    This prevents the silent failure mode where tasks are sent but never processed
    because they end up in a queue that no worker is consuming.
    
    Args:
        task_name: The full task name
        args: Positional arguments for the task
        kwargs: Keyword arguments for the task
        queue: Explicit queue name (optional - will be determined from routes if not provided)
        **options: Additional options for send_task (e.g., countdown, eta)
    
    Returns:
        AsyncResult from send_task
    
    Raises:
        ValueError: If no valid queue can be determined and none is specified
    """
    expected_queue = get_expected_queue_for_task(task_name)
    
    if queue is None:
        # No queue specified - use expected queue from routing
        if expected_queue is None:
            # CRITICAL: Task has no valid route!
            logger.error(
                f"[TASK_ROUTING] UNROUTED_TASK: task_name={task_name}. "
                f"No queue specified and no route found! This task will NOT be processed. "
                f"Add an explicit route in celery_config.py or specify a queue."
            )
            raise ValueError(
                f"Cannot send task '{task_name}': no queue specified and no route found. "
                f"Either specify queue= parameter or add a route in celery_config.py"
            )
        queue = expected_queue
        logger.debug(f"[TASK_ROUTING] Using expected queue '{queue}' for task '{task_name}'")
    elif expected_queue is not None and queue != expected_queue:
        # Queue specified but doesn't match expected - log warning
        logger.warning(
            f"[TASK_ROUTING] QUEUE_MISMATCH: task_name={task_name}, "
            f"specified_queue={queue}, expected_queue={expected_queue}. "
            f"Using specified queue, but verify this is intentional."
        )
    
    # Log the task dispatch for traceability
    logger.info(
        f"[TASK_ROUTING] TASK_DISPATCHED: task_name={task_name}, queue={queue}"
    )
    
    return app.send_task(
        name=task_name,
        args=args,
        kwargs=kwargs,
        queue=queue,
        **options
    )


app.conf.beat_schedule = {
    'health-check-all-providers': {
        'task': 'health_check.check_all_providers',
        'schedule': timedelta(seconds=300),  # 5 minutes (300 seconds)
        'options': {'queue': 'health_check'},  # Explicitly route to health_check queue
    },
    'health-check-all-apps': {
        'task': 'health_check.check_all_apps',
        'schedule': timedelta(seconds=300),  # 5 minutes (300 seconds)
        'options': {'queue': 'health_check'},  # Explicitly route to health_check queue
    },
    'archive-old-usage-entries': {
        'task': 'usage.archive_old_entries',
        'schedule': crontab(hour=2, minute=0, day_of_month=1),  # 1st of month at 2 AM UTC
        'options': {'queue': 'persistence'},  # Route to persistence queue
    },
    'flush-server-stats': {
        'task': 'server_stats.flush_to_directus',
        'schedule': timedelta(seconds=600),  # Every 10 minutes
        'options': {'queue': 'server_stats'},  # Route to server_stats queue
    },
    # 'cleanup-uncompleted-signups': {
    #     'task': 'app.tasks.persistence_tasks.cleanup_uncompleted_signups',
    #     'schedule': crontab(hour=3, minute=0),  # Every day at 3 AM UTC
    #     'options': {'queue': 'persistence'},  # Route to persistence queue
    # },
}
app.conf.timezone = 'UTC'
