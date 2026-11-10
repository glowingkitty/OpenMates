"""Storage and content of an images.modify result.

The picture is stored exactly like an images.generate raster result, so every
client renders, opens, downloads and shares it with the existing generated
image card: ``original`` (the computed PNG/JPEG with provenance metadata),
``full`` and ``preview`` WEBP variants, encrypted with one AES key, uploaded to
chatfiles and indexed in the owner's generated-asset index. The content adds
``review_status``, ``unmet_requirements``, ``attempts`` and
``changed_from_program``; it never carries the program or a draft picture.
"""

from __future__ import annotations

import logging
import math
import uuid
from dataclasses import dataclass
from datetime import datetime, timezone
from io import BytesIO
from typing import Any, Mapping, Sequence

from backend.apps.images.modify_author import ModifyAuthorResult

logger = logging.getLogger(__name__)

ASSISTANT_FIELDS = (
    "prompt", "model", "provider", "filename", "aspect_ratio", "output_filetype", "generated_at",
    "input_embed_ids", "review_status", "unmet_requirements", "attempts", "changed_from_program", "billing_status",
)
FORMAT_MAPPING = {"original": "original", "full_webp": "full", "preview_webp": "preview"}
PROVENANCE = {
    "ai_generated": True,
    "ai_edited": True,
    "edit_engine": "program",
    "labeling": "xmp+c2pa",
    "visual_watermark": False,
    "provider_watermarking": "not_applicable",
}


@dataclass(frozen=True)
class StoredModifyImage:
    """What the embed content and the index need about the stored picture."""

    files_metadata: dict[str, dict[str, Any]]
    aes_key_b64: str
    nonce_b64: str
    vault_wrapped_aes_key: str
    s3_base_url: str
    filename: str
    output_filetype: str


def aspect_ratio(width: int, height: int) -> str:
    """Reduced ``W:H`` of the computed picture (the result keeps its own size)."""
    if width <= 0 or height <= 0:
        raise ValueError("a computed picture has a positive size")
    divisor = math.gcd(width, height)
    return f"{width // divisor}:{height // divisor}"


def display_model(model_id: str) -> str:
    return model_id.split("/")[-1]


def _size(content: bytes) -> tuple[int, int]:
    from PIL import Image

    with Image.open(BytesIO(content)) as image:
        return image.size


async def store_modified_image(
    task: Any, *, s3_service: Any, bucket_name: str, user_id: str, embed_id: str, authored: ModifyAuthorResult,
    instructions: str, vault_key_id: str, log_prefix: str,
) -> StoredModifyImage:
    """Process, encrypt, upload and index the picture; remove uploaded objects when a later step fails."""
    from backend.core.api.app.utils.image_processing import process_image_for_storage
    from backend.shared.python_utils.generated_assets import cache_s3_file_keys, index_generated_asset
    from backend.shared.python_utils.generated_media_graph import generated_image_filename
    from backend.shared.python_utils.image_mime import validate_raster_image
    from backend.shared.python_utils.media_encryption import encrypt_media_variants, load_media_write_version

    labeling_metadata = {
        "prompt": instructions,
        "model": authored.model_id,
        "software": "OpenMates",
        "source": "OpenMates AI",
        "generated_at": datetime.now(timezone.utc).isoformat(),
    }
    processed = process_image_for_storage(authored.image, metadata=labeling_metadata)
    encrypted = encrypt_media_variants(processed, write_version=load_media_write_version())
    wrapped_key, _ = await task._encryption_service.encrypt_with_user_key(encrypted.aes_key_b64, vault_key_id)
    if not wrapped_key:
        raise RuntimeError("Failed to wrap the AES key of the modified picture with Vault")

    timestamp = datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S")
    unique_id = uuid.uuid4().hex[:8]
    files_metadata: dict[str, dict[str, Any]] = {}
    uploaded: list[str] = []
    try:
        for format_key, content in processed.items():
            extension, mime_type = validate_raster_image(content)
            file_key = f"{user_id}/{timestamp}_{unique_id}_modify_{format_key}.{extension}"
            result = await s3_service.upload_file(
                bucket_key="chatfiles", file_key=file_key, content=encrypted.payloads[format_key],
                content_type="application/octet-stream",
            )
            if not result.get("url"):
                raise RuntimeError(f"Failed to upload the {format_key} file of the modified picture")
            uploaded.append(file_key)
            width, height = _size(content)
            files_metadata[FORMAT_MAPPING.get(format_key, format_key)] = {
                "s3_key": file_key, "width": width, "height": height, "size_bytes": len(content),
                "format": extension, "mime_type": mime_type, **encrypted.metadata[format_key],
            }
        output_filetype = files_metadata["original"]["format"]
        filename = generated_image_filename(instructions, embed_id, output_filetype)
        s3_base_url = f"https://{bucket_name}.{s3_service.base_domain}"
        indexed = await index_generated_asset(
            task, user_id=user_id, embed_id=embed_id, media_type="image", files_metadata=files_metadata,
            s3_base_url=s3_base_url, aes_key_b64=encrypted.aes_key_b64, nonce_b64=encrypted.legacy_nonce_b64 or "",
            vault_wrapped_aes_key=wrapped_key, created_at=int(datetime.now(timezone.utc).timestamp()),
            content_hash_source=authored.image, original_filename=filename,
            content_type=files_metadata["original"]["mime_type"], log_prefix=log_prefix,
            provenance_metadata={key: PROVENANCE[key] for key in ("labeling", "visual_watermark", "edit_engine")},
        )
        if not indexed:
            raise RuntimeError("Failed to index the modified picture in account storage")
    except BaseException:
        for file_key in uploaded:
            await s3_service.delete_file(bucket_key="chatfiles", file_key=file_key)
        raise
    await cache_s3_file_keys(task, embed_id=embed_id, files_metadata=files_metadata, log_prefix=log_prefix)
    return StoredModifyImage(
        files_metadata=files_metadata, aes_key_b64=encrypted.aes_key_b64,
        nonce_b64=encrypted.legacy_nonce_b64 or "", vault_wrapped_aes_key=wrapped_key, s3_base_url=s3_base_url,
        filename=filename, output_filetype=output_filetype,
    )


