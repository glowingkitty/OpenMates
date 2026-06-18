# backend/apps/weather/skills/rain_radar_skill.py
#
# Weather rain radar skill implementation.
# Produces compact LLM summaries and embed-ready timeline metadata from DWD radar
# while keeping raw radar grids out of the inference context.
#
# Architecture: docs/specs/weather-rain-radar/spec.yml

from __future__ import annotations

import logging
import base64
import json
import secrets
from datetime import datetime, timezone as datetime_timezone
from io import BytesIO
from typing import Any

from celery import Celery
from cryptography.hazmat.primitives.ciphers.aead import AESGCM
from PIL import Image
from pydantic import BaseModel, Field, model_validator

from backend.apps.base_skill import BaseSkill
from backend.shared.providers.bright_sky import fetch_radar, normalize_radar_frames
from backend.shared.providers.open_meteo import geocode_location

logger = logging.getLogger(__name__)

BRIGHT_SKY_RADAR_PROVIDER_LABEL = "Deutscher Wetterdienst (DWD) via Bright Sky"
DEFAULT_RADAR_RADIUS_KM = 5
MIN_RADAR_RADIUS_KM = 1
MAX_RADAR_RADIUS_KM = 100
GERMANY_COUNTRY_CODE = "DE"
DEFAULT_TIMEZONE = "Europe/Berlin"
RADAR_INFERENCE_EXCLUDE_FIELDS = [
    "files",
    "s3_base_url",
    "aes_key",
    "aes_nonce",
    "vault_wrapped_aes_key",
    "radar_blob_b64",
    "provider_raw",
]


class RainRadarRequest(BaseModel):
    """Rain radar request parameters."""

    location: str | None = Field(default=None, description="Place name for the radar.")
    latitude: float | None = Field(default=None, description="Optional exact latitude.")
    longitude: float | None = Field(default=None, description="Optional exact longitude.")
    radius_km: int = Field(default=DEFAULT_RADAR_RADIUS_KM, ge=MIN_RADAR_RADIUS_KM, le=MAX_RADAR_RADIUS_KM)
    timezone: str | None = Field(default=None, description="Optional IANA timezone.")

    @model_validator(mode="after")
    def validate_location_or_coordinates(self) -> "RainRadarRequest":
        has_location = bool(self.location and self.location.strip())
        has_coordinates = self.latitude is not None and self.longitude is not None
        if not has_location and not has_coordinates:
            raise ValueError("Provide either location or latitude and longitude.")
        if (self.latitude is None) != (self.longitude is None):
            raise ValueError("latitude and longitude must be provided together.")
        return self


class RainRadarResponse(BaseModel):
    """Weather rain radar skill response."""

    type: str = "rain_radar"
    provider: str = BRIGHT_SKY_RADAR_PROVIDER_LABEL
    location: dict[str, Any] = Field(default_factory=dict)
    coverage: dict[str, Any] = Field(default_factory=dict)
    summary: dict[str, Any] = Field(default_factory=dict)
    timeline: list[dict[str, Any]] = Field(default_factory=list)
    rendering: dict[str, Any] = Field(default_factory=dict)
    suggestions_follow_up_requests: list[str] = Field(default_factory=list)
    ignore_fields_for_inference: list[str] = Field(default_factory=lambda: list(RADAR_INFERENCE_EXCLUDE_FIELDS))
    radar_blob_b64: str | None = None
    files: dict[str, Any] | None = None
    s3_base_url: str | None = None
    aes_key: str | None = None
    aes_nonce: str | None = None
    error: str | None = None


