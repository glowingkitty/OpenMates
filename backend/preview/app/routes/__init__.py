# Preview Server Routes
# API endpoints for image/favicon proxying and metadata extraction

from .admin_logs import router as admin_logs_router
from .favicon import router as favicon_router
from .image import router as image_router
from .metadata import router as metadata_router
from .youtube import router as youtube_router
from .health import router as health_router

__all__ = [
    "admin_logs_router",
    "favicon_router",
    "image_router",
    "metadata_router",
    "youtube_router",
    "health_router",
]

