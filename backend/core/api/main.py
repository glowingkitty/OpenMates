import os
import uvicorn
import logging # Keep logging import for potential direct use if needed
from dotenv import load_dotenv

# --- Setup Logging FIRST ---
# Load environment variables early for logging config if needed
load_dotenv()
from backend.core.api.app.utils.setup_logging import setup_logging  # noqa: E402
setup_logging()
# --- End Logging Setup ---

# Now import other modules that might log
from fastapi import FastAPI, Request  # noqa: E402
from fastapi.responses import RedirectResponse  # noqa: E402
from fastapi.middleware.cors import CORSMiddleware  # noqa: E402
from fastapi.openapi.utils import get_openapi  # noqa: E402
from contextlib import asynccontextmanager  # noqa: E402
from slowapi import _rate_limit_exceeded_handler  # noqa: E402
from slowapi.errors import RateLimitExceeded  # noqa: E402
from prometheus_client import make_asgi_app  # noqa: E402
from uvicorn.middleware.proxy_headers import ProxyHeadersMiddleware  # noqa: E402
import httpx  # noqa: E402 # For service discovery
from typing import Dict, List, Any, Optional  # noqa: E402 # For type hinting

# Make sure the path is correct based on your project structure
from backend.core.api.app.routes import auth, email, invoice, credit_note, settings, payments, websockets  # noqa: E402
from backend.core.api.app.routes import internal_api  # noqa: E402 # Import the new internal API router
from backend.core.api.app.routes import apps  # noqa: E402 # Import apps router
from backend.core.api.app.routes import share  # noqa: E402 # Import share router
from backend.core.api.app.routes import demo_chat  # noqa: E402 # Import demo chat router
from backend.core.api.app.routes import admin  # noqa: E402 # Import admin router
from backend.core.api.app.routes import admin_debug  # noqa: E402 # Import admin debug router for remote debugging
from backend.core.api.app.routes import apps_api  # noqa: E402 # Import apps API router for external API access
from backend.core.api.app.routes import creators  # noqa: E402 # Import creators router
from backend.core.api.app.routes import newsletter  # noqa: E402 # Import newsletter router
from backend.core.api.app.routes import email_block  # noqa: E402 # Import email block router
from backend.core.api.app.services.directus import DirectusService  # noqa: E402
from backend.core.api.app.services.cache import CacheService  # noqa: E402
from backend.core.api.app.services.metrics import MetricsService  # noqa: E402
from backend.core.api.app.services.compliance import ComplianceService  # noqa: E402
from backend.core.api.app.services.email_template import EmailTemplateService  # noqa: E402
from backend.core.api.app.services.image_safety import ImageSafetyService  # noqa: E402 # Import ImageSafetyService
from backend.core.api.app.services.s3.service import S3UploadService  # noqa: E402 # Import S3UploadService
from backend.core.api.app.services.payment.payment_service import PaymentService  # noqa: E402 # Import PaymentService
from backend.core.api.app.services.invoiceninja.invoiceninja import InvoiceNinjaService  # noqa: E402 # Import InvoiceNinjaService
from backend.core.api.app.services.stripe_product_sync import StripeProductSync  # noqa: E402 # Import StripeProductSync
from backend.core.api.app.services.translations import TranslationService  # noqa: E402 # Import TranslationService for resolving app metadata translations
from backend.core.api.app.utils.encryption import EncryptionService  # noqa: E402
from backend.core.api.app.utils.secrets_manager import SecretsManager  # noqa: E402 # Add import for SecretManager
from backend.core.api.app.utils.server_mode import is_payment_enabled  # noqa: E402 # Import for checking payment status during router registration
from backend.core.api.app.services.limiter import limiter  # noqa: E402
from backend.core.api.app.utils.config_manager import config_manager  # noqa: E402
from backend.shared.python_schemas.app_metadata_schemas import AppYAML  # noqa: E402 # Moved AppYAML to backend_shared

# Middleware & Utils
from backend.core.api.app.middleware.logging_middleware import LoggingMiddleware  # noqa: E402

# Add import for Celery app
from backend.core.api.app.tasks.celery_config import app as celery_app  # noqa: E402

# Import our new compliance logging setup
# Import the metrics update task
from backend.core.api.app.tasks.user_metrics import periodic_metrics_update, update_active_users_metrics  # noqa: E402

# Get a logger instance for this module (main.py) after setup
logger = logging.getLogger(__name__)

# DISCOVERED_APPS_METADATA_CACHE_KEY is now defined in CacheService

