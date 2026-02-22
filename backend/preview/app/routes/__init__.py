# Preview Server Routes
# API endpoints for image/favicon proxying and metadata extraction.
#
# Note: /admin/* endpoints (logs, update) are intentionally NOT registered here.
# They are handled by the separate admin-sidecar container which has Docker socket
# access. This keeps the Docker socket out of the main preview container.

from .favicon import router as favicon_router
from .image import router as image_router
from .metadata import router as metadata_router
from .youtube import router as youtube_router
from .health import router as health_router

__all__ = [
    "favicon_router",
    "image_router",
    "metadata_router",
    "youtube_router",
    "health_router",
]

