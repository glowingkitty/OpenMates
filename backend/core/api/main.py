import os
import uvicorn
import logging
from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from dotenv import load_dotenv
from contextlib import asynccontextmanager
from slowapi import _rate_limit_exceeded_handler
from slowapi.errors import RateLimitExceeded

from app.routes import auth
from app.services.directus import DirectusService
from app.services.cache import CacheService
from app.services.limiter import limiter

# Set up logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# Load environment variables
load_dotenv()

# Check crucial environment variables
cms_token = os.getenv("CMS_TOKEN")
if not cms_token:
    logger.warning("CMS_TOKEN environment variable is not set. Authentication with Directus will fail.")

# Initialize services
cache_service = CacheService()
directus_service = DirectusService(cache_service=cache_service)

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

# Add rate limiting exception handler
app.state.limiter = limiter
app.add_exception_handler(RateLimitExceeded, _rate_limit_exceeded_handler)

# Configure CORS with proper origin restrictions
is_dev = os.getenv("SERVER_ENVIRONMENT", "development") == "development"
allowed_origins = [
    os.getenv("FRONTEND_URL", "http://localhost:5174") if is_dev else
    os.getenv("PRODUCTION_URL", "https://app.openmates.org")
]
logger.debug(f"Allowed origins: {allowed_origins}")

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
    uvicorn.run("main:app", host="0.0.0.0", port=port, reload=True)