# Import the listener functions for Redis Pub/Sub
from backend.core.api.app.routes.websockets import (  # noqa: E402
    listen_for_cache_events, 
    listen_for_ai_chat_streams,
    listen_for_ai_thinking_streams,  # Thinking/reasoning streams for thinking models (Gemini, Anthropic)
    listen_for_ai_message_persisted_events,
    listen_for_ai_typing_indicator_events, # Added import
    listen_for_chat_updates, # Added import
    listen_for_user_updates,
    listen_for_embed_data_events
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

def scan_filesystem_for_apps() -> List[str]:
    """
    Scans the backend/apps directory for all subdirectories containing app.yml files.
    Returns a list of app IDs (directory names).
    
    This enables auto-discovery of all apps without manual configuration.
    """
    APPS_DIR = "/app/backend/apps"  # Path inside Docker container
    app_ids = []
    
    if not os.path.isdir(APPS_DIR):
        logger.warning(f"Apps directory not found: {APPS_DIR}. Cannot auto-discover apps.")
        return app_ids
    
    try:
        for item in os.listdir(APPS_DIR):
            item_path = os.path.join(APPS_DIR, item)
            # Check if it's a directory and contains app.yml
            if os.path.isdir(item_path):
                app_yml_path = os.path.join(item_path, "app.yml")
                if os.path.isfile(app_yml_path):
                    app_ids.append(item)
                    logger.debug(f"Found app directory with app.yml: {item}")
    except OSError as e:
        logger.error(f"Error scanning apps directory {APPS_DIR}: {e}")
    
    logger.info(f"Filesystem scan found {len(app_ids)} app(s): {app_ids}")
    return app_ids


def filter_app_components_by_stage(app_metadata_json: Dict[str, Any], server_environment: str) -> Dict[str, Any]:
    """
    Filters app components (skills, focuses, memory_fields) by stage and returns
    a filtered copy of the metadata.
    
    Rules:
    - Development server: Include components with stage='development' OR stage='production'
    - Production server: Include components with stage='production' only
    - Components without stage or with invalid stage are excluded
    
    Args:
        app_metadata_json: The raw JSON metadata from the app service
        server_environment: 'development' or 'production'
    
    Returns:
        Filtered metadata dictionary with only valid components, or None if no valid components
    """
    # Determine required stages based on server environment
    if server_environment.lower() == "production":
        required_stages = ["production"]
    else:  # development (default)
        required_stages = ["development", "production"]
    
    # Create a copy of the metadata to filter
    filtered_metadata = app_metadata_json.copy()
    
    # Filter skills by stage (stage field is in schema)
    skills_data = filtered_metadata.get("skills", [])
    if isinstance(skills_data, list):
        filtered_skills = [
            skill for skill in skills_data
            if isinstance(skill, dict) and skill.get("stage", "").lower() in required_stages
        ]
        filtered_metadata["skills"] = filtered_skills
    else:
        filtered_metadata["skills"] = []
    
    # Filter focuses by stage - access raw JSON to check stage field
    # Focuses may have stage in YAML but not in schema
    # The actual JSON uses "focuses" (not "focus_modes")
    focuses_data = []
    if "focuses" in filtered_metadata and isinstance(filtered_metadata["focuses"], list):
        focuses_data = filtered_metadata["focuses"]
    elif "focus_modes" in filtered_metadata and isinstance(filtered_metadata["focus_modes"], list):
        # Fallback to alias if "focuses" doesn't exist
        focuses_data = filtered_metadata["focus_modes"]
    
    # Filter by stage
    filtered_focuses = [
        focus for focus in focuses_data
        if isinstance(focus, dict) and focus.get("stage", "").lower() in required_stages
    ]
    
    # Set the field name (use "focuses" as that's what the JSON uses)
    filtered_metadata["focuses"] = filtered_focuses
    
    # Filter memory fields by stage - access raw JSON to check stage field
    # Memory fields may have stage in YAML but not in schema
    # The actual JSON uses "settings_and_memories" (not "memory_fields" or "memory")
    memory_data = []
    if "settings_and_memories" in filtered_metadata and isinstance(filtered_metadata["settings_and_memories"], list):
        memory_data = filtered_metadata["settings_and_memories"]
    elif "memory_fields" in filtered_metadata and isinstance(filtered_metadata["memory_fields"], list):
        # Fallback to other field names if "settings_and_memories" doesn't exist
        memory_data = filtered_metadata["memory_fields"]
    elif "memory" in filtered_metadata and isinstance(filtered_metadata["memory"], list):
        memory_data = filtered_metadata["memory"]
    
    # Filter by stage
    filtered_memory = [
        memory for memory in memory_data
        if isinstance(memory, dict) and memory.get("stage", "").lower() in required_stages
    ]
    
    # Set the field name (use "settings_and_memories" as that's what the JSON uses)
    filtered_metadata["settings_and_memories"] = filtered_memory
    
    # Check if app has at least one valid component
    has_valid_skill = len(filtered_metadata.get("skills", [])) > 0
    has_valid_focus = len(filtered_metadata.get("focuses", [])) > 0
    has_valid_memory = len(filtered_metadata.get("settings_and_memories", [])) > 0
    
    # Return filtered metadata if app has at least one valid component, otherwise None
    if has_valid_skill or has_valid_focus or has_valid_memory:
        return filtered_metadata
    else:
        return None


async def discover_apps(app_state: any) -> Dict[str, AppYAML]: # Use 'any' for app_state for now if Request.state causes issues
    """
    Auto-discovers all apps by scanning the filesystem and fetching their metadata.
    Apps are filtered by component stages based on SERVER_ENVIRONMENT:
    - Development: Apps with 'development' or 'production' stage components
    - Production: Apps with 'production' stage components only
    - Apps in disabled_apps list are excluded
    
    No manual configuration needed - new apps are automatically available by default.
    """
    DEFAULT_APP_INTERNAL_PORT = 8000 # Standard internal port for our apps
    discovered_metadata: Dict[str, AppYAML] = {}
    
    # Ensure config_manager is accessed correctly from app_state
    if not hasattr(app_state, 'config_manager'):
        logger.error("Service Discovery: config_manager not found in app.state.")
        return discovered_metadata
    
    # Get server environment for stage-based filtering
    server_environment = os.getenv("SERVER_ENVIRONMENT", "development").lower()
    logger.info(f"Service Discovery: Server environment is '{server_environment}'")
    
    # Get disabled apps list (opt-out)
    disabled_app_ids: List[str] = app_state.config_manager.get_disabled_apps()
    if disabled_app_ids:
        logger.info(f"Service Discovery: {len(disabled_app_ids)} app(s) explicitly disabled: {disabled_app_ids}")
    
    # Auto-discover all apps by scanning filesystem
    all_app_ids = scan_filesystem_for_apps()
    
    if not all_app_ids:
        logger.warning("Service Discovery: No apps found in filesystem scan. Check that backend/apps directory exists and contains app subdirectories.")
        return discovered_metadata
    
    logger.info(f"Service Discovery: Starting discovery for {len(all_app_ids)} app(s) found in filesystem: {all_app_ids}")
    
    # Check all apps (except disabled ones) - filtering happens at component level
    apps_to_check = []
    for app_id in all_app_ids:
        # Skip disabled apps
        if app_id in disabled_app_ids:
            logger.info(f"Service Discovery: Skipping app '{app_id}' (explicitly disabled in config)")
            continue
        
        # Check all apps - component-level filtering happens later
        apps_to_check.append(app_id)
    
    logger.info(f"Service Discovery: Will check {len(apps_to_check)} app(s): {apps_to_check}")
    
    # PERFORMANCE OPTIMIZATION: Fetch all app metadata in parallel instead of sequentially
    # This reduces discovery time from N*timeout to max(timeout) for N apps
    async def fetch_app_metadata(client: httpx.AsyncClient, app_id: str) -> tuple[str, Optional[AppYAML], Optional[str]]:
        """Fetch metadata for a single app. Returns (app_id, metadata, error_message)."""
        hostname = f"app-{app_id}"
        metadata_url = f"http://{hostname}:{DEFAULT_APP_INTERNAL_PORT}/metadata"
        logger.debug(f"Service Discovery: Attempting to fetch metadata from {metadata_url} for app '{app_id}' (using service name '{hostname}')")
        
        try:
            response = await client.get(metadata_url)
            response.raise_for_status()
            app_metadata_json = response.json()
            
            # Filter components by stage before parsing
            filtered_metadata_json = filter_app_components_by_stage(app_metadata_json, server_environment)
            
            # If no valid components after filtering, skip this app
            if filtered_metadata_json is None:
                return (app_id, None, f"App '{app_id}' excluded (no components with required stage for '{server_environment}' environment)")
            
            # Parse the filtered metadata
            app_yaml_data = AppYAML(**filtered_metadata_json)
            # Ensure the app_id matches the service name
            if app_yaml_data.id and app_yaml_data.id != app_id:
                logger.warning(f"Service Discovery: App ID mismatch for service '{app_id}'. "
                               f"Configured ID in app.yml is '{app_yaml_data.id}'. Using service name '{app_id}' as the key.")
            app_yaml_data.id = app_id
            
            return (app_id, app_yaml_data, None)
            
        except httpx.HTTPStatusError as e:
            return (app_id, None, f"HTTP error {e.response.status_code}. App service may not be running.")
        except httpx.RequestError as e:
            return (app_id, None, f"Request error: {e}. App service may not be running.")
        except Exception as e:
            logger.error(f"Service Discovery: Unexpected error while fetching metadata for app '{app_id}' from {metadata_url}. Error: {e}", exc_info=True)
            return (app_id, None, f"Unexpected error: {e}")
    
    async with httpx.AsyncClient(timeout=5.0) as client:
        # Fetch all app metadata in parallel
        import asyncio
        tasks = [fetch_app_metadata(client, app_id) for app_id in apps_to_check]
        results = await asyncio.gather(*tasks, return_exceptions=True)
        
        # Process results
        for result in results:
            if isinstance(result, Exception):
                logger.error(f"Service Discovery: Unexpected exception during parallel fetch: {result}")
                continue
            
            app_id, app_yaml_data, error_msg = result
            
            if app_yaml_data is not None:
                discovered_metadata[app_id] = app_yaml_data
                logger.info(f"Service Discovery: Successfully discovered and included app '{app_id}'. Skills: {len(app_yaml_data.skills)}, Focuses: {len(app_yaml_data.focuses)}, Memory fields: {len(app_yaml_data.memory_fields) if app_yaml_data.memory_fields else 0}")
            elif error_msg:
                # Log at appropriate level based on error type
                if "excluded" in error_msg:
                    logger.info(f"Service Discovery: {error_msg}")
                else:
                    logger.warning(f"Service Discovery: App '{app_id}': {error_msg}")
    
    logger.info(f"Service Discovery: Completed. Discovered and included {len(discovered_metadata)} app(s) successfully.")
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
    
    # Initialize server stats service
    from backend.core.api.app.services.server_stats_service import ServerStatsService
    app.state.server_stats_service = ServerStatsService(
        cache_service=app.state.cache_service,
        directus_service=app.state.directus_service
    )
    
    # Server stats service depends on cache and directus
    app.state.server_stats_service = ServerStatsService(
        cache_service=app.state.cache_service,
        directus_service=app.state.directus_service
    )
    
    # Initialize EmailTemplateService (depends on SecretsManager)
    app.state.email_template_service = EmailTemplateService(secrets_manager=app.state.secrets_manager)
    
    # Initialize S3UploadService (depends on SecretsManager)
    app.state.s3_service = S3UploadService(secrets_manager=app.state.secrets_manager)
    logger.info("S3 service instance created.")
    
    # Initialize ImageSafetyService (depends on SecretsManager)
    app.state.image_safety_service = ImageSafetyService(secrets_manager=app.state.secrets_manager)
    logger.info("Image safety service instance created.")

    # Initialize PaymentService conditionally (only if payment is enabled)
    # Note: We check payment_enabled later after domain validation, but create service instance here
    # The service will only be initialized/used if payment_enabled is True
    app.state.payment_service = PaymentService(secrets_manager=app.state.secrets_manager)
    logger.info("Payment service instance created (will be initialized only if payment enabled).")

    # Initialize InvoiceNinjaService conditionally (only if payment is enabled)
    # Note: We check payment_enabled later after domain validation, but create service instance here
    # The service will only be initialized/used if payment_enabled is True
    logger.info("Initializing Invoice Ninja service (will be initialized only if payment enabled)...")
    app.state.invoice_ninja_service = await InvoiceNinjaService.create(secrets_manager=app.state.secrets_manager)

    # Store ConfigManager in app.state
    app.state.config_manager = config_manager
    # Log disabled_apps config for reference
    disabled_apps = app.state.config_manager.get_disabled_apps()
    logger.info(f"ConfigManager initialized. Disabled apps: {disabled_apps if disabled_apps else 'none (all apps enabled by default)'}")

    # Initialize TranslationService for resolving app metadata translations
    logger.info("Initializing TranslationService...")
    app.state.translation_service = TranslationService()
    
    # Pre-load translations during server startup to populate the shared cache
    # This ensures translations are ready before any requests come in
    logger.info("Pre-loading translations into cache...")
    try:
        # Pre-load English translations (default language)
        # This will load all YAML files and convert them to JSON structure, storing in class-level cache
        app.state.translation_service.get_translations(lang="en")
        logger.info("Translations pre-loaded successfully into shared cache.")
    except Exception as e:
        logger.error(f"Failed to pre-load translations during startup: {e}", exc_info=True)
        # Don't fail startup if translations fail to load - they'll be loaded on first request
    
    logger.info("TranslationService initialized successfully.")

    logger.info("All core service instances created.")

    # --- Perform App Service Discovery ---
    # This should happen after core services like config_manager are ready.
    logger.info("Starting App Service Discovery...")
    app.state.discovered_apps_metadata = await discover_apps(app.state)
    
    # Translation resolution happens in the metadata endpoint when requested
    # This ensures translations are always up-to-date and allows for language selection in the future
    if app.state.discovered_apps_metadata:
        discovered_app_names = list(app.state.discovered_apps_metadata.keys())
        logger.info(f"Successfully discovered apps and loaded metadata for: {discovered_app_names}")
        for app_id, metadata in app.state.discovered_apps_metadata.items():
            skill_ids = [skill.id for skill in metadata.skills]
            focus_ids = [focus.id for focus in metadata.focuses]
            logger.info(f"  App '{app_id}': Skill IDs: {skill_ids}, Focus IDs: {focus_ids}")
        
        # Register dynamic routes for each app and skill
        logger.info("Registering dynamic routes for discovered apps and skills...")
        from backend.core.api.app.routes.apps_api import register_app_and_skill_routes
        register_app_and_skill_routes(app, app.state.discovered_apps_metadata)
        logger.info("Successfully registered dynamic routes for all apps and skills")
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

    # --- Restore pending payment orders from disk backup ---
    # This recovers payment orders that were persisted during the last graceful shutdown
    # to prevent payment data loss if a webhook arrives after cache was cleared by restart
    if hasattr(app.state, 'cache_service'):
        try:
            restored_count = await app.state.cache_service.restore_orders_from_disk()
            if restored_count > 0:
                logger.info(f"Restored {restored_count} pending payment orders from disk backup")
        except Exception as e:
            logger.error(f"Error restoring payment orders from disk: {e}", exc_info=True)
    
    # --- Preload and cache AI processing configuration files ---
    # This ensures base_instructions and mates_configs are ready in cache before first message arrives
    # This optimization prevents disk I/O on every message processing request
    logger.info("Preloading AI processing configuration files into cache...")
    if hasattr(app.state, 'cache_service'):
        try:
            # Import loaders for base_instructions and mates_configs
            from backend.apps.ai.utils.instruction_loader import load_base_instructions
            from backend.apps.ai.utils.mate_utils import load_mates_config
            
            # Load base_instructions from disk and cache it
            logger.info("Loading base_instructions.yml from disk...")
            base_instructions = load_base_instructions()
            if base_instructions:
                try:
                    await app.state.cache_service.set_base_instructions(base_instructions)
                    logger.info("Successfully preloaded and cached base_instructions.")
                except Exception as e_base:
                    logger.error(f"Failed to cache base_instructions during startup: {e_base}", exc_info=True)
                    # Don't fail startup - will fallback to disk loading on first request
            else:
                logger.warning("Failed to load base_instructions.yml during startup. Will fallback to disk loading on first request.")
            
            # Load mates_configs from disk and cache it
            logger.info("Loading mates.yml from disk...")
            mates_configs = load_mates_config()
            if mates_configs:
                try:
                    await app.state.cache_service.set_mates_configs(mates_configs)
                    logger.info(f"Successfully preloaded and cached {len(mates_configs)} mates_configs.")
                except Exception as e_mates:
                    logger.error(f"Failed to cache mates_configs during startup: {e_mates}", exc_info=True)
                    # Don't fail startup - will fallback to disk loading on first request
            else:
                logger.warning("Failed to load mates.yml during startup. Will fallback to disk loading on first request.")
            
            # Load content sanitization model from AI app.yml and cache it
            logger.info("Loading content sanitization model from AI app.yml...")
            try:
                from backend.apps.ai.processing.content_sanitization import _load_content_sanitization_model
                content_sanitization_model = _load_content_sanitization_model()
                if content_sanitization_model:
                    try:
                        await app.state.cache_service.set_content_sanitization_model(content_sanitization_model)
                        logger.info(f"Successfully preloaded and cached content_sanitization_model: {content_sanitization_model}")
                    except Exception as e_model:
                        logger.error(f"Failed to cache content_sanitization_model during startup: {e_model}", exc_info=True)
                        # Don't fail startup - will fallback to disk loading on first request
                else:
                    logger.warning("Failed to load content_sanitization_model from AI app.yml during startup. Will fallback to disk loading on first request.")
            except Exception as e_model_load:
                logger.error(f"Error loading content_sanitization_model during startup: {e_model_load}", exc_info=True)
                # Don't fail startup - will fallback to disk loading on first request
            
            # Load prompt injection detection config from YAML and cache it
            logger.info("Loading prompt_injection_detection.yml from disk...")
            try:
                from backend.apps.ai.processing.content_sanitization import _load_prompt_injection_detection_config
                prompt_injection_config = _load_prompt_injection_detection_config()
                if prompt_injection_config:
                    try:
                        await app.state.cache_service.set_prompt_injection_detection_config(prompt_injection_config)
                        logger.info("Successfully preloaded and cached prompt_injection_detection_config.")
                    except Exception as e_config:
                        logger.error(f"Failed to cache prompt_injection_detection_config during startup: {e_config}", exc_info=True)
                        # Don't fail startup - will fallback to disk loading on first request
                else:
                    logger.warning("Failed to load prompt_injection_detection.yml during startup. Will fallback to disk loading on first request.")
            except Exception as e_config_load:
                logger.error(f"Error loading prompt_injection_detection_config during startup: {e_config_load}", exc_info=True)
                # Don't fail startup - will fallback to disk loading on first request
        except Exception as e_preload:
            logger.error(f"Error during AI configuration preloading: {e_preload}", exc_info=True)
            # Don't fail startup - will fallback to disk loading on first request
    else:
        logger.warning("CacheService not available in app.state. Cannot preload AI configuration files.")

    # --- Preload leaderboard data into cache ---
    # This ensures model rankings are available before first AI request
    # If no leaderboard data exists, trigger generation asynchronously
    logger.info("Preloading leaderboard data into cache...")
    if hasattr(app.state, 'cache_service'):
        try:
            from backend.core.api.app.tasks.leaderboard_tasks import get_leaderboard_data
            leaderboard_data = await get_leaderboard_data()
            if leaderboard_data:
                ranked_count = len(leaderboard_data.get("rankings", []))
                logger.info(f"Successfully preloaded leaderboard data with {ranked_count} ranked models.")
            else:
                # No leaderboard data exists - trigger generation asynchronously
                logger.warning("No leaderboard data available. Triggering initial leaderboard generation...")
                try:
                    task_result = celery_app.send_task(
                        "leaderboard.update_daily",
                        queue="leaderboard",
                        kwargs={"category": "text"}
                    )
                    logger.info(f"Initial leaderboard generation task queued. Task ID: {task_result.id}")
                except Exception as e_task:
                    logger.warning(f"Failed to queue leaderboard generation task: {e_task}")
        except Exception as e_leaderboard:
            logger.warning(f"Failed to preload leaderboard data during startup: {e_leaderboard}")
            # Don't fail startup - leaderboard is optional for model selection
    else:
        logger.warning("CacheService not available in app.state. Cannot preload leaderboard data.")

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
        
        # Validate hosting domain against security policies (prevents self-hosting on restricted domains)
        logger.info("Validating hosting domain against security policies...")
        try:
            from backend.core.api.app.services.domain_security import DomainSecurityService
            # Note: encryption_service parameter kept for compatibility but not used
            # Fernet decryption uses key derivation from codebase constants
            domain_security_service = DomainSecurityService()
            
            # Load security configuration
            try:
                domain_security_service.load_security_config()
                logger.info("Domain security configuration loaded successfully")
            except SystemExit as e:
                logger.critical(f"CRITICAL: Cannot load domain security configuration: {e}")
                raise SystemExit("Server files missing")
            except Exception as e:
                logger.critical(f"CRITICAL: Error loading domain security configuration: {e}")
                raise SystemExit("Server files missing")
            
            # Validate hosting domain
            is_allowed, error_message = domain_security_service.validate_hosting_domain()
            if not is_allowed:
                logger.critical(f"CRITICAL: Server cannot start on restricted domain: {error_message}")
                raise SystemExit("Domain not supported")
            
            logger.info("Hosting domain validation passed")
            
            # Store security service in app state for use in auth endpoints
            app.state.domain_security_service = domain_security_service
            
            # --- Determine payment/billing status based on domain and environment ---
            # This must happen AFTER domain_security_service.load_security_config() is called
            # so that _ALLOWED_DOMAIN is populated from the encrypted file
            from backend.core.api.app.utils.server_mode import (
                is_payment_enabled,
                get_server_edition,
                get_hosting_domain
            )
            
            # Determine payment status
            payment_enabled = is_payment_enabled()
            hosting_domain = get_hosting_domain()
            server_edition = get_server_edition()
            is_development = os.getenv("SERVER_ENVIRONMENT", "development").lower() == "development"
            is_self_hosted = not payment_enabled
            
            # Store payment status flags in app.state for use throughout the application
            app.state.payment_enabled = payment_enabled
            app.state.is_self_hosted = is_self_hosted
            app.state.is_development = is_development
            app.state.server_edition = server_edition
            
            logger.info(
                f"Payment/Billing Status: enabled={payment_enabled}, "
                f"self_hosted={is_self_hosted}, "
                f"server_edition={server_edition}, "
                f"hosting_domain={hosting_domain or 'localhost'}"
            )
            
        except SystemExit:
            # Re-raise SystemExit to prevent server startup
            raise
        except Exception as e:
            logger.critical(f"CRITICAL: Domain validation failed: {e}")
            raise SystemExit("Domain not supported")
        
        # Initialize metrics (depends on directus service)
        logger.info("Initializing metrics...")
        await app.state.metrics_service.initialize_metrics(app.state.directus_service)
        logger.info("Metrics service initialized successfully.")

        # Initialize Payment service conditionally (only if payment is enabled)
        # Check payment_enabled flag that was set during domain validation
        if hasattr(app.state, 'payment_enabled') and app.state.payment_enabled:
            logger.info("Initializing Payment service (payment enabled)...")
            await app.state.payment_service.initialize(is_production=os.getenv("SERVER_ENVIRONMENT", "development") == "production")
            logger.info("Payment service initialized successfully.")

            # Initialize Stripe Product Sync service (only if payment enabled)
            logger.info("Initializing Stripe Product Sync service...")
            app.state.stripe_product_sync = StripeProductSync(app.state.payment_service.provider)
            logger.info("Stripe Product Sync service initialized successfully.")

            # Synchronize Stripe products with pricing configuration (only if payment enabled)
            logger.info("Synchronizing Stripe products with pricing configuration...")
            try:
                sync_result = await app.state.stripe_product_sync.sync_all_products()
                if sync_result.get("success"):
                    results = sync_result.get("results", {})
                    logger.info(f"Stripe product synchronization completed successfully. "
                               f"One-time products: {results.get('one_time_products', {}).get('created', 0)} created, "
                               f"{results.get('one_time_products', {}).get('updated', 0)} updated, "
                               f"{results.get('one_time_products', {}).get('errors', 0)} errors. "
                               f"Subscription products: {results.get('subscription_products', {}).get('created', 0)} created, "
                               f"{results.get('subscription_products', {}).get('updated', 0)} updated, "
                               f"{results.get('subscription_products', {}).get('errors', 0)} errors.")
                else:
                    error_msg = sync_result.get("error", "Unknown error")
                    logger.warning(f"Stripe product synchronization failed: {error_msg}")
                    # Don't fail startup, just log the warning
            except Exception as sync_error:
                logger.warning(f"Stripe product synchronization encountered an error: {str(sync_error)}")
                # Don't fail startup, just log the warning
        else:
            logger.info("Skipping Payment service initialization (payment disabled - self-hosted mode)")
            app.state.stripe_product_sync = None

    except Exception as e:
        logger.critical(f"Failed during critical service initialization: {str(e)}", exc_info=True)
        # Depending on the severity, might want to raise exception to stop startup
        # raise e 
    
    # --- Other startup logic ---
    logger.info("Invoice Ninja service initialized successfully.")
    logger.info("Preloading invite codes into cache...")
    try:
        # Pass app.state to preload_invite_codes
        await preload_invite_codes(app.state)
        
        # Preload gift cards into cache
        await preload_gift_cards(app.state) 
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
        logger.error(f"Failed to preload codes or start metrics task: {e}", exc_info=True)

    # Trigger initial health check for all providers on startup
    # This ensures /health endpoint has data immediately instead of waiting up to 5 minutes
    logger.info("Triggering initial health check for all providers...")
    try:
        # Trigger the health check task asynchronously (non-blocking)
        # Use apply_async for better error handling and to get task result
        task_result = celery_app.send_task(
            "health_check.check_all_providers",
            queue="health_check"
        )
        logger.info(f"Initial health check task queued successfully. Task ID: {task_result.id}")
        
        # --- NEW: Warm demo chats cache on startup ---
        logger.info("Triggering demo chats cache warming...")
        try:
            # We can't easily call demo methods from here without re-initializing everything
            # but we can trigger a task or just wait for first request.
            # Actually, let's just trigger a small async task to warm it.
            async def warm_demo_cache():
                try:
                    await asyncio.sleep(5) # Wait for other services to settle
                    
                    # IMPORTANT: Clear existing demo cache before warming to prevent stale data
                    # This ensures that any old cache entries (e.g., from before a demo was fully published
                    # or with missing fields like encrypted_category) are removed before we populate
                    # fresh data from the database.
                    logger.info("Clearing existing demo chats cache before warming...")
                    await app.state.directus_service.cache.clear_demo_chats_cache()
                    
                    # Fetch all active demo chats to warm the cache for all languages
                    from backend.core.api.app.tasks.demo_tasks import TARGET_LANGUAGES
                    for lang in TARGET_LANGUAGES:
                        # Fetch the list of published demo chats for this language
                        params = {
                            "filter": {
                                "status": {"_eq": "published"},
                                "is_active": {"_eq": True}
                            },
                            "sort": ["-created_at"]
                        }
                        demo_chats = await app.state.directus_service.get_items("demo_chats", params)
                        
                        if demo_chats:
                            # This warms both the list and individual chat data caches
                            # ARCHITECTURE: demo_chats from Directus have 'id' (UUID), not 'demo_id'
                            # The display ID (demo-1, demo-2) is generated based on order
                            public_demo_chats = []
                            for idx, demo in enumerate(demo_chats):
                                demo_uuid = demo["id"]  # UUID from Directus
                                display_id = f"demo-{idx + 1}"  # Generated display ID
                                
                                # Warm translation cache using UUID
                                translation = await app.state.directus_service.demo_chat.get_demo_chat_translation_by_uuid(demo_uuid, lang)
                                if not translation and lang != "en":
                                    translation = await app.state.directus_service.demo_chat.get_demo_chat_translation_by_uuid(demo_uuid, "en")
                                
                                if translation:
                                    # Get translation metadata (stored as cleartext)
                                    title = translation.get("title")
                                    summary = translation.get("summary")
                                    follow_up_suggestions = []

                                    # Parse follow-up suggestions from cleartext
                                    if translation.get("follow_up_suggestions"):
                                        try:
                                            import json as json_module
                                            follow_up_suggestions = json_module.loads(translation["follow_up_suggestions"])
                                        except Exception as followup_err:
                                            logger.warning(f"Failed to parse follow_up_suggestions for demo {demo_uuid}: {followup_err}")

                                    # Get category and icon from demo_chats table (stored as cleartext)
                                    category = demo.get("category")
                                    icon = demo.get("icon")

                                    # Add to list with cleartext data
                                    public_demo_chats.append({
                                        "demo_id": display_id,
                                        "uuid": demo_uuid,
                                        "title": title or "Demo Chat",
                                        "summary": summary,
                                        "category": category,
                                        "icon": icon,
                                        "content_hash": demo.get("content_hash", ""),
                                        "created_at": demo.get("created_at"),
                                        "status": demo.get("status")
                                    })
                                    
                                    # Warm individual chat data cache using UUID
                                    messages = await app.state.directus_service.demo_chat.get_demo_messages_by_uuid(demo_uuid, lang)
                                    if not messages and lang != "en":
                                        messages = await app.state.directus_service.demo_chat.get_demo_messages_by_uuid(demo_uuid, "en")
                                        
                                    embeds = await app.state.directus_service.demo_chat.get_demo_embeds_by_uuid(demo_uuid, lang)
                                    if not embeds and lang != "en":
                                        embeds = await app.state.directus_service.demo_chat.get_demo_embeds_by_uuid(demo_uuid, "en")
                                    
                                    # Get messages (stored as cleartext)
                                    cleartext_messages = []
                                    for msg in (messages or []):
                                        cleartext_messages.append({
                                            "message_id": str(msg.get("id")),
                                            "role": msg.get("role"),
                                            "content": msg.get("content", ""),
                                            "category": msg.get("category"),
                                            "model_name": msg.get("model_name"),
                                            "created_at": msg.get("original_created_at")  # Use original_created_at for ordering
                                        })

                                    # Get embeds (stored as cleartext)
                                    cleartext_embeds = []
                                    for emb in (embeds or []):
                                        cleartext_embeds.append({
                                            "embed_id": emb.get("original_embed_id"),
                                            "type": emb.get("type"),
                                            "content": emb.get("content", ""),
                                            "created_at": emb.get("original_created_at")  # Use original_created_at for ordering
                                        })

                                    full_chat_data = {
                                        "demo_id": display_id,
                                        "title": title,
                                        "summary": summary,
                                        "category": category,
                                        "icon": icon,
                                        "content_hash": demo.get("content_hash", ""),
                                        "follow_up_suggestions": follow_up_suggestions,
                                        "chat_data": {
                                            "chat_id": display_id,  # Use display_id as chat_id for client
                                            "messages": cleartext_messages,
                                            "embeds": cleartext_embeds,
                                            "encryption_mode": "none"
                                        }
                                    }
                                    
                                    # Store in cache using display_id as key
                                    await app.state.directus_service.cache.set_demo_chat_data(display_id, lang, full_chat_data)

                            # Store list in cache
                            response_data = {
                                "demo_chats": public_demo_chats,
                                "count": len(public_demo_chats)
                            }
                            await app.state.directus_service.cache.set_demo_chats_list(lang, response_data)

                    logger.info(f"✅ Demo chats cache warmed for {len(TARGET_LANGUAGES)} languages")
                except Exception as e:
                    logger.warning(f"Failed to warm demo chats cache: {e}", exc_info=True)
            
            asyncio.create_task(warm_demo_cache())
        except Exception as demo_warm_err:
            logger.warning(f"Error during demo cache warming setup: {demo_warm_err}")

        # Log task status after a short delay to verify it was accepted
        async def check_task_status():
            await asyncio.sleep(2)  # Wait 2 seconds for task to be picked up
            try:
                # Check if task is in queue or being processed
                inspect = celery_app.control.inspect()
                active_tasks = inspect.active()
                scheduled_tasks = inspect.scheduled()
                reserved_tasks = inspect.reserved()
                
                if active_tasks or scheduled_tasks or reserved_tasks:
                    logger.debug(f"Celery workers status - Active: {active_tasks}, Scheduled: {scheduled_tasks}, Reserved: {reserved_tasks}")
                else:
                    logger.warning("No active Celery workers detected. Health check task may not execute until workers are available.")
            except Exception as inspect_error:
                logger.warning(f"Could not inspect Celery worker status: {inspect_error}")
        
        # Check task status in background (non-blocking)
        asyncio.create_task(check_task_status())
    except Exception as e:
        logger.error(f"Failed to trigger initial health check: {e}. Health checks will run on schedule.", exc_info=True)

        # Trigger initial app health check on startup
        logger.info("Triggering initial app health check for all apps...")
        try:
            # Trigger the app health check task asynchronously (non-blocking)
            app_task_result = celery_app.send_task(
                "health_check.check_all_apps",
                queue="health_check"
            )
            logger.info(f"Initial app health check task queued successfully. Task ID: {app_task_result.id}")
        except Exception as e:
            logger.error(f"Failed to trigger initial app health check: {e}. App health checks will run on schedule.", exc_info=True)
    except Exception as e:
        logger.error(f"Failed to initialize: {str(e)}", exc_info=True)

    # Start Redis Pub/Sub listener task
    logger.info("Starting Redis Pub/Sub listener for cache events as a background task...")
    app.state.redis_pubsub_listener_task = asyncio.create_task(listen_for_cache_events(app))
    
    logger.info("Starting Redis Pub/Sub listener for AI chat streams as a background task...")
    app.state.ai_chat_stream_listener_task = asyncio.create_task(listen_for_ai_chat_streams(app))

    logger.info("Starting Redis Pub/Sub listener for AI thinking streams as a background task...")
    app.state.ai_thinking_stream_listener_task = asyncio.create_task(listen_for_ai_thinking_streams(app))

    logger.info("Starting Redis Pub/Sub listener for AI message persisted events as a background task...")
    app.state.ai_message_persisted_listener_task = asyncio.create_task(listen_for_ai_message_persisted_events(app))

    logger.info("Starting Redis Pub/Sub listener for AI typing indicator events as a background task...")
    app.state.ai_typing_indicator_listener_task = asyncio.create_task(listen_for_ai_typing_indicator_events(app))

    logger.info("Starting Redis Pub/Sub listener for chat update events as a background task...")
    app.state.chat_updates_listener_task = asyncio.create_task(listen_for_chat_updates(app))

    logger.info("Starting Redis Pub/Sub listener for user update events as a background task...")
    app.state.user_updates_listener_task = asyncio.create_task(listen_for_user_updates(app))

    logger.info("Starting Redis Pub/Sub listener for embed data events as a background task...")
    app.state.embed_data_listener_task = asyncio.create_task(listen_for_embed_data_events(app))

    yield  # This is where FastAPI serves requests
    
    # Shutdown logic
    logger.info("Shutting down application...")
    
    # --- Persist pending payment orders to disk before shutdown ---
    # This ensures payment orders survive restarts and can be restored on next startup
    # Critical for preventing payment data loss when webhook arrives after cache is cleared
    if hasattr(app.state, 'cache_service'):
        try:
            dumped_count = await app.state.cache_service.dump_pending_orders_to_disk()
            if dumped_count > 0:
                logger.info(f"Persisted {dumped_count} pending payment orders to disk for recovery after restart")
        except Exception as e:
            logger.error(f"Error persisting payment orders to disk during shutdown: {e}", exc_info=True)
    
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

    if hasattr(app.state, 'user_updates_listener_task'):
        app.state.user_updates_listener_task.cancel()
        try:
            await app.state.user_updates_listener_task
        except asyncio.CancelledError:
            logger.info("Redis Pub/Sub listener task for user updates cancelled")

    if hasattr(app.state, 'embed_data_listener_task'):
        app.state.embed_data_listener_task.cancel()
        try:
            await app.state.embed_data_listener_task
        except asyncio.CancelledError:
            logger.info("Redis Pub/Sub listener task for embed data events cancelled")
            
    # Close encryption service client
    if hasattr(app.state, 'encryption_service'):
        await app.state.encryption_service.close()
        
    # Close Payment service client
    if hasattr(app.state, 'payment_service'):
        await app.state.payment_service.close()

    # Close InvoiceNinja service client
    if hasattr(app.state, 'invoice_ninja_service'):
        await app.state.invoice_ninja_service.close()
        
    # Close Directus service client
    if hasattr(app.state, 'directus_service'):
        await app.state.directus_service.close()

# Create FastAPI application with lifespan
def create_app() -> FastAPI:
    app = FastAPI(
        title="OpenMates API",
        description="First version of the OpenMates API. Work in progress. Will be extended and new docs design implemented in the weeks to come.",
        version="0.1.0",
        lifespan=lifespan,
        docs_url="/docs",  # Enable Swagger UI documentation
        redoc_url=None  # ReDoc disabled - using custom Swagger UI design instead
    )
    
    # Customize OpenAPI schema to include security scheme for API key authentication
    # This enables the "Authorize" button in Swagger UI
    
    def custom_openapi():
        if app.openapi_schema:
            return app.openapi_schema
        openapi_schema = get_openapi(
            title=app.title,
            version=app.version,
            description=app.description,
            routes=app.routes,
        )
        # Add security scheme for API key authentication (Bearer token)
        # This will make the "Authorize" button appear in Swagger UI
        if "components" not in openapi_schema:
            openapi_schema["components"] = {}
        # The security scheme name must match the scheme_name in HTTPBearer
        openapi_schema["components"]["securitySchemes"] = {
            "API Key": {
                "type": "http",
                "scheme": "bearer",
                "bearerFormat": "JWT",  # Swagger UI expects this format
                "description": "Enter your API key. API keys start with 'sk-api-'. Use format: Bearer sk-api-..."
            }
        }
        
        # Note: OpenAPI schemas are now automatically generated from the skill's Pydantic models
        # (SearchRequest, SearchResponse, etc.) which are imported directly from the skill modules.
        # No manual customization needed - FastAPI handles this automatically.
        
        app.openapi_schema = openapi_schema
        return app.openapi_schema
    
    app.openapi = custom_openapi

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
    default_dev_origins_str = "http://localhost:5173, https://app.dev.openmates.org"
    default_prod_origin_str = "https://openmates.org"

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

    # 3. Validate CORS configuration for production environment
    # In production, we require at least one HTTPS URL that is not localhost
    if not is_dev:
        from urllib.parse import urlparse
        
        # Check if there's at least one non-localhost HTTPS URL
        has_production_url = False
        localhost_urls = []
        non_https_urls = []
        
        for origin in allowed_origins:
            try:
                parsed = urlparse(origin)
                hostname = parsed.hostname or ""
                
                # Check if it's localhost
                if hostname.lower() in ["localhost", "127.0.0.1", "::1", "0.0.0.0"]:
                    localhost_urls.append(origin)
                # Check if it's HTTPS
                elif parsed.scheme.lower() == "https":
                    has_production_url = True
                else:
                    non_https_urls.append(origin)
            except Exception:
                # Invalid URL format - will be caught by CORS middleware anyway
                pass
        
        if not has_production_url:
            env_var_name = "PRODUCTION_URL"
            env_var_value = os.getenv(env_var_name, "(NOT SET)")
            
            error_msg = (
                "=" * 80 + "\n"
                "🚨 CORS CONFIGURATION ERROR - MISSING PRODUCTION HTTPS URL 🚨\n"
                f"Environment: PRODUCTION\n"
                f"Configured URLs: {', '.join(allowed_origins) if allowed_origins else '(NONE)'}\n"
                f"Environment Variable: {env_var_name}\n"
                f"Current Value: {env_var_value}\n"
            )
            
            if localhost_urls:
                error_msg += f"\n⚠️  Found localhost URLs (not suitable for production): {', '.join(localhost_urls)}\n"
            if non_https_urls:
                error_msg += f"\n⚠️  Found non-HTTPS URLs: {', '.join(non_https_urls)}\n"
            
            error_msg += (
                "\n"
                "⚠️  IMPACT: CORS requests from production frontend will FAIL!\n"
                "   - API requests will return 403 Forbidden\n"
                "   - OPTIONS preflight requests will fail\n"
                "   - Frontend will not be able to communicate with the API\n"
                "\n"
                "🔧 FIX: Set PRODUCTION_URL to your production frontend URL:\n"
                f"   {env_var_name}=\"https://your-domain.com\"\n"
                "   (For multiple URLs, separate with commas)\n"
                "=" * 80
            )
            
            logger.error(error_msg)
            # Also log as warning for less critical visibility
            logger.warning(
                "CORS validation failed: No HTTPS production URL found. "
                "PRODUCTION_URL must contain at least one HTTPS URL that is not localhost."
            )
        else:
            logger.info("✅ CORS configuration validation passed: Production HTTPS URL found")

    # 4. Log the final list
    logger.info(f"Final allowed origins configured: {allowed_origins}")

    # Make allowed_origins accessible outside this module
    # This enables auth endpoints to validate origins
    app.state.allowed_origins = allowed_origins

    # Configure CORS with the allowed origins
    # expose_headers is required to allow frontend to read response headers like Content-Disposition
    # This is needed for file downloads (invoices, credit notes) where the filename is in the header
    app.add_middleware(
        CORSMiddleware,
        allow_origins=allowed_origins,
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
        expose_headers=["Content-Disposition"],  # Expose Content-Disposition header for file downloads
    )

    # Add ProxyHeadersMiddleware to handle X-Forwarded-* headers
    # TRUSTED_PROXY_IPS should be a comma-separated string of trusted proxy IPs/CIDRs
    # Defaulting to "*" trusts all proxies (use with caution in production)
    trusted_hosts = os.getenv("TRUSTED_PROXY_IPS", "*").split(",")
    app.add_middleware(ProxyHeadersMiddleware, trusted_hosts=trusted_hosts)

    # Include routers
    # By default, all routers are excluded from OpenAPI schema (include_in_schema=False)
    # Only routers explicitly marked with include_in_schema=True will appear in API documentation
    # This ensures endpoints are not exposed to API users unless explicitly intended
    
    # Internal/web app routers - excluded from API schema (web app only, not for API access)
    app.include_router(auth.router, include_in_schema=False)  # Auth endpoints - web app only
    app.include_router(email.router, include_in_schema=False)  # Email endpoints - web app only
    
    # Conditionally register payment-related routers (only if payment is enabled)
    # Note: We call is_payment_enabled() directly here because app.state.payment_enabled
    # is only set during lifespan startup, which happens after create_app() returns.
    # This ensures the payment router is registered correctly based on domain/environment.
    payment_enabled = is_payment_enabled()
    
    if payment_enabled:
        app.include_router(invoice.router, include_in_schema=False)  # Invoice endpoints - web app only
        app.include_router(credit_note.router, include_in_schema=False)  # Credit note endpoints - web app only
        app.include_router(payments.router, include_in_schema=False)  # Payments endpoints - web app only
        logger.info("Payment-related routes registered (payment enabled)")
    else:
        logger.info("Skipping payment-related routes (payment disabled - self-hosted mode)")
    
    # Web app only routers - excluded from API schema (use web app auth, not API keys)
    app.include_router(websockets.router, include_in_schema=False)  # WebSocket endpoints - web app only
    app.include_router(internal_api.router, include_in_schema=False)  # Internal API router - service-to-service communication only
    app.include_router(apps.router, include_in_schema=False)  # Apps router - public endpoint, not API key based
    app.include_router(share.router, include_in_schema=False)  # Share router - web app only
    app.include_router(demo_chat.router, include_in_schema=False)  # Demo chat router - public access
    app.include_router(admin.router, include_in_schema=False)  # Admin router - authenticated admin only
    app.include_router(admin_debug.router, include_in_schema=False)  # Admin debug router - requires admin API key, not in public docs
    app.include_router(newsletter.router, include_in_schema=False)  # Newsletter endpoints - web app only (uses verify_allowed_origin)
    app.include_router(email_block.router, include_in_schema=False)  # Email blocking endpoints - web app only (uses verify_allowed_origin)
    
    # API routers - explicitly included in schema (support API key authentication)
    from backend.core.api.app.routes import tasks_api
    from backend.core.api.app.routes import embeds_api
    app.include_router(settings.router, include_in_schema=True)  # Settings endpoints - some endpoints support API key auth
    app.include_router(apps_api.router, include_in_schema=True)  # Apps API router - uses API key authentication for external API access
    app.include_router(tasks_api.router, include_in_schema=True)  # Tasks API router - uses API key authentication for polling long-running tasks
    app.include_router(embeds_api.router, include_in_schema=True)  # Embeds API router - uses API key authentication for downloading embed files (images, etc.)
    from backend.core.api.app.routes import usage_api
    app.include_router(usage_api.router, include_in_schema=True)  # Usage API router - supports both session and API key auth
    
    # Conditionally register creators router (only if payment is enabled - tips require payment)
    if payment_enabled:
        app.include_router(creators.router, include_in_schema=True)  # Creators router - requires authentication, supports API keys
        logger.info("Creators router registered (payment enabled)")
    else:
        logger.info("Skipping creators router (payment disabled - tips require payment)")

    # Redirect /health to /v1/health for backward compatibility
    @app.get("/health", include_in_schema=False)
    async def health_redirect():
        """Redirect /health to /v1/health for backward compatibility."""
        return RedirectResponse(url="/v1/health", status_code=301)
    
    # Health check endpoint with rate limiting
    # Included in OpenAPI docs - useful public endpoint for monitoring
    # Note: This endpoint does NOT require API key authentication (public endpoint)
    @app.get("/v1/health", dependencies=[])  # Explicitly no dependencies (no auth required)
    @limiter.limit("60/minute")
    async def health_check_v1(request: Request):
        """
        Health check endpoint that includes provider health status.
        
        Only includes apps that are in discovered_apps_metadata (already filtered by stage during server startup).
        This ensures consistency with /v1/apps/metadata endpoint behavior.
        
        Stage filtering rules:
        - Production server: Only apps with stage 'production' components
        - Development server: Apps with stage 'development' or 'production' components
        - Other stages are always ignored
        """
        from backend.core.api.app.services.cache import CacheService
        import json
        
        # Get discovered apps from app state (already filtered by stage during startup)
        # This ensures we only return health status for apps that should be included
        discovered_app_ids = set()
        if hasattr(request.app.state, 'discovered_apps_metadata'):
            discovered_app_ids = set(request.app.state.discovered_apps_metadata.keys())
            logger.debug(f"Health check: Filtering apps by discovered_apps_metadata. Found {len(discovered_app_ids)} app(s): {sorted(discovered_app_ids)}")
        else:
            logger.warning("Health check: discovered_apps_metadata not found in app.state. All apps from cache will be included.")
        
        # Get provider, app, and external service health status from cache
        providers_health = {}
        apps_health = {}
        external_services_health = {}
        try:
            cache_service = CacheService()
            client = await cache_service.client
            if client:
                # Get all provider health check keys
                # Pattern: health_check:provider:{provider_id}
                provider_health_keys = await client.keys("health_check:provider:*")
                for key in provider_health_keys:
                    if isinstance(key, bytes):
                        key = key.decode('utf-8')
                    # Extract provider_id from key
                    provider_id = key.replace("health_check:provider:", "")
                    health_data_json = await client.get(key)
                    if health_data_json:
                        if isinstance(health_data_json, bytes):
                            health_data_json = health_data_json.decode('utf-8')
                        health_data = json.loads(health_data_json)
                        providers_health[provider_id] = {
                            "status": health_data.get("status", "unknown"),
                            "last_check": health_data.get("last_check"),
                            "last_error": health_data.get("last_error"),
                            "response_times_ms": health_data.get("response_times_ms", {})
                        }

                # Get all app health check keys, but only include apps from discovered_apps_metadata
                # Pattern: health_check:app:{app_id}
                app_health_keys = await client.keys("health_check:app:*")
                for key in app_health_keys:
                    if isinstance(key, bytes):
                        key = key.decode('utf-8')
                    # Extract app_id from key
                    app_id = key.replace("health_check:app:", "")

                    # Only include apps that are in discovered_apps_metadata (already stage-filtered)
                    # If discovered_apps_metadata is empty/not available, include all apps (fallback behavior)
                    if discovered_app_ids and app_id not in discovered_app_ids:
                        logger.debug(f"Health check: Excluding app '{app_id}' from health status (not in discovered_apps_metadata - likely filtered by stage)")
                        continue

                    health_data_json = await client.get(key)
                    if health_data_json:
                        if isinstance(health_data_json, bytes):
                            health_data_json = health_data_json.decode('utf-8')
                        health_data = json.loads(health_data_json)
                        apps_health[app_id] = {
                            "status": health_data.get("status", "unknown"),
                            "api": health_data.get("api", {}),
                            "worker": health_data.get("worker", {}),
                            "last_check": health_data.get("last_check")
                        }

                # Get all external service health check keys
                # Pattern: health_check:external:{service_id}
                external_health_keys = await client.keys("health_check:external:*")
                for key in external_health_keys:
                    if isinstance(key, bytes):
                        key = key.decode('utf-8')
                    # Extract service_id from key
                    service_id = key.replace("health_check:external:", "")
                    health_data_json = await client.get(key)
                    if health_data_json:
                        if isinstance(health_data_json, bytes):
                            health_data_json = health_data_json.decode('utf-8')
                        health_data = json.loads(health_data_json)
                        external_services_health[service_id] = {
                            "status": health_data.get("status", "unknown"),
                            "last_check": health_data.get("last_check"),
                            "last_error": health_data.get("last_error"),
                            "response_times_ms": health_data.get("response_times_ms", {})
                        }
        except Exception as e:
            logger.error(f"Error fetching health status: {e}", exc_info=True)

        # Determine overall status
        overall_status = "healthy"
        unhealthy_providers = sum(1 for p in providers_health.values() if p.get("status") == "unhealthy")
        unhealthy_apps = sum(1 for a in apps_health.values() if a.get("status") == "unhealthy")
        unhealthy_external = sum(1 for e in external_services_health.values() if e.get("status") == "unhealthy")
        degraded_apps = sum(1 for a in apps_health.values() if a.get("status") == "degraded")

        if unhealthy_providers > 0 or unhealthy_apps > 0 or unhealthy_external > 0:
            total_services = len(providers_health) + len(apps_health) + len(external_services_health)
            unhealthy_total = unhealthy_providers + unhealthy_apps + unhealthy_external
            if unhealthy_total < total_services:
                overall_status = "degraded"
            else:
                overall_status = "unhealthy"
        elif degraded_apps > 0:
            overall_status = "degraded"

        return {
            "status": overall_status,
            "providers": providers_health,
            "apps": apps_health,
            "external_services": external_services_health
        }

    # Health history endpoint - provides historical health data for incident analysis
    # Public endpoint (no auth required) - enables status pages and monitoring
    @app.get("/v1/health/history", dependencies=[])  # No dependencies (public endpoint)
    @limiter.limit("60/minute")
    async def health_history(
        request: Request,
        service_type: Optional[str] = None,
        service_id: Optional[str] = None,
        since: Optional[int] = None,
        limit: int = 100
    ):
        """
        Get historical health events for incident analysis.
        
        This endpoint returns health status change events, allowing you to see
        when and how often services went down over time. Only status transitions
        are recorded (e.g., healthy → unhealthy), not every health check.
        
        Query Parameters:
            service_type: Filter by service type ('provider', 'app', 'external')
            service_id: Filter by service identifier (e.g., 'openrouter', 'ai', 'stripe')
            since: Only include events after this Unix timestamp
            limit: Maximum number of events to return (default 100, max 1000)
        
        Returns:
            Dict with:
            - events: List of health events sorted by created_at descending
            - total: Number of events returned
            - filters: Applied filters
        """
        from backend.core.api.app.services.directus import DirectusService
        from backend.core.api.app.services.cache import CacheService
        
        # Validate service_type if provided
        valid_service_types = {'provider', 'app', 'external'}
        if service_type and service_type not in valid_service_types:
            from fastapi import HTTPException
            raise HTTPException(
                status_code=400, 
                detail=f"Invalid service_type. Must be one of: {', '.join(valid_service_types)}"
            )
        
        # Query health events
        directus = DirectusService(cache_service=CacheService())
        try:
            events = await directus.health_event.get_health_history(
                service_type=service_type,
                service_id=service_id,
                since_timestamp=since,
                limit=min(max(1, limit), 1000)
            )
            
            return {
                "events": events,
                "total": len(events),
                "filters": {
                    "service_type": service_type,
                    "service_id": service_id,
                    "since": since,
                    "limit": limit
                }
            }
        finally:
            await directus.close()

    # Health incident summary endpoint - provides aggregated incident statistics
    # Public endpoint (no auth required) - enables status pages and monitoring
    @app.get("/v1/health/incidents", dependencies=[])  # No dependencies (public endpoint)
    @limiter.limit("60/minute")
    async def health_incident_summary(
        request: Request,
        service_type: Optional[str] = None,
        since: Optional[int] = None
    ):
        """
        Get aggregated incident statistics for all services.
        
        This endpoint provides a summary view of service incidents, including:
        - Total incident count per service
        - Total downtime duration per service
        - Last incident timestamp
        
        Query Parameters:
            service_type: Filter by service type ('provider', 'app', 'external')
            since: Only include events after this Unix timestamp
        
        Returns:
            Dict with incident statistics aggregated by service.
        """
        from backend.core.api.app.services.directus import DirectusService
        from backend.core.api.app.services.cache import CacheService
        
        # Validate service_type if provided
        valid_service_types = {'provider', 'app', 'external'}
        if service_type and service_type not in valid_service_types:
            from fastapi import HTTPException
            raise HTTPException(
                status_code=400, 
                detail=f"Invalid service_type. Must be one of: {', '.join(valid_service_types)}"
            )
        
        # Get incident summary
        directus = DirectusService(cache_service=CacheService())
        try:
            summary = await directus.health_event.get_incident_summary(
                since_timestamp=since,
                service_type=service_type
            )
            return summary
        finally:
            await directus.close()

    # Server information endpoint - public endpoint (no auth required)
    # Included in OpenAPI docs - useful for clients to determine server type
    @app.get("/v1/server", dependencies=[])  # Explicitly no dependencies (no auth required)
    @limiter.limit("60/minute")
    async def server_info(request: Request):
        """
        Get server information including domain and self-hosted status.
        
        This endpoint uses request-based validation to determine if the server
        is the official instance or self-hosted. It extracts the domain from
        the request headers (Origin or Host) and validates it against the
        official domain from encrypted config.
        
        This approach is more secure than environment variable-based detection
        because it validates the actual request domain, making it harder for
        malicious actors to spoof the official instance.
        
        Returns:
            Dict with:
            - "domain": The domain extracted from the request (None for localhost)
            - "self_hosted": Boolean indicating if this is a self-hosted instance
              (True if domain doesn't match official domain or is localhost)
            - "edition": Server edition string ("production" | "development" | "self_hosted")
              - "production": Official domain or non-dev subdomain
              - "development": *.dev.{official_domain} subdomain
              - "self_hosted": Other domains or localhost
        """
        from backend.core.api.app.utils.server_mode import validate_request_domain
        
        # Validate request domain against official domain
        # This uses request headers (Origin/Host) for security validation
        domain, is_self_hosted, edition = validate_request_domain(request)
        
        logger.debug(
            f"Server info requested: domain={domain}, self_hosted={is_self_hosted}, "
            f"edition={edition}, origin={request.headers.get('origin')}, host={request.headers.get('host')}"
        )
        
        return {
            "domain": domain,
            "self_hosted": is_self_hosted,
            "edition": edition
        }

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

async def preload_gift_cards(app_state):
    """Load all unredeemed gift cards into cache for faster lookup"""
    directus_service = app_state.directus_service 
    cache_service = app_state.cache_service
    
    all_gift_cards = await directus_service.get_all_gift_cards()
    if not all_gift_cards:
        logger.warning("No gift cards found to preload")
        return
    
    imported_count = 0
    skipped_count = 0
    
    # Cache each gift card with its data
    for gift_card_data in all_gift_cards:
        code = gift_card_data.get("code")
        if code:
            # Use the gift card code as the key
            cache_key = f"gift_card:{code}"
            
            # Check if gift card already exists in cache
            existing_data = await cache_service.get(cache_key)
            if existing_data is None:
                # Only add to cache if it doesn't already exist
                await cache_service.set(cache_key, gift_card_data)
                imported_count += 1
            else:
                skipped_count += 1
    
    logger.info(f"Preloaded {imported_count} new gift cards into cache (skipped {skipped_count} existing cards)")

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
