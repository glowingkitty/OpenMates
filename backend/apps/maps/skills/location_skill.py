# backend/apps/maps/skills/location_skill.py
#
# Maps location skill implementation.
# Creates a map location embed from user-provided coordinates.
#
# This skill is invoked when the user selects a location via the MapsView
# interactive map picker in the frontend. The frontend sends the selected
# coordinates (lat, lon, zoom, name) and this skill:
#   1. Generates a static map image via Google Maps Static API
#   2. Uploads the image to S3 (plaintext — no AES encryption needed, it's
#      public-enough map imagery)
#   3. Creates an embed with the location metadata and S3 image URL
#   4. Sends the embed to the client via WebSocket (standard flow)
#
# Architecture:
# - Direct async execution (same pattern as maps.search) — map generation
#   is fast (< 2 s) and does not need a Celery task queue.
# - S3 upload is done using the task's S3 service (chatfiles bucket).
# - The embed content is sent as plaintext TOON; the client encrypts it
#   with the chat master key before storing (standard zero-knowledge flow).
#
# Embed content fields (stored in TOON, encrypted at rest by client):
#   app_id, skill_id, type, status, lat, lon, zoom, name,
#   location_type, map_image_url, map_image_s3_key

import logging
import uuid
import hashlib
from datetime import datetime, timezone
from typing import Dict, Any, Optional

from pydantic import BaseModel, Field

from backend.apps.base_skill import BaseSkill
from backend.core.api.app.utils.secrets_manager import SecretsManager

logger = logging.getLogger(__name__)


class LocationRequest(BaseModel):
    """
    Request model for maps location skill.
    Accepts a single location object with coordinate metadata.
    """
    lat: float = Field(..., description="Latitude of the selected location")
    lon: float = Field(..., description="Longitude of the selected location")
    zoom: int = Field(default=15, description="Map zoom level (0–21, default 15)")
    name: Optional[str] = Field(None, description="Display name for the location (e.g. from reverse geocoding)")
    location_type: Optional[str] = Field(
        None,
        description="Type of location: 'precise_location' or 'area'"
    )


class LocationResponse(BaseModel):
    """Response model for maps location skill."""
    embed_id: Optional[str] = Field(None, description="ID of the created location embed")
    status: str = Field(default="finished", description="Embed status")
    lat: Optional[float] = Field(None, description="Latitude")
    lon: Optional[float] = Field(None, description="Longitude")
    zoom: Optional[int] = Field(None, description="Zoom level")
    name: Optional[str] = Field(None, description="Location name")
    location_type: Optional[str] = Field(None, description="Location type")
    map_image_url: Optional[str] = Field(None, description="Public URL of the static map image")
    error: Optional[str] = Field(None, description="Error message if skill failed")


