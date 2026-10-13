#!/usr/bin/env python3
"""Publish explicitly reviewed generated media from one owned chat as public examples.

Run only in the trusted API runtime. Private asset keys and owner data remain in
memory; the output manifest contains only selected embed IDs and immutable URLs.
"""

from __future__ import annotations

import argparse
import asyncio
import base64
import hashlib
import json
import re
import sys
from pathlib import Path
from typing import Any
from urllib.parse import urlparse

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from backend.core.api.app.services.s3.config import get_bucket_name  # noqa: E402
from backend.shared.python_utils.generated_assets import (  # noqa: E402
    CHUNKED_MODEL_ENCRYPTION,
    decrypt_generated_asset_variant,
)
from backend.shared.python_utils.media_encryption import decrypt_media_payload  # noqa: E402
from backend.shared.python_utils.object_storage_regions import LEGACY_BUCKET_REGION  # noqa: E402


PUBLIC_BUCKET_KEY = "public_example_media"
PUBLIC_OBJECT_PREFIX = "reviewed-media"
MAX_PLAINTEXT_BYTES = 100 * 1024 * 1024
MEDIA_SOURCES = {
    "openmates_application_preview_generate": "application_preview",
    "openmates_image_generate": "image",
    "openmates_audio_generate": "audio",
    "openmates_sound_effect_generate": "audio",
    "openmates_music_generate": "music",
    "openmates_video_generate": "video",
    "openmates_models3d_generate": "models3d",
}
MIME_EXTENSIONS = {
    "image/png": "png",
    "image/jpeg": "jpg",
    "image/webp": "webp",
    "audio/mpeg": "mp3",
    "audio/wav": "wav",
    "audio/ogg": "ogg",
    "video/mp4": "mp4",
    "video/webm": "webm",
    "model/gltf-binary": "glb",
}
FORMAT_MIMES = {
    "png": "image/png", "jpg": "image/jpeg", "jpeg": "image/jpeg", "webp": "image/webp",
    "mp3": "audio/mpeg", "wav": "audio/wav", "ogg": "audio/ogg",
    "mp4": "video/mp4", "webm": "video/webm", "glb": "model/gltf-binary",
}
SAFE_NAME = re.compile(r"^[a-z][a-z0-9_]{0,31}$")


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--chat-id", required=True)
    parser.add_argument("--user-id", required=True)
    parser.add_argument("--embed-id", action="append", required=True)
    parser.add_argument("--output", required=True, type=Path)
    parser.add_argument("--reviewed", action="store_true", help="Confirm selected embeds and media variants are approved for public display")
    parser.add_argument("--print-manifest", action="store_true")
    return parser.parse_args()


async def _rows(directus: Any, collection: str, filters: dict[str, Any]) -> list[dict[str, Any]]:
    rows = await directus.get_items(
        collection,
        params={"filter": filters, "limit": 2},
        no_cache=True,
        admin_required=True,
        raise_on_error=True,
    )
    return rows if isinstance(rows, list) else []


def _exact_row(rows: list[dict[str, Any]], label: str) -> dict[str, Any]:
    if len(rows) != 1 or not isinstance(rows[0], dict):
        raise RuntimeError(f"Reviewed {label} is unavailable or ambiguous")
    return rows[0]


async def _verify_chat_and_embed(directus: Any, *, chat_id: str, user_id: str, embed_id: str) -> None:
    user_hash = hashlib.sha256(user_id.encode()).hexdigest()
    chat_hash = hashlib.sha256(chat_id.encode()).hexdigest()
    chat = _exact_row(await _rows(directus, "chats", {"id": {"_eq": chat_id}}), "chat")
    if (chat.get("id") != chat_id or chat.get("hashed_user_id") != user_hash
            or chat.get("hashed_team_id") is not None or chat.get("storage_state") == "deleting"
            or chat.get("chat_visibility") not in (None, "team")
            or chat.get("participant_user_hashes") is not None
            or chat.get("participant_key_envelopes") is not None):
        raise RuntimeError("Reviewed chat owner could not be verified")
    embed = _exact_row(await _rows(directus, "embeds", {"embed_id": {"_eq": embed_id}}), "embed")
    if (embed.get("embed_id") != embed_id or embed.get("hashed_chat_id") != chat_hash
            or embed.get("hashed_user_id") != user_hash):
        raise RuntimeError("Reviewed embed does not belong to the selected chat and owner")


