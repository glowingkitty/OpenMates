import os
import uvicorn
import logging
from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from dotenv import load_dotenv
from contextlib import asynccontextmanager
from slowapi import _rate_limit_exceeded_handler
from slowapi.errors import RateLimitExceeded
from prometheus_client import make_asgi_app
from pythonjsonlogger import jsonlogger

from app.routes import auth, email, invoice, credit_note, settings  # Update settings import
# Service Imports
from app.services.directus import DirectusService
from app.services.cache import CacheService
from app.services.metrics import MetricsService
from app.services.compliance import ComplianceService
from app.services.email_template import EmailTemplateService
from app.utils.encryption import EncryptionService
from app.utils.secrets_manager import SecretsManager  # Add import for SecretManager
from app.services.limiter import limiter

# Middleware & Utils
from app.middleware.logging_middleware import LoggingMiddleware
from app.utils.log_filters import SensitiveDataFilter  # Import the new filter

# Add import for Celery app
from app.tasks.celery_config import app as celery_app

# Import our new compliance logging setup
from app.utils.setup_compliance_logging import setup_compliance_logging

# Import the metrics update task
from app.tasks.user_metrics import periodic_metrics_update, update_active_users_metrics

# Set up structured logging - INFO for console output, WARNING for files
log_level = os.getenv("LOG_LEVEL", "INFO")  # Keep INFO as default for console
logging.basicConfig(level=log_level)
logger = logging.getLogger(__name__)

# Create sensitive data filter instance
sensitive_filter = SensitiveDataFilter()

# Configure JSON logging for the root logger for console output
log_handler = logging.StreamHandler()
log_formatter = jsonlogger.JsonFormatter(
    '%(asctime)s %(name)s %(levelname)s %(message)s',
    rename_fields={
        'asctime': 'timestamp',
        'levelname': 'level'
    }
)
log_handler.setFormatter(log_formatter)
log_handler.addFilter(sensitive_filter)  # Add filter to console handler

# Replace the default handler
root_logger = logging.getLogger()
if root_logger.handlers:
    for handler in root_logger.handlers:
        root_logger.removeHandler(handler)
root_logger.addHandler(log_handler)

# Create logs directory if it doesn't exist
logs_dir = os.path.join(os.path.dirname(__file__), "logs")
os.makedirs(logs_dir, exist_ok=True)

# Add file handler for API logs - ONLY log WARNING and above
api_log_path = os.path.join(logs_dir, "api.log")
api_handler = logging.FileHandler(api_log_path)
api_handler.setFormatter(log_formatter)
api_handler.addFilter(sensitive_filter)  # Add filter to file handler
# More aggressively filter logs for the file handler
api_handler.setLevel(logging.WARNING)  # Only WARNING and above in files
root_logger.addHandler(api_handler)

# Create a special event logger for business events (like invite code checks)
event_logger = logging.getLogger("app.events")
event_logger.propagate = False  # Don't send to root logger
event_handler = logging.FileHandler(api_log_path)
event_handler.setFormatter(log_formatter)
event_handler.addFilter(sensitive_filter)  # Add filter to event file handler
event_handler.setLevel(logging.INFO)  # Allow INFO level for specific events
event_logger.addHandler(event_handler)
# Add console output for events as well
event_console = logging.StreamHandler()
event_console.setFormatter(log_formatter)
event_console.addFilter(sensitive_filter)  # Add filter to event console handler
event_console.setLevel(logging.INFO)
event_logger.addHandler(event_console)

# Set higher log levels only for noisy modules, but leave others at INFO for console
logging.getLogger("uvicorn.access").setLevel(logging.WARNING)  # This one is very noisy
logging.getLogger("httpx").setLevel(logging.WARNING)  # Also quite noisy
logging.getLogger("app.middleware.logging_middleware").setLevel(logging.WARNING)  # Only important middleware logs

# Explicitly set higher log levels for noisy modules, but leave others at INFO for console
logging.getLogger("uvicorn.access").setLevel(logging.WARNING)
logging.getLogger("httpx").setLevel(logging.WARNING)