class LocationSkill(BaseSkill):
    """
    Maps location skill that generates a static map embed from user-selected coordinates.

    This skill is triggered when the user picks a location on the MapsView map picker
    in the frontend. It creates a static map image and stores it as a location embed
    so the AI can see and reason about the selected location.

    Architecture: Direct async execution (not via Celery).
    See search_skill.py class docstring for the reasoning behind this choice.
    """

    def __init__(
        self,
        app,
        app_id: str,
        skill_id: str,
        skill_name: str,
        skill_description: str,
        stage: str = "development",
        full_model_reference: Optional[str] = None,
        pricing_config: Optional[Dict[str, Any]] = None,
        celery_producer=None,
        skill_operational_defaults: Optional[Dict[str, Any]] = None,
    ):
        super().__init__(
            app=app,
            app_id=app_id,
            skill_id=skill_id,
            skill_name=skill_name,
            skill_description=skill_description,
            stage=stage,
            full_model_reference=full_model_reference,
            pricing_config=pricing_config,
            celery_producer=celery_producer,
        )
        if skill_operational_defaults:
            logger.debug(
                f"LocationSkill '{self.skill_name}' received operational_defaults: "
                f"{skill_operational_defaults}"
            )

    def _hash_value(self, value: str) -> str:
        """Create SHA256 hash of a value for privacy protection."""
        return hashlib.sha256(value.encode("utf-8")).hexdigest()

    async def execute(
        self,
        lat: float,
        lon: float,
        zoom: int = 15,
        name: Optional[str] = None,
        location_type: Optional[str] = None,
        embed_id: Optional[str] = None,
        user_id: Optional[str] = None,
        chat_id: Optional[str] = None,
        message_id: Optional[str] = None,
        secrets_manager: Optional[SecretsManager] = None,
        **kwargs,
    ) -> LocationResponse:
        """
        Execute maps location skill: generate static map image and create embed.

        Args:
            lat: Latitude of the selected location.
            lon: Longitude of the selected location.
            zoom: Map zoom level (0–21).
            name: Optional display name for the location.
            location_type: 'precise_location' or 'area'.
            embed_id: Pre-assigned embed ID (from frontend).
            user_id: ID of the requesting user (for S3 path prefix).
            chat_id: Chat ID for WebSocket delivery.
            message_id: Message ID for WebSocket delivery.
            secrets_manager: SecretsManager instance (injected by app).

        Returns:
            LocationResponse with embed metadata.
        """
        # Get or create SecretsManager
        secrets_manager, error_response = await self._get_or_create_secrets_manager(
            secrets_manager=secrets_manager,
            skill_name="LocationSkill",
            error_response_factory=lambda msg: LocationResponse(
                status="error", error=msg
            ),
            logger=logger,
        )
        if error_response:
            return error_response

        # Use pre-assigned embed_id from frontend, or generate a new one
        final_embed_id = embed_id or str(uuid.uuid4())
        log_prefix = f"[LocationSkill embed={final_embed_id}]"

        logger.info(
            f"{log_prefix} Creating location embed: lat={lat}, lon={lon}, "
            f"zoom={zoom}, name={name!r}, type={location_type!r}"
        )

        # ------------------------------------------------------------------ #
        # 1. Generate static map image via Google Maps Static API
        # ------------------------------------------------------------------ #
        map_image_url: Optional[str] = None
        map_image_s3_key: Optional[str] = None

        try:
            from backend.shared.providers.google_maps.static_maps import (
                generate_static_map_image,
            )

            image_bytes = await generate_static_map_image(
                latitude=lat,
                longitude=lon,
                secrets_manager=secrets_manager,
                zoom=zoom,
            )

            # ---------------------------------------------------------------- #
            # 2. Upload image to S3 (chatfiles bucket, unencrypted PNG)
            # ---------------------------------------------------------------- #
            # The image itself is a static OpenStreetMap rendering — not
            # sensitive personal data. We store it unencrypted for simplicity
            # so the frontend can load it directly via <img src="{url}">.
            # The embed CONTENT (with lat/lon/name) is still client-encrypted.
            timestamp = datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S")
            uid = uuid.uuid4().hex[:8]
            prefix = user_id or "anon"
            map_image_s3_key = f"{prefix}/{timestamp}_{uid}_map_location.png"

            if hasattr(self, "app") and hasattr(self.app, "_s3_service") and self.app._s3_service:
                upload_result = await self.app._s3_service.upload_file(
                    bucket_key="chatfiles",
                    file_key=map_image_s3_key,
                    content=image_bytes,
                    content_type="image/png",
                )
                map_image_url = upload_result.get("url")
                logger.info(f"{log_prefix} Uploaded static map to S3: {map_image_s3_key}")
            else:
                logger.warning(
                    f"{log_prefix} S3 service not available on app; skipping map image upload"
                )

        except Exception as img_error:
            # Image generation is best-effort: the embed is still created with
            # coordinates — the frontend can render a Leaflet map as fallback.
            logger.warning(
                f"{log_prefix} Failed to generate/upload static map image: {img_error}",
                exc_info=True,
            )

        # ------------------------------------------------------------------ #
        # 3. Build embed content dict and encode as TOON
        # ------------------------------------------------------------------ #
        generated_at = datetime.now(timezone.utc).isoformat()

        embed_content: Dict[str, Any] = {
            "app_id": "maps",
            "skill_id": "location",
            "type": "map_location",
            "status": "finished",
            "lat": lat,
            "lon": lon,
            "zoom": zoom,
            "name": name or "",
            "location_type": location_type or "precise_location",
            "generated_at": generated_at,
        }

        if map_image_url:
            embed_content["map_image_url"] = map_image_url
        if map_image_s3_key:
            embed_content["map_image_s3_key"] = map_image_s3_key

        from toon_format import encode as toon_encode
        content_toon = toon_encode(embed_content)
        logger.info(f"{log_prefix} TOON-encoded content: {len(content_toon)} chars")

        # ------------------------------------------------------------------ #
        # 4. Send embed to client via WebSocket (standard client-encryption flow)
        # ------------------------------------------------------------------ #
        # Note: message_id may be None when the skill is called from the
        # message compose UI (before the message exists). We still send the embed
        # so the compose-time embed node can transition from 'processing' to
        # 'finished'. The frontend embed store identifies embeds by embed_id.
        if user_id and chat_id:
            try:
                hashed_user_id = self._hash_value(user_id)
                now_ts = int(datetime.now(timezone.utc).timestamp())

                from backend.core.api.app.services.embed_service import EmbedService

                # Access shared services from the parent app instance
                embed_service = EmbedService(
                    cache_service=self.app._cache_service,
                    directus_service=self.app._directus_service,
                    encryption_service=self.app._encryption_service,
                )

                await embed_service.send_embed_data_to_client(
                    embed_id=final_embed_id,
                    embed_type="app_skill_use",
                    content_toon=content_toon,
                    chat_id=chat_id,
                    # message_id may be None when called from compose UI
                    # (before the message exists). Pass empty string as placeholder;
                    # the frontend embed store identifies embeds by embed_id.
                    message_id=message_id or "",
                    user_id=user_id,
                    user_id_hash=hashed_user_id,
                    status="finished",
                    encryption_mode="client",
                    created_at=now_ts,
                    updated_at=now_ts,
                    log_prefix=log_prefix,
                    check_cache_status=False,
                )

                # Cache S3 key for server-side cleanup on embed/chat deletion
                if map_image_s3_key:
                    try:
                        client = await self.app._cache_service.client
                        if client:
                            import json
                            s3_keys = [{"bucket": "chatfiles", "key": map_image_s3_key}]
                            cache_key = f"embed:{final_embed_id}:s3_file_keys"
                            await client.set(cache_key, json.dumps(s3_keys), ex=3600)
                            logger.debug(
                                f"{log_prefix} Cached S3 file key for embed {final_embed_id}"
                            )
                    except Exception as cache_err:
                        logger.warning(
                            f"{log_prefix} Failed to cache S3 file key: {cache_err}"
                        )

                logger.info(f"{log_prefix} Location embed sent successfully")

            except Exception as send_error:
                logger.error(
                    f"{log_prefix} Failed to send embed to client: {send_error}",
                    exc_info=True,
                )
                return LocationResponse(
                    status="error",
                    error=f"Failed to deliver location embed: {send_error}",
                )
        else:
            logger.warning(
                f"{log_prefix} Missing user_id/chat_id/message_id — embed not sent via WebSocket"
            )

        return LocationResponse(
            embed_id=final_embed_id,
            status="finished",
            lat=lat,
            lon=lon,
            zoom=zoom,
            name=name,
            location_type=location_type,
            map_image_url=map_image_url,
        )
