import os
import uvicorn
import logging # Keep logging import for potential direct use if needed
from dotenv import load_dotenv

# --- Setup Logging FIRST ---
# Load environment variables early for logging config if needed
load_dotenv()
from backend.core.api.app.utils.setup_logging import setup_logging
setup_logging()
# --- End Logging Setup ---

# Now import other modules that might log
from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from contextlib import asynccontextmanager
from slowapi import _rate_limit_exceeded_handler
from slowapi.errors import RateLimitExceeded
from prometheus_client import make_asgi_app
from pythonjsonlogger import jsonlogger # json is imported by CacheService now for this specific metadata
from uvicorn.middleware.proxy_headers import ProxyHeadersMiddleware
import httpx # For service discovery
from typing import Dict, List # For type hinting

# Make sure the path is correct based on your project structure
from backend.core.api.app.routes import auth, email, invoice, credit_note, settings, payments, websockets
from backend.core.api.app.routes import internal_api # Import the new internal API router
from backend.core.api.app.services.directus import DirectusService
from backend.core.api.app.services.cache import CacheService
from backend.core.api.app.services.metrics import MetricsService
from backend.core.api.app.services.compliance import ComplianceService
from backend.core.api.app.services.email_template import EmailTemplateService
from backend.core.api.app.services.image_safety import ImageSafetyService # Import ImageSafetyService
from backend.core.api.app.services.s3.service import S3UploadService # Import S3UploadService
from backend.core.api.app.services.payment.payment_service import PaymentService # Import PaymentService
from backend.core.api.app.utils.encryption import EncryptionService
from backend.core.api.app.utils.secrets_manager import SecretsManager  # Add import for SecretManager
from backend.core.api.app.services.limiter import limiter
from backend.core.api.app.utils.config_manager import config_manager
from backend.shared.python_schemas.app_metadata_schemas import AppYAML # Moved AppYAML to backend_shared

# Middleware & Utils
from backend.core.api.app.middleware.logging_middleware import LoggingMiddleware
from backend.core.api.app.utils.log_filters import SensitiveDataFilter  # Import the new filter

# Add import for Celery app
from backend.core.api.app.tasks.celery_config import app as celery_app

# Import our new compliance logging setup
# Import the metrics update task
from backend.core.api.app.tasks.user_metrics import periodic_metrics_update, update_active_users_metrics

# Get a logger instance for this module (main.py) after setup
logger = logging.getLogger(__name__)

# DISCOVERED_APPS_METADATA_CACHE_KEY is now defined in CacheService

# Import the listener functions for Redis Pub/Sub
from backend.core.api.app.routes.websockets import (
    listen_for_cache_events, 
    listen_for_ai_chat_streams, 
    listen_for_ai_message_persisted_events,
    listen_for_ai_typing_indicator_events, # Added import
    listen_for_chat_updates # Added import
)

# Load environment variables
# load_dotenv() # Moved to the top before logging setup

# Check crucial environment variables
DIRECTUS_TOKEN = os.getenv("DIRECTUS_TOKEN")
if not DIRECTUS_TOKEN:
    logger.warning("DIRECTUS_TOKEN environment variable is not set. Authentication with Directus will fail.")

# Services will be initialized within the lifespan context manager
# and stored in app.state

# Create the application instance
app = None

# Define lifespan context manager for startup/shutdown events

