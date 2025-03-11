import os
import uvicorn
import logging
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from dotenv import load_dotenv

from app.routes import auth
from app.services.directus import DirectusService

# Set up logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# Load environment variables
load_dotenv()

# Check crucial environment variables
cms_token = os.getenv("CMS_TOKEN")
if not cms_token:
    logger.warning("CMS_TOKEN environment variable is not set. Authentication with Directus will fail.")

# Create FastAPI application
app = FastAPI(
    title="OpenMates API",
    description="API for OpenMates platform",
    version="0.1.0"
)

# Initialize services
directus_service = DirectusService()

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

# Include routers
app.include_router(auth.router)

# Health check endpoint
@app.get("/health")
def health_check():
    return {"status": "healthy"}

if __name__ == "__main__":
    port = int(os.getenv("REST_API_PORT", "8000"))
    uvicorn.run("main:app", host="0.0.0.0", port=port, reload=True)
