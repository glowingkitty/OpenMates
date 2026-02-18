# backend/shared/providers/google_maps/static_maps.py
#
# Google Maps Static API provider.
# Generates static map images centered on a specific coordinate.
#
# Documentation: https://developers.google.com/maps/documentation/maps-static
#
# The static map image is used to create a visual preview of a location embed
# (maps.location skill). The image is stored in S3 and referenced by the embed.
#
# API Key:
# - Shares the same Google Maps Platform API key as google_places.py
# - Key is fetched from Vault (kv/data/providers/google_maps / api_key)
#   with fallback to the SECRET__GOOGLE_MAPS__API_KEY environment variable.

import logging
import httpx

from backend.core.api.app.utils.secrets_manager import SecretsManager
from backend.shared.providers.google_maps.google_places import _get_google_maps_api_key

logger = logging.getLogger(__name__)

# Google Maps Static API base URL
STATIC_MAPS_API_URL = "https://maps.googleapis.com/maps/api/staticmap"

# Default map parameters
DEFAULT_MAP_SIZE = "600x400"       # Width x Height in pixels
DEFAULT_MAP_ZOOM = 15              # Default zoom level (street level)
DEFAULT_MAP_SCALE = 2              # Retina/high-DPI scale (1 or 2)
DEFAULT_MAP_MAP_TYPE = "roadmap"   # Map type: roadmap, satellite, terrain, hybrid
DEFAULT_MARKER_COLOR = "red"       # Marker color


async def generate_static_map_image(
    latitude: float,
    longitude: float,
    secrets_manager: SecretsManager,
    zoom: int = DEFAULT_MAP_ZOOM,
    size: str = DEFAULT_MAP_SIZE,
    scale: int = DEFAULT_MAP_SCALE,
    map_type: str = DEFAULT_MAP_MAP_TYPE,
    marker_color: str = DEFAULT_MARKER_COLOR,
) -> bytes:
    """
    Generate a static map image for a given coordinate using the Google Maps Static API.

    The image is returned as raw PNG bytes ready for upload to S3.

    Args:
        latitude: Latitude of the map center (also used for the marker).
        longitude: Longitude of the map center (also used for the marker).
        secrets_manager: SecretsManager instance for API key retrieval.
        zoom: Zoom level 0–21 (default 15 = street level).
        size: Image dimensions as "{width}x{height}" (default "600x400").
        scale: Image scale — 1 (standard) or 2 (retina/high-DPI).
        map_type: Map rendering style: roadmap | satellite | terrain | hybrid.
        marker_color: Color of the map pin (default "red").

    Returns:
        Raw PNG image bytes.

    Raises:
        ValueError: If the Google Maps API key is not available.
        httpx.HTTPStatusError: If the Static Maps API returns a non-2xx status.
        Exception: For any other unexpected error.
    """
    api_key = await _get_google_maps_api_key(secrets_manager)
    if not api_key:
        raise ValueError(
            "Google Maps API key not available. "
            "Please configure it in Vault or set SECRET__GOOGLE_MAPS__API_KEY."
        )

    # Build query parameters
    params = {
        "center": f"{latitude},{longitude}",
        "zoom": str(zoom),
        "size": size,
        "scale": str(scale),
        "maptype": map_type,
        "markers": f"color:{marker_color}|{latitude},{longitude}",
        "key": api_key,
    }

    masked_key = f"{api_key[:4]}****{api_key[-4:]}" if len(api_key) > 8 else "****"
    logger.debug(
        f"Generating static map: center={latitude},{longitude} "
        f"zoom={zoom} size={size} scale={scale} api_key={masked_key}"
    )

    async with httpx.AsyncClient(timeout=30.0) as client:
        response = await client.get(STATIC_MAPS_API_URL, params=params)
        response.raise_for_status()

        content_type = response.headers.get("content-type", "")
        if "image" not in content_type:
            # Google returns a plain-text or HTML error body with HTTP 200 for some
            # API errors (e.g. quota exceeded, invalid key). Detect and raise.
            raise ValueError(
                f"Static Maps API returned non-image content-type '{content_type}': "
                f"{response.text[:200]}"
            )

        image_bytes = response.content
        logger.info(
            f"Static map image generated: {len(image_bytes)} bytes, "
            f"center=({latitude},{longitude}) zoom={zoom}"
        )
        return image_bytes
