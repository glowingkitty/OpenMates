# backend/shared/python_utils/generated_assets/service.py
#
# Unified generated-asset helpers for long-running media skills.
# Generated files are always stored encrypted in private S3. REST callers get
# short-lived download URLs that decrypt server-side; web embeds keep local
# client-side decryption metadata inside encrypted embed content.

import base64
import hashlib
import hmac
import json
import logging
import os
import time
from dataclasses import dataclass
from typing import Any, Dict, Optional

logger = logging.getLogger(__name__)

TOKEN_TTL_SECONDS = 900


@dataclass(frozen=True)
class GeneratedAssetVariant:
    """A stored encrypted generated-file variant."""

    s3_key: str
    size_bytes: int
    format: str
    mime_type: str
    width: Optional[int] = None
    height: Optional[int] = None
    duration_seconds: Optional[int] = None

    def to_metadata(self) -> Dict[str, Any]:
        data: Dict[str, Any] = {
            "s3_key": self.s3_key,
            "size_bytes": self.size_bytes,
            "format": self.format,
            "mime_type": self.mime_type,
        }
        if self.width is not None:
            data["width"] = self.width
        if self.height is not None:
            data["height"] = self.height
        if self.duration_seconds is not None:
            data["duration_seconds"] = self.duration_seconds
        return data


def _token_secret() -> bytes:
    secret = os.getenv("GENERATED_ASSET_TOKEN_SECRET") or os.getenv("INTERNAL_API_SHARED_TOKEN")
    if not secret:
        # Development/test fallback only. Production should always set a stable secret.
        secret = "openmates-generated-assets-dev-token-secret"
    return secret.encode("utf-8")


def _b64url_encode(data: bytes) -> str:
    return base64.urlsafe_b64encode(data).decode("ascii").rstrip("=")


def _b64url_decode(data: str) -> bytes:
    padding = "=" * (-len(data) % 4)
    return base64.urlsafe_b64decode(data + padding)


def create_download_token(
    *,
    asset_id: str,
    user_id: str,
    variant: str,
    expires_at: Optional[int] = None,
) -> str:
    """Create a signed short-lived bearer token for generated asset downloads."""
    payload = {
        "asset_id": asset_id,
        "user_id": user_id,
        "variant": variant,
        "expires_at": expires_at or int(time.time()) + TOKEN_TTL_SECONDS,
    }
    payload_b64 = _b64url_encode(json.dumps(payload, separators=(",", ":")).encode("utf-8"))
    signature = hmac.new(_token_secret(), payload_b64.encode("ascii"), hashlib.sha256).digest()
    return f"{payload_b64}.{_b64url_encode(signature)}"


def validate_download_token(token: str) -> Dict[str, Any]:
    """Validate a generated-asset download token and return its payload."""
    try:
        payload_b64, signature_b64 = token.split(".", 1)
        expected = hmac.new(_token_secret(), payload_b64.encode("ascii"), hashlib.sha256).digest()
        supplied = _b64url_decode(signature_b64)
        if not hmac.compare_digest(expected, supplied):
            raise ValueError("Invalid signature")
        payload = json.loads(_b64url_decode(payload_b64).decode("utf-8"))
        if int(payload.get("expires_at") or 0) < int(time.time()):
            raise ValueError("Expired token")
        return payload
    except Exception as exc:
        raise ValueError("Invalid generated asset download token") from exc


def build_download_url(*, base_url: str, asset_id: str, variant: str, token: str) -> str:
    """Build the public REST URL for server-side decrypted generated asset download."""
    root = base_url.rstrip("/")
    return f"{root}/v1/generated-assets/{asset_id}/files/{variant}/download?token={token}"


async def cache_s3_file_keys(task: Any, *, embed_id: str, files_metadata: Dict[str, Any], log_prefix: str) -> None:
    """Cache generated S3 keys so store_embed can persist cleanup metadata."""
    s3_file_keys = [
        {"bucket": "chatfiles", "key": meta["s3_key"]}
        for meta in files_metadata.values()
        if isinstance(meta, dict) and meta.get("s3_key")
    ]
    if not s3_file_keys:
        return
    try:
        client = await task._cache_service.client
        if client:
            await client.set(f"embed:{embed_id}:s3_file_keys", json.dumps(s3_file_keys), ex=3600)
    except Exception as exc:
        logger.warning("%s Failed to cache generated asset S3 keys: %s", log_prefix, exc)


async def index_generated_asset(
    task: Any,
    *,
    user_id: str,
    embed_id: str,
    media_type: str,
    files_metadata: Dict[str, Any],
    s3_base_url: str,
    aes_key_b64: str,
    nonce_b64: str,
    vault_wrapped_aes_key: str,
    created_at: int,
    content_hash_source: bytes,
    original_filename: str,
    content_type: str,
    log_prefix: str,
    provenance_metadata: Optional[Dict[str, Any]] = None,
) -> bool:
    """Create upload_files index record for generated media and update storage count."""
    file_size_bytes = sum(
        int(meta.get("size_bytes") or 0)
        for meta in files_metadata.values()
        if isinstance(meta, dict)
    )
    record = {
        "embed_id": embed_id,
        "user_id": user_id,
        "content_hash": hashlib.sha256(content_hash_source).hexdigest(),
        "original_filename": original_filename,
        "content_type": content_type,
        "file_size_bytes": file_size_bytes,
        "s3_base_url": s3_base_url,
        "files_metadata": files_metadata,
        "aes_key": aes_key_b64,
        "aes_nonce": nonce_b64,
        "vault_wrapped_aes_key": vault_wrapped_aes_key,
        "malware_scan": "clean",
        "ai_detection": {
            "ai_generated": 1.0,
            "source": f"openmates_{media_type}_generate",
            "provenance": provenance_metadata or {},
        },
        "created_at": created_at,
    }
    success, error = await task._directus_service.create_item("upload_files", record)
    if not success:
        logger.warning("%s Failed to create generated asset upload_files record: %s", log_prefix, error)
        return False

    try:
        user_fields = await task._directus_service.get_user_fields_direct(user_id, ["storage_used_bytes"])
        current_bytes = int((user_fields or {}).get("storage_used_bytes") or 0)
        await task._directus_service.update_user(user_id, {"storage_used_bytes": current_bytes + file_size_bytes})
    except Exception as exc:
        logger.warning("%s Failed to update generated asset storage counter: %s", log_prefix, exc)
    return True