# Force the middleware logger to never use INFO level
logging.getLogger("app.middleware.logging_middleware").setLevel(logging.WARNING)

# Disable the INFO logs for this specific module so they never get written
log_filter = logging.Filter()
log_filter.filter = lambda record: record.levelno >= logging.WARNING
logging.getLogger("app.middleware.logging_middleware").addFilter(log_filter)

# Configure the compliance logger to use a separate file handler
compliance_logger = logging.getLogger("compliance")
compliance_logger.setLevel(logging.INFO)
compliance_logger.propagate = False  # Don't send to root logger

# Create file handler for compliance logs
compliance_log_path = os.path.join(logs_dir, "compliance.log")
compliance_handler = logging.FileHandler(compliance_log_path)
compliance_formatter = jsonlogger.JsonFormatter('%(message)s')
compliance_handler.setFormatter(compliance_formatter)
compliance_handler.addFilter(sensitive_filter)  # Add filter to compliance handler as well
compliance_logger.addHandler(compliance_handler)

logging.getLogger("app.utils.encryption").setLevel(logging.INFO)
logging.getLogger("app.routes.auth").setLevel(logging.INFO)

# Load environment variables
load_dotenv()

# Check crucial environment variables
DIRECTUS_TOKEN = os.getenv("DIRECTUS_TOKEN")
if not DIRECTUS_TOKEN:
    logger.warning("DIRECTUS_TOKEN environment variable is not set. Authentication with Directus will fail.")

# Services will be initialized within the lifespan context manager
# and stored in app.state

# Create the application instance
app = None

# Define lifespan context manager for startup/shutdown events
@asynccontextmanager
async def lifespan(app: FastAPI):
    # Set up event loop for async background tasks
    import asyncio
    loop = asyncio.get_event_loop()
    app.state.loop = loop
    
    # --- Initialize all services and store in app.state ---
    logger.info("Initializing services...")
    app.state.cache_service = CacheService()
    app.state.metrics_service = MetricsService()
    app.state.compliance_service = ComplianceService()
    app.state.email_template_service = EmailTemplateService()
    
    # Initialize secrets manager with cache
    app.state.secrets_manager = SecretsManager(cache_service=app.state.cache_service)
    logger.info("Initializing secrets manager...")
    await app.state.secrets_manager.initialize()
    
    # Encryption service depends on cache
    app.state.encryption_service = EncryptionService(cache_service=app.state.cache_service)
    
    # Directus service depends on cache and encryption
    app.state.directus_service = DirectusService(
        cache_service=app.state.cache_service, 
        encryption_service=app.state.encryption_service
    )
    logger.info("Services instantiated.")
    
    # --- Perform async initializations ---
    try:
        # Initialize encryption service (validates token, ensures keys)
        logger.info("Initializing encryption service...")
        await app.state.encryption_service.initialize()
        logger.info("Ensuring encryption keys exist...")
        await app.state.encryption_service.ensure_keys_exist()
        logger.info("Encryption service initialized successfully.")
        
        # Initialize metrics (depends on directus service)
        logger.info("Initializing metrics...")
        await app.state.metrics_service.initialize_metrics(app.state.directus_service)
        logger.info("Metrics service initialized successfully.")
        
    except Exception as e:
        logger.critical(f"Failed during critical service initialization: {str(e)}", exc_info=True)
        # Depending on the severity, might want to raise exception to stop startup
        # raise e 
    
    # --- Other startup logic ---
    logger.info("Preloading invite codes into cache...")
    try:
        # Pass app.state to preload_invite_codes
        await preload_invite_codes(app.state) 
        logger.info("Successfully preloaded invite codes into cache")
        
        # Run initial metrics update, passing services from app.state
        await update_active_users_metrics(
            directus_service=app.state.directus_service, 
            metrics_service=app.state.metrics_service
        )
        
        # Start the background task for periodic metrics updates, passing services from app.state
        # We use create_task to avoid blocking startup
        app.state.metrics_task = asyncio.create_task(periodic_metrics_update(
            directus_service=app.state.directus_service, 
            metrics_service=app.state.metrics_service
        ))
        logger.info("Started periodic metrics update task")
    except Exception as e:
        logger.error(f"Failed to initialize: {str(e)}", exc_info=True)
    
    yield  # This is where FastAPI serves requests
    
    # Shutdown logic
    logger.info("Shutting down application...")
    
    # Clean up background tasks
    if hasattr(app.state, 'metrics_task'):
        app.state.metrics_task.cancel()
        try:
            await app.state.metrics_task
        except asyncio.CancelledError:
            logger.info("Metrics update task cancelled")
            
    # Close encryption service client
    if hasattr(app.state, 'encryption_service'):
        await app.state.encryption_service.close()