def _media_type(record: dict[str, Any]) -> str:
    detection = record.get("ai_detection")
    source = detection.get("source") if isinstance(detection, dict) else None
    media_type = MEDIA_SOURCES.get(str(source or ""))
    if not media_type:
        raise RuntimeError("Reviewed embed is not an indexed generated media asset")
    return media_type


def _variant_mime(variant: dict[str, Any]) -> str | None:
    mime = str(variant.get("mime_type") or "").lower()
    if mime in MIME_EXTENSIONS:
        return mime
    return FORMAT_MIMES.get(str(variant.get("format") or "").lower())


def _valid_variant_for_media(media_type: str, variant_name: str, mime: str) -> bool:
    if media_type == "application_preview":
        return variant_name == "preview" and mime == "image/png"
    if media_type == "image":
        return mime.startswith("image/")
    if media_type in {"audio", "music"}:
        return variant_name == "original" and mime.startswith("audio/")
    if media_type == "video":
        return (variant_name == "original" and mime.startswith("video/")) or (
            variant_name in {"thumbnail", "poster"} and mime.startswith("image/")
        )
    if media_type == "models3d":
        return (variant_name in {"preview", "master"} and mime == "model/gltf-binary") or (
            variant_name == "poster" and mime.startswith("image/")
        )
    return False


async def _asset_key(record: dict[str, Any], *, user_id: str, directus: Any, encryption: Any) -> bytes:
    wrapped = str(record.get("vault_wrapped_aes_key") or "")
    if wrapped:
        profile = await directus.get_user_fields_direct(user_id, ["vault_key_id"])
        vault_key_id = profile.get("vault_key_id") if isinstance(profile, dict) else None
        if not vault_key_id:
            raise RuntimeError("Reviewed asset key is unavailable")
        unwrapped = await encryption.decrypt_with_user_key(wrapped, vault_key_id)
        encoded = str(unwrapped or "")
    else:
        # Older generated media records stored the AES key directly.
        encoded = str(record.get("aes_key") or "")
    try:
        key = base64.b64decode(encoded, validate=True)
    except ValueError as exc:
        raise RuntimeError("Reviewed asset key is invalid") from exc
    if len(key) != 32:
        raise RuntimeError("Reviewed asset key is invalid")
    return key


async def _read_plaintext(s3: Any, *, metadata: dict[str, Any], key: bytes, nonce: str) -> bytes:
    s3_key = str(metadata.get("s3_key") or "")
    if not s3_key:
        raise RuntimeError("Reviewed asset variant has no private object")
    bucket = get_bucket_name("chatfiles", s3.environment)
    if metadata.get("encryption") == CHUNKED_MODEL_ENCRYPTION:
        chunks: list[bytes] = []
        size = 0
        async for chunk in decrypt_generated_asset_variant(
            metadata,
            s3.get_file_stream(bucket_name=bucket, object_key=s3_key),
            aes_key=key,
        ):
            size += len(chunk)
            if size > MAX_PLAINTEXT_BYTES:
                raise RuntimeError("Reviewed media variant exceeds publication limit")
            chunks.append(chunk)
        plaintext = b"".join(chunks)
    else:
        encrypted = await s3.get_file(bucket_name=bucket, object_key=s3_key)
        plaintext = decrypt_media_payload(
            encrypted_data=encrypted,
            aes_key=key,
            variant=metadata,
            legacy_nonce_b64=metadata.get("aes_nonce") or nonce,
        )
    if not plaintext or len(plaintext) > MAX_PLAINTEXT_BYTES:
        raise RuntimeError("Reviewed media variant is empty or too large")
    return plaintext


def _public_url(uploaded: dict[str, Any], *, bucket: str, base_domain: str, object_key: str) -> str:
    value = str(uploaded.get("url") or uploaded.get("file_url") or "")
    parsed = urlparse(value)
    if (parsed.scheme != "https" or parsed.netloc != f"{bucket}.{base_domain}"
            or parsed.path != f"/{object_key}" or parsed.query or parsed.fragment or parsed.username):
        raise RuntimeError("Public media upload did not return the expected immutable URL")
    return value