def review_fields(authored: ModifyAuthorResult, *, changed_from_program: bool) -> dict[str, Any]:
    """How the result was checked: shown on the card and told to the assistant."""
    return {
        "review_status": authored.review_status,
        "unmet_requirements": list(authored.unmet_requirements),
        "attempts": authored.attempts,
        "changed_from_program": changed_from_program,
    }


def build_finished_content(
    *, skill_id: str, stored: StoredModifyImage, authored: ModifyAuthorResult, instructions: str,
    input_embed_ids: Sequence[str], changed_from_program: bool, billing_status: str,
) -> dict[str, Any]:
    """Content of the finished result child: the images.generate raster shape plus the review fields."""
    return {
        "app_id": "images",
        "skill_id": skill_id,
        "type": "image",
        "status": "finished",
        "files": stored.files_metadata,
        "s3_base_url": stored.s3_base_url,
        "aes_key": stored.aes_key_b64,
        "aes_nonce": stored.nonce_b64,
        "vault_wrapped_aes_key": stored.vault_wrapped_aes_key,
        "prompt": instructions,
        "model": display_model(authored.model_id),
        "provider": authored.model_id.split("/", 1)[0],
        "filename": stored.filename,
        "aspect_ratio": aspect_ratio(authored.width, authored.height),
        "output_filetype": stored.output_filetype,
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "input_embed_ids": list(input_embed_ids),
        **review_fields(authored, changed_from_program=changed_from_program),
        "billing_status": billing_status,
        "provenance": dict(PROVENANCE),
    }


def build_failed_content(
    *, skill_id: str, instructions: str, output_filetype: str, input_embed_ids: Sequence[str], error_code: str,
    user_message: str,
) -> dict[str, Any]:
    """A failed result: the reason in plain words, no picture and no charge."""
    return {
        "app_id": "images",
        "skill_id": skill_id,
        "type": "image",
        "status": "error",
        "prompt": instructions,
        "output_filetype": output_filetype,
        "input_embed_ids": list(input_embed_ids),
        "files": {},
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "billing_status": "not_charged",
        "error": user_message,
        "error_code": error_code,
    }


def assistant_result(*, embed_id: str, content: Mapping[str, Any]) -> dict[str, Any]:
    """Task result for the assistant (like images.generate in a chat): what was made and how it was checked."""
    from backend.shared.python_utils.generated_media_graph import generated_media_embed_ref

    files = content.get("files") or {}
    original = files.get("original") or {}
    return {
        "embed_id": embed_id,
        "child_embed_id": embed_id,
        "child_embed_ids": [embed_id],
        "embed_ref": generated_media_embed_ref("images", embed_id),
        "type": "image",
        "status": "finished",
        **{key: content[key] for key in ASSISTANT_FIELDS if key in content},
        "width": original.get("width"),
        "height": original.get("height"),
        "files": {
            variant: {"width": meta["width"], "height": meta["height"], "size_bytes": meta["size_bytes"],
                      "format": meta["format"]}
            for variant, meta in files.items()
        },
    }