async def discover_apps(app_state: any) -> Dict[str, AppYAML]: # Use 'any' for app_state for now if Request.state causes issues
    """
    Discovers enabled apps by fetching their metadata.
    """
    DEFAULT_APP_INTERNAL_PORT = 8000 # Standard internal port for our apps
    discovered_metadata: Dict[str, AppYAML] = {}
    # Ensure config_manager is accessed correctly from app_state
    if not hasattr(app_state, 'config_manager'):
        logger.error("Service Discovery: config_manager not found in app.state.")
        return discovered_metadata
        
    enabled_app_ids: List[str] = app_state.config_manager.get_enabled_apps()

    if not enabled_app_ids:
        logger.info("Service Discovery: No enabled apps configured to discover.")
        return discovered_metadata

    logger.info(f"Service Discovery: Starting discovery for {len(enabled_app_ids)} enabled app(s): {enabled_app_ids}")
    async with httpx.AsyncClient(timeout=5.0) as client: # 5 second timeout for metadata calls
        for app_id in enabled_app_ids:
            # Construct hostname by prepending "app-" to the app_id from config
            hostname = f"app-{app_id}"
            metadata_url = f"http://{hostname}:{DEFAULT_APP_INTERNAL_PORT}/metadata"
            logger.info(f"Service Discovery: Attempting to fetch metadata from {metadata_url} for app '{app_id}' (using service name '{hostname}')")
            try:
                response = await client.get(metadata_url)
                response.raise_for_status() # Raise an exception for HTTP 4xx/5xx errors
                app_metadata_json = response.json()
                try:
                    app_yaml_data = AppYAML(**app_metadata_json)
                    # Ensure the app_id from backend.core.api.app.yml (if present) matches the service name, or set it.
                    # The app_id from enabled_apps (service name) is the key.
                    if app_yaml_data.id and app_yaml_data.id != app_id:
                        logger.warning(f"Service Discovery: App ID mismatch for service '{app_id}'. "
                                       f"Configured ID in app.yml is '{app_yaml_data.id}'. Using service name '{app_id}' as the key.")
                    app_yaml_data.id = app_id # Standardize the ID to the service name from backend_config

                    discovered_metadata[app_id] = app_yaml_data
                    logger.info(f"Service Discovery: Successfully discovered and validated metadata for app '{app_id}'. Skills: {len(app_yaml_data.skills)}, Focuses: {len(app_yaml_data.focuses)}")
                except Exception as pydantic_error:
                    logger.error(f"Service Discovery: Metadata for app '{app_id}' from {metadata_url} is invalid or does not match AppYAML schema. Error: {pydantic_error}. Data: {app_metadata_json}")

            except httpx.HTTPStatusError as e:
                logger.error(f"Service Discovery: HTTP error while fetching metadata for app '{app_id}' from {metadata_url}. Status: {e.response.status_code}. Response: {e.response.text}")
            except httpx.RequestError as e:
                logger.error(f"Service Discovery: Request error while fetching metadata for app '{app_id}' from {metadata_url}. Error: {e}")
            except Exception as e:
                logger.error(f"Service Discovery: Unexpected error while fetching metadata for app '{app_id}' from {metadata_url}. Error: {e}", exc_info=True)
    
    logger.info(f"Service Discovery: Completed. Discovered {len(discovered_metadata)} app(s) successfully.")
    return discovered_metadata


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
    
    # Initialize EmailTemplateService (depends on SecretsManager)
    app.state.email_template_service = EmailTemplateService(secrets_manager=app.state.secrets_manager)
    
    # Initialize S3UploadService (depends on SecretsManager)
    app.state.s3_service = S3UploadService(secrets_manager=app.state.secrets_manager)
    logger.info("S3 service instance created.")
    
    # Initialize ImageSafetyService (depends on SecretsManager)
    app.state.image_safety_service = ImageSafetyService(secrets_manager=app.state.secrets_manager)
    logger.info("Image safety service instance created.")

    # Initialize PaymentService (depends on SecretsManager)
    app.state.payment_service = PaymentService(secrets_manager=app.state.secrets_manager)
    logger.info("Payment service instance created.")

    # Store ConfigManager in app.state
    app.state.config_manager = config_manager
    # Log raw enabled_apps config for now, actual discovery happens later
    raw_enabled_apps = app.state.config_manager.get_backend_config().get('enabled_apps', [])
    logger.info(f"ConfigManager initialized. Configured enabled_apps (raw): {raw_enabled_apps}")

    logger.info("All core service instances created.")

    # --- Perform App Service Discovery ---
    # This should happen after core services like config_manager are ready.
    logger.info("Starting App Service Discovery...")
    app.state.discovered_apps_metadata = await discover_apps(app.state)
    if app.state.discovered_apps_metadata:
        discovered_app_names = list(app.state.discovered_apps_metadata.keys())
        logger.info(f"Successfully discovered apps and loaded metadata for: {discovered_app_names}")
        for app_id, metadata in app.state.discovered_apps_metadata.items():
            skill_ids = [skill.id for skill in metadata.skills]
            focus_ids = [focus.id for focus in metadata.focuses]
            logger.info(f"  App '{app_id}': Skill IDs: {skill_ids}, Focus IDs: {focus_ids}")
    else:
        logger.warning("No apps were discovered or metadata could not be fetched/validated for any app.")

    # --- Cache the discovered_apps_metadata using CacheService ---
    if app.state.discovered_apps_metadata and hasattr(app.state, 'cache_service'):
        try:
            await app.state.cache_service.set_discovered_apps_metadata(app.state.discovered_apps_metadata)
            # Logger message for success is in CacheService.set_discovered_apps_metadata
        except Exception as e_cache: # Should be caught by CacheService, but as a safeguard:
            logger.error(f"Error explicitly calling set_discovered_apps_metadata from main.py: {e_cache}", exc_info=True)
    elif not hasattr(app.state, 'cache_service'):
        logger.error("CacheService not available in app.state. Cannot cache discovered_apps_metadata.")
    
    # --- Perform other async initializations ---
    # Initialize S3 service (fetches secrets, creates clients, buckets, etc.)
    logger.info("Initializing S3 service...")
    await app.state.s3_service.initialize()
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

        # Initialize Payment service (sets base URL)
        logger.info("Initializing Payment service...")
        await app.state.payment_service.initialize(is_production=os.getenv("SERVER_ENVIRONMENT", "development") == "production")
        logger.info("Payment service initialized successfully.")
        
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
        
        # Run initial metrics update, passing services from backend.core.api.app.state
        await update_active_users_metrics(
            directus_service=app.state.directus_service, 
            metrics_service=app.state.metrics_service
        )
        
        # Start the background task for periodic metrics updates, passing services from backend.core.api.app.state
        # We use create_task to avoid blocking startup
        app.state.metrics_task = asyncio.create_task(periodic_metrics_update(
            directus_service=app.state.directus_service, 
            metrics_service=app.state.metrics_service
        ))
        logger.info("Started periodic metrics update task")
    except Exception as e:
        logger.error(f"Failed to initialize: {str(e)}", exc_info=True)

    # Start Redis Pub/Sub listener task
    logger.info("Starting Redis Pub/Sub listener for cache events as a background task...")
    app.state.redis_pubsub_listener_task = asyncio.create_task(listen_for_cache_events(app))
    
    logger.info("Starting Redis Pub/Sub listener for AI chat streams as a background task...")
    app.state.ai_chat_stream_listener_task = asyncio.create_task(listen_for_ai_chat_streams(app))

    logger.info("Starting Redis Pub/Sub listener for AI message persisted events as a background task...")
    app.state.ai_message_persisted_listener_task = asyncio.create_task(listen_for_ai_message_persisted_events(app))

    logger.info("Starting Redis Pub/Sub listener for AI typing indicator events as a background task...")
    app.state.ai_typing_indicator_listener_task = asyncio.create_task(listen_for_ai_typing_indicator_events(app))

    logger.info("Starting Redis Pub/Sub listener for chat update events as a background task...")
    app.state.chat_updates_listener_task = asyncio.create_task(listen_for_chat_updates(app))

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

    if hasattr(app.state, 'redis_pubsub_listener_task'):
        app.state.redis_pubsub_listener_task.cancel()
        try:
            await app.state.redis_pubsub_listener_task
        except asyncio.CancelledError:
            logger.info("Redis Pub/Sub listener task for cache events cancelled")

    if hasattr(app.state, 'ai_chat_stream_listener_task'):
        app.state.ai_chat_stream_listener_task.cancel()
        try:
            await app.state.ai_chat_stream_listener_task
        except asyncio.CancelledError:
            logger.info("Redis Pub/Sub listener task for AI chat streams cancelled")

    if hasattr(app.state, 'ai_message_persisted_listener_task'):
        app.state.ai_message_persisted_listener_task.cancel()
        try:
            await app.state.ai_message_persisted_listener_task
        except asyncio.CancelledError:
            logger.info("Redis Pub/Sub listener task for AI message persisted events cancelled")

    if hasattr(app.state, 'ai_typing_indicator_listener_task'):
        app.state.ai_typing_indicator_listener_task.cancel()
        try:
            await app.state.ai_typing_indicator_listener_task
        except asyncio.CancelledError:
            logger.info("Redis Pub/Sub listener task for AI typing indicator events cancelled")

    if hasattr(app.state, 'chat_updates_listener_task'):
        app.state.chat_updates_listener_task.cancel()
        try:
            await app.state.chat_updates_listener_task
        except asyncio.CancelledError:
            logger.info("Redis Pub/Sub listener task for chat updates cancelled")
            
    # Close encryption service client
    if hasattr(app.state, 'encryption_service'):
        await app.state.encryption_service.close()
        
    # Close Payment service client
    if hasattr(app.state, 'payment_service'):
        await app.state.payment_service.close()
        
    # Close Directus service client
    if hasattr(app.state, 'directus_service'):
        await app.state.directus_service.close()

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

    # Compliance logging is handled by setup_logging now

    # Create metrics endpoint
    metrics_app = make_asgi_app()
    app.mount("/metrics", metrics_app)

    # Add rate limiting exception handler
    app.state.limiter = limiter
    app.add_exception_handler(RateLimitExceeded, _rate_limit_exceeded_handler)

    # Add logging middleware (pass metrics service from backend.core.api.app.state if needed, or remove if unused)
    # Assuming LoggingMiddleware doesn't actually need metrics_service passed here
    app.add_middleware(LoggingMiddleware) 
    # If it does need it, it should fetch it via request.app.state inside the middleware

    # Determine environment (using .lower() for case-insensitivity)
    is_dev = os.getenv("SERVER_ENVIRONMENT", "development").lower() == "development"

    # Define defaults clearly
    default_dev_origins_str = "http://localhost:5174, https://app.dev.openmates.org"
    default_prod_origin_str = "https://app.openmates.org"

    # 1. Get the relevant string (either from env var or default)
    if is_dev:
        # In dev, read FRONTEND_URLS, fallback to the dev default string
        origins_str = os.getenv("FRONTEND_URLS", default_dev_origins_str)
        logger.info(f"Dev env: Reading FRONTEND_URLS (defaulting to '{default_dev_origins_str}')")
    else:
        # In prod, read PRODUCTION_URL, fallback to the prod default string
        # Consider renaming PRODUCTION_URL env var to FRONTEND_URLS for consistency if it might hold multiple URLs in the future.
        origins_str = os.getenv("PRODUCTION_URL", default_prod_origin_str)
        logger.info(f"Prod env: Reading PRODUCTION_URL (defaulting to '{default_prod_origin_str}')")

    # 2. Split the obtained string into a list
    if origins_str:
        # Split by comma, strip whitespace from each part, filter out any empty strings resulting from extra commas
        allowed_origins = [origin.strip() for origin in origins_str.split(',') if origin.strip()]
    else:
        # Handle case where the environment variable was set but empty, or default was somehow empty
        allowed_origins = []
        logger.warning("Origin string resolved to empty. No origins will be allowed.")

    # 3. Log the final list
    logger.info(f"Final allowed origins configured: {allowed_origins}")

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

    # Add ProxyHeadersMiddleware to handle X-Forwarded-* headers
    # TRUSTED_PROXY_IPS should be a comma-separated string of trusted proxy IPs/CIDRs
    # Defaulting to "*" trusts all proxies (use with caution in production)
    trusted_hosts = os.getenv("TRUSTED_PROXY_IPS", "*").split(",")
    app.add_middleware(ProxyHeadersMiddleware, trusted_hosts=trusted_hosts)

    # Include routers
    app.include_router(auth.router)
    app.include_router(email.router)
    app.include_router(invoice.router)
    app.include_router(credit_note.router)
    app.include_router(settings.router)
    app.include_router(payments.router) # Include payments router
    app.include_router(websockets.router) # Include websockets router
    app.include_router(internal_api.router) # Include the internal API router

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
    # Uvicorn logging is now configured via logging.dictConfig in setup_logging
    # Use log_config=None to prevent uvicorn from overriding our config
    uvicorn.run(
        "main:app",
        host="0.0.0.0",
        port=port,
        reload=False,
        log_config=None # Let our setup_logging handle configuration
    )
