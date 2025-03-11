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

from app.routes import auth
from app.services.directus import DirectusService
from app.services.cache import CacheService
from app.services.metrics import MetricsService
from app.services.limiter import limiter
from app.middleware.logging_middleware import LoggingMiddleware

# Set up structured logging - INFO for console output, WARNING for files
log_level = os.getenv("LOG_LEVEL", "INFO")  # Keep INFO as default for console
logging.basicConfig(level=log_level)
logger = logging.getLogger(__name__)

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
# More aggressively filter logs for the file handler
api_handler.setLevel(logging.WARNING)  # Only WARNING and above in files
root_logger.addHandler(api_handler)

# Create a special event logger for business events (like invite code checks)
event_logger = logging.getLogger("app.events")
event_logger.propagate = False  # Don't send to root logger
event_handler = logging.FileHandler(api_log_path)
event_handler.setFormatter(log_formatter)
event_handler.setLevel(logging.INFO)  # Allow INFO level for specific events
event_logger.addHandler(event_handler)
# Add console output for events as well
event_console = logging.StreamHandler()
event_console.setFormatter(log_formatter)
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
compliance_logger.addHandler(compliance_handler)

# Load environment variables
load_dotenv()

# Check crucial environment variables
cms_token = os.getenv("CMS_TOKEN")
if not cms_token:
    logger.warning("CMS_TOKEN environment variable is not set. Authentication with Directus will fail.")

# Initialize services
cache_service = CacheService()
directus_service = DirectusService(cache_service=cache_service)
metrics_service = MetricsService()

# Define lifespan context manager for startup/shutdown events
@asynccontextmanager
async def lifespan(app: FastAPI):
    # Startup logic
    logger.info("Preloading invite codes into cache...")
    try:
        await preload_invite_codes()
        logger.info("Successfully preloaded invite codes into cache")
    except Exception as e:
        logger.error(f"Failed to preload invite codes: {str(e)}", exc_info=True)
    
    yield  # This is where FastAPI serves requests
    
    # Shutdown logic (if any)
    logger.info("Shutting down application...")

# Create FastAPI application with lifespan
app = FastAPI(
    title="OpenMates API",
    description="API for OpenMates platform",
    version="0.1.0",
    lifespan=lifespan
)

# Create metrics endpoint
metrics_app = make_asgi_app()
app.mount("/metrics", metrics_app)

# Add rate limiting exception handler
app.state.limiter = limiter
app.add_exception_handler(RateLimitExceeded, _rate_limit_exceeded_handler)

# Add logging middleware
app.add_middleware(LoggingMiddleware, metrics_service=metrics_service)

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

async def preload_invite_codes():
    """Load all invite codes into cache for faster lookup"""
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

# Include routers
app.include_router(auth.router)

# Health check endpoint with rate limiting
@app.get("/health")
@limiter.limit("60/minute")
async def health_check(request: Request):
    return {"status": "healthy"}

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