# Create FastAPI application with lifespan
def create_app() -> FastAPI:
    app = FastAPI(
        title="OpenMates API",
        description="API for OpenMates platform",
        version="0.1.0",
        lifespan=lifespan,
        docs_url=None,  # Disable default docs
        redoc_url=None  # Disable ReDoc
    )

    # Set up compliance logging
    setup_compliance_logging()

    # Create metrics endpoint
    metrics_app = make_asgi_app()
    app.mount("/metrics", metrics_app)

    # Add rate limiting exception handler
    app.state.limiter = limiter
    app.add_exception_handler(RateLimitExceeded, _rate_limit_exceeded_handler)

    # Add logging middleware (pass metrics service from app.state if needed, or remove if unused)
    # Assuming LoggingMiddleware doesn't actually need metrics_service passed here
    app.add_middleware(LoggingMiddleware) 
    # If it does need it, it should fetch it via request.app.state inside the middleware

    # Configure CORS with proper origin restrictions
    is_dev = os.getenv("SERVER_ENVIRONMENT", "development") == "development"
    allowed_origins = [
        os.getenv("FRONTEND_URL", "http://localhost:5174") if is_dev else
        os.getenv("PRODUCTION_URL", "https://app.openmates.org")
    ]
    logger.debug(f"Allowed origins: {allowed_origins}")

    # Make allowed_origins accessible outside this module
    # This enables auth endpoints to validate origins
    app.state.allowed_origins = allowed_origins

    # Configure CORS with the allowed origins
    app.add_middleware(
        CORSMiddleware,
        allow_origins=allowed_origins,
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )

    # Include routers
    app.include_router(auth.router)
    app.include_router(email.router)
    app.include_router(invoice.router)
    app.include_router(credit_note.router)
    app.include_router(settings.router)

    # Health check endpoint with rate limiting
    @app.get("/health")
    @limiter.limit("60/minute")
    async def health_check(request: Request):
        return {"status": "healthy"}

    return app

async def preload_invite_codes(app_state): # Accepts app_state now
    """Load all invite codes into cache for faster lookup"""
    directus_service = app_state.directus_service 
    cache_service = app_state.cache_service # Also need cache service
    
    all_codes = await directus_service.get_all_invite_codes()
    if not all_codes:
        logger.warning("No invite codes found to preload")
        return
    
    imported_count = 0
    skipped_count = 0
    
    # Cache each invite code with its data
    for code_data in all_codes:
        code = code_data.get("code")
        if code:
            # Use the invite code as the key
            cache_key = f"invite_code:{code}"
            
            # Check if code already exists in cache
            existing_data = await cache_service.get(cache_key)
            if existing_data is None:
                # Only add to cache if it doesn't already exist
                await cache_service.set(cache_key, code_data)
                imported_count += 1
            else:
                skipped_count += 1
    
    logger.info(f"Preloaded {imported_count} new invite codes into cache (skipped {skipped_count} existing codes)")

# Create the application at module level to make it available for import
app = create_app()

# Make Celery app accessible through the main module
__all__ = ['app', 'celery_app']

if __name__ == "__main__":
    port = int(os.getenv("REST_API_PORT", "8000"))
    # Configure uvicorn with aggressive log filtering
    uvicorn.run(
        "main:app",
        host="0.0.0.0",
        port=port,
        reload=True,
        log_level="error",  # Only log errors for uvicorn
        access_log=False,   # Disable access logs completely
        use_colors=False    # Disable colors for cleaner logs
    )