async def publish(args: argparse.Namespace, *, directus: Any = None, s3: Any = None, encryption: Any = None) -> dict[str, Any]:
    if args.reviewed is not True:
        raise RuntimeError("Refusing media publication without --reviewed")
    if not args.embed_id or len(set(args.embed_id)) != len(args.embed_id):
        raise RuntimeError("Select distinct reviewed embed IDs")

    owns_directus = directus is None
    if owns_directus:
        from backend.core.api.app.services.directus import DirectusService
        from backend.core.api.app.services.s3.service import S3UploadService
        from backend.core.api.app.utils.encryption import EncryptionService
        from backend.core.api.app.utils.secrets_manager import SecretsManager

        secrets = SecretsManager()
        await secrets.initialize()
        directus = DirectusService()
        s3 = S3UploadService(secrets_manager=secrets, directus_service=directus)
        await s3.initialize(configure_buckets=True)
        encryption = EncryptionService()
    elif s3 is None or encryption is None:
        raise RuntimeError("Media publisher dependencies are incomplete")

    output_embeds: list[dict[str, Any]] = []
    try:
        for embed_id in args.embed_id:
            await _verify_chat_and_embed(directus, chat_id=args.chat_id, user_id=args.user_id, embed_id=embed_id)
            record = _exact_row(await _rows(directus, "upload_files", {
                "embed_id": {"_eq": embed_id}, "user_id": {"_eq": args.user_id},
            }), "generated asset")
            if record.get("embed_id") != embed_id or record.get("user_id") != args.user_id:
                raise RuntimeError("Reviewed generated asset owner could not be verified")
            media_type = _media_type(record)
            files = record.get("files_metadata")
            if not isinstance(files, dict) or not files:
                raise RuntimeError("Reviewed generated asset has no variants")
            key = await _asset_key(record, user_id=args.user_id, directus=directus, encryption=encryption)
            public_variants: list[dict[str, str]] = []
            for variant_name, metadata in sorted(files.items()):
                if not isinstance(metadata, dict) or not SAFE_NAME.fullmatch(variant_name):
                    raise RuntimeError("Reviewed generated asset variant is invalid")
                mime = _variant_mime(metadata)
                if mime is None:
                    # SVG is active content and cannot be copied to the public
                    # examples bucket. Raster derivatives remain publishable.
                    if str(metadata.get("format") or "").lower() == "svg":
                        continue
                    raise RuntimeError("Reviewed generated asset variant has an unsupported MIME type")
                if not _valid_variant_for_media(media_type, variant_name, mime):
                    raise RuntimeError("Reviewed generated asset variant does not match its media type")
                plaintext = await _read_plaintext(s3, metadata=metadata, key=key, nonce=str(record.get("aes_nonce") or ""))
                digest = hashlib.sha256(plaintext).hexdigest()
                object_key = f"{PUBLIC_OBJECT_PREFIX}/{media_type}/{variant_name}/sha256-{digest}.{MIME_EXTENSIONS[mime]}"
                uploaded = await s3.upload_file(
                    PUBLIC_BUCKET_KEY, object_key, plaintext, mime,
                    metadata={"source-sha256": digest, "purpose": "reviewed-public-example-media"},
                    region=LEGACY_BUCKET_REGION,
                )
                public_variants.append({
                    "variant": variant_name,
                    "public_url": _public_url(
                        uploaded,
                        bucket=get_bucket_name(PUBLIC_BUCKET_KEY, s3.environment),
                        base_domain=s3.base_domain,
                        object_key=object_key,
                    ),
                    "sha256": digest,
                    "mime_type": mime,
                })
            if not public_variants:
                raise RuntimeError("Reviewed generated asset has no safe public variants")
            output_embeds.append({"embed_id": embed_id, "media_type": media_type, "variants": public_variants})
    finally:
        if owns_directus:
            await directus.close()

    manifest = {"reviewed": True, "source_chat_id": args.chat_id, "embeds": output_embeds}
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(manifest, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    return manifest


def main() -> int:
    args = parse_args()
    manifest = asyncio.run(publish(args))
    print(json.dumps(
        manifest if args.print_manifest else {"published_embeds": len(manifest["embeds"]), "manifest": str(args.output)},
        sort_keys=True,
    ))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