class RainRadarSkill(BaseSkill):
    """Get nearby DWD rain radar for German locations."""

    def __init__(
        self,
        app: Any,
        app_id: str,
        skill_id: str,
        skill_name: str,
        skill_description: str,
        stage: str = "development",
        full_model_reference: str | None = None,
        pricing_config: dict[str, Any] | None = None,
        celery_producer: Celery | None = None,
        skill_operational_defaults: dict[str, Any] | None = None,
    ) -> None:
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
            skill_operational_defaults=skill_operational_defaults,
        )

    @classmethod
    def resolve_preview_metadata(cls, request: dict[str, Any]) -> dict[str, Any]:
        location = request.get("location") or "Rain radar"
        radius_km = request.get("radius_km") or DEFAULT_RADAR_RADIUS_KM
        return {
            "query": f"{location} rain radar",
            "location": location,
            "radius_km": radius_km,
            "provider": BRIGHT_SKY_RADAR_PROVIDER_LABEL,
        }

    async def _resolve_location(self, request: RainRadarRequest) -> dict[str, Any]:
        if request.latitude is not None and request.longitude is not None:
            return {
                "name": request.location or f"{request.latitude:.4f}, {request.longitude:.4f}",
                "country_code": GERMANY_COUNTRY_CODE if request.location is None else None,
                "country": None,
                "latitude": request.latitude,
                "longitude": request.longitude,
                "timezone": request.timezone or DEFAULT_TIMEZONE,
            }

        assert request.location is not None
        resolved = await geocode_location(request.location)
        if not resolved:
            raise ValueError(f"Could not resolve rain radar location: {request.location}")
        if resolved.get("latitude") is None or resolved.get("longitude") is None:
            raise ValueError(f"Resolved rain radar location lacks coordinates: {request.location}")
        if request.timezone:
            resolved["timezone"] = request.timezone
        return resolved

    async def execute(
        self,
        location: str | None = None,
        latitude: float | None = None,
        longitude: float | None = None,
        radius_km: int = DEFAULT_RADAR_RADIUS_KM,
        timezone: str | None = None,
        **kwargs: Any,
    ) -> RainRadarResponse:
        """Execute the rain radar skill and return embed-ready radar metadata."""
        try:
            request = RainRadarRequest(
                location=location,
                latitude=latitude,
                longitude=longitude,
                radius_km=radius_km,
                timezone=timezone,
            )
            resolved_location = await self._resolve_location(request)
            resolved_timezone = resolved_location.get("timezone") or timezone or DEFAULT_TIMEZONE
            location_name = str(resolved_location.get("name") or location or "Rain radar")
            country_code = resolved_location.get("country_code")
            lat = float(resolved_location["latitude"])
            lon = float(resolved_location["longitude"])
            location_payload = {
                "name": location_name,
                "country": resolved_location.get("country"),
                "country_code": country_code,
                "admin1": resolved_location.get("admin1"),
                "latitude": lat,
                "longitude": lon,
                "timezone": resolved_timezone,
            }

            if country_code != GERMANY_COUNTRY_CODE:
                return RainRadarResponse(
                    location=location_payload,
                    coverage={
                        "status": "unavailable",
                        "reason": "Rain radar V1 only supports Germany through DWD/Bright Sky coverage.",
                        "radius_km": request.radius_km,
                    },
                    summary={
                        "rain_expected": None,
                        "in_10_min": "Rain radar is unavailable for this location in V1.",
                        "next_2_hours": "Germany DWD rain radar is available in V1; global radar coverage is not supported yet.",
                        "peak_intensity": "unknown",
                        "preview_frame_id": None,
                    },
                    rendering={"mode": "unavailable", "radius_km": request.radius_km, "frame_count": 0},
                    suggestions_follow_up_requests=["Show the regular forecast", "Try a German location"],
                )

            provider_payload = await fetch_radar(
                latitude=lat,
                longitude=lon,
                radius_km=request.radius_km,
                timezone=resolved_timezone,
            )
            now_timestamp = datetime.now(datetime_timezone.utc).isoformat()
            radar_result = normalize_radar_frames(
                provider_payload,
                location_name=location_name,
                latitude=lat,
                longitude=lon,
                radius_km=request.radius_km,
                now_timestamp=now_timestamp,
            )
            rendering = dict(radar_result["rendering"])
            rendering.setdefault("radius_km", request.radius_km)
            storage_metadata = await self._store_radar_assets_if_possible(
                radar_result=radar_result,
                user_id=kwargs.get("user_id"),
                placeholder_embed_ids=kwargs.get("placeholder_embed_ids"),
            )

            return RainRadarResponse(
                location=location_payload,
                coverage=radar_result["coverage"],
                summary=radar_result["summary"],
                timeline=radar_result["timeline"],
                rendering=rendering,
                radar_blob_b64=None if storage_metadata else radar_result.get("radar_blob_b64"),
                files=storage_metadata.get("files") if storage_metadata else None,
                s3_base_url=storage_metadata.get("s3_base_url") if storage_metadata else None,
                aes_key=storage_metadata.get("aes_key") if storage_metadata else None,
                aes_nonce=storage_metadata.get("aes_nonce") if storage_metadata else None,
                suggestions_follow_up_requests=[
                    "Show the regular forecast",
                    "Will it rain at my exact location?",
                    "Check a larger radar radius",
                ],
            )
        except Exception as error:
            logger.error("RainRadarSkill failed: %s", error, exc_info=True)
            return RainRadarResponse(
                location={"name": location or "Rain radar"},
                coverage={"status": "error", "radius_km": radius_km},
                summary={
                    "rain_expected": None,
                    "in_10_min": "Rain radar could not be loaded.",
                    "next_2_hours": "Rain radar failed before a timeline could be built.",
                    "peak_intensity": "unknown",
                    "preview_frame_id": None,
                },
                rendering={"mode": "error", "radius_km": radius_km, "frame_count": 0},
                error=str(error),
            )

    async def _store_radar_assets_if_possible(
        self,
        *,
        radar_result: dict[str, Any],
        user_id: str | None,
        placeholder_embed_ids: Any,
    ) -> dict[str, Any] | None:
        """Store encrypted preview/blob files when chat execution context is available."""
        embed_id = self._first_placeholder_embed_id(placeholder_embed_ids)
        if not user_id or not embed_id:
            return None
        radar_blob_b64 = radar_result.get("radar_blob_b64")
        if not isinstance(radar_blob_b64, str) or not radar_blob_b64:
            return None

        try:
            from backend.core.api.app.services.cache import CacheService
            from backend.core.api.app.services.s3.config import get_bucket_name
            from backend.core.api.app.services.s3.service import S3UploadService
            from backend.core.api.app.utils.secrets_manager import SecretsManager

            secrets_manager = SecretsManager()
            await secrets_manager.initialize()
            s3_service = S3UploadService(secrets_manager=secrets_manager)
            await s3_service.initialize()
            if not s3_service.base_domain:
                raise RuntimeError("S3 service initialized without base domain")

            aes_key = AESGCM.generate_key(bit_length=256)
            aesgcm = AESGCM(aes_key)
            now = datetime.now(datetime_timezone.utc)
            unique_id = secrets.token_hex(8)
            base_key = f"{user_id}/{int(now.timestamp())}_{unique_id}_rain_radar"
            radar_blob = base64.b64decode(radar_blob_b64)
            preview = self._render_preview_webp(radar_result)
            files: dict[str, dict[str, Any]] = {
                "preview": {
                    "s3_key": f"{base_key}_preview.webp",
                    "format": "webp",
                    "width": 640,
                    "height": 360,
                    "size_bytes": len(preview),
                },
                "radar_blob": {
                    "s3_key": f"{base_key}_blob.zlib",
                    "format": "radar-grid-v1.zlib",
                    "size_bytes": len(radar_blob),
                },
            }

            for file_meta, content in ((files["preview"], preview), (files["radar_blob"], radar_blob)):
                nonce = secrets.token_bytes(12)
                encrypted_payload = aesgcm.encrypt(nonce, content, None)
                await s3_service.upload_file(
                    bucket_key="chatfiles",
                    file_key=file_meta["s3_key"],
                    content=nonce + encrypted_payload,
                    content_type="application/octet-stream",
                )

            client = await CacheService().client
            if client:
                s3_file_keys = [
                    {"bucket": "chatfiles", "key": files["preview"]["s3_key"]},
                    {"bucket": "chatfiles", "key": files["radar_blob"]["s3_key"]},
                ]
                await client.set(f"embed:{embed_id}:s3_file_keys", json.dumps(s3_file_keys), ex=3600)

            chatfiles_bucket = get_bucket_name("chatfiles")
            return {
                "files": files,
                "s3_base_url": f"https://{chatfiles_bucket}.{s3_service.base_domain}",
                "aes_key": base64.b64encode(aes_key).decode("ascii"),
                "aes_nonce": "",
            }
        except Exception as error:
            logger.error("Failed to store rain radar assets: %s", error, exc_info=True)
            raise

    @staticmethod
    def _first_placeholder_embed_id(placeholder_embed_ids: Any) -> str | None:
        if isinstance(placeholder_embed_ids, list) and placeholder_embed_ids:
            first = placeholder_embed_ids[0]
            return first if isinstance(first, str) and first else None
        return None

    @staticmethod
    def _render_preview_webp(radar_result: dict[str, Any]) -> bytes:
        """Render a small deterministic preview image from the selected radar frame."""
        radar_blob_b64 = radar_result.get("radar_blob_b64")
        # radar_blob_b64 is already a compressed JSON blob from the provider helper.
        import zlib
        blob = json.loads(zlib.decompress(base64.b64decode(str(radar_blob_b64))).decode("utf-8"))
        frames = blob.get("frames") or []
        preview_id = radar_result.get("summary", {}).get("preview_frame_id")
        frame = next((item for item in frames if item.get("frame_id") == preview_id), frames[0] if frames else {})
        values = frame.get("values") or [0]
        grid = blob.get("grid") or {}
        width = int(grid.get("width") or 1)
        height = int(grid.get("height") or max(1, len(values) // width))
        image = Image.new("RGBA", (width, height), (240, 248, 252, 255))
        pixels = image.load()
        for index, raw_value in enumerate(values[:width * height]):
            x = index % width
            y = index // width
            value = int(raw_value)
            if value <= 0:
                pixels[x, y] = (230, 240, 245, 255)
            elif value < 50:
                pixels[x, y] = (0, 167, 201, min(255, 90 + value * 2))
            elif value < 200:
                pixels[x, y] = (54, 99, 255, min(255, 120 + value // 2))
            else:
                pixels[x, y] = (98, 51, 176, 245)
        image = image.resize((640, 360), resample=Image.Resampling.BILINEAR)
        output = BytesIO()
        image.save(output, format="WEBP", quality=82)
        return output.getvalue()
