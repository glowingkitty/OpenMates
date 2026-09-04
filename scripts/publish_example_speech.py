#!/usr/bin/env python3
"""Publish reviewed assistant speech as immutable public example fixtures.

This internal-only utility runs in the trusted API runtime, reads owner-scoped
ready segment metadata, decrypts private generated assets in memory, and writes
content-addressed public copies. Output contains no owner IDs, keys, provider
metadata, private bucket paths, or source generated-asset records.
"""

from __future__ import annotations

import argparse
import asyncio
import base64
import hashlib
import json
import sys
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from backend.core.api.app.services.s3.config import get_bucket_name  # noqa: E402
from backend.core.api.app.services.s3.service import S3UploadService  # noqa: E402
from backend.core.api.app.services.directus import DirectusService  # noqa: E402
from backend.core.api.app.utils.encryption import EncryptionService  # noqa: E402
from backend.core.api.app.utils.secrets_manager import SecretsManager  # noqa: E402
from backend.shared.python_utils.media_encryption import (  # noqa: E402
    decrypt_media_payload,
)


PUBLIC_BUCKET_KEY = "public_example_speech"
PUBLIC_OBJECT_PREFIX = "assistant-speech"


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--chat-id", required=True)
    parser.add_argument("--message-id", action="append", required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--reviewed", action="store_true", help="Confirm every selected message is approved for public playback")
    parser.add_argument("--print-manifest", action="store_true", help="Print the public-safe manifest for a downstream converter")
    return parser.parse_args()


async def _asset_key(record: dict[str, Any], *, user_id: str, directus: DirectusService, encryption: EncryptionService) -> bytes:
    if record.get("aes_key"):
        return base64.b64decode(str(record["aes_key"]), validate=True)
    wrapped = str(record.get("vault_wrapped_aes_key") or "")
    profile = await directus.get_user_fields_direct(user_id, ["vault_key_id"])
    vault_key_id = profile.get("vault_key_id") if profile else None
    if not wrapped or not vault_key_id:
        raise RuntimeError("Reviewed source asset key is unavailable")
    unwrapped = await encryption.decrypt_with_user_key(wrapped, vault_key_id)
    key = base64.b64decode(unwrapped or "", validate=True)
    if len(key) != 32:
        raise RuntimeError("Reviewed source asset key is invalid")
    return key


async def publish(args: argparse.Namespace) -> dict[str, Any]:
    if not args.reviewed:
        raise RuntimeError("Refusing public speech publication without --reviewed")
    secrets = SecretsManager()
    await secrets.initialize()
    directus = DirectusService()
    s3 = S3UploadService(secrets_manager=secrets, directus_service=directus)
    await s3.initialize(configure_buckets=True)
    encryption = EncryptionService()
    output_messages: list[dict[str, Any]] = []
    try:
        for message_id in args.message_id:
            rows = await directus.get_items(
                "assistant_speech_segments",
                params={
                    "filter": {
                        "chat_id": {"_eq": args.chat_id},
                        "assistant_message_id": {"_eq": message_id},
                        "status": {"_eq": "ready"},
                    },
                    "sort": "sequence",
                    "limit": -1,
                },
                no_cache=True,
                admin_required=True,
                raise_on_error=True,
            )
            if not rows:
                raise RuntimeError(f"No ready speech segments found for message {message_id}")
            public_segments: list[dict[str, Any]] = []
            for row in rows:
                asset_id = str(row.get("generated_asset_id") or "")
                records = await directus.get_items(
                    "upload_files",
                    params={"filter": {"embed_id": {"_eq": asset_id}}, "sort": "-created_at", "limit": 1},
                    no_cache=True,
                    admin_required=True,
                    raise_on_error=True,
                )
                if not records:
                    raise RuntimeError(f"Generated speech asset is missing for segment {row.get('segment_id')}")
                record = dict(records[0])
                variants = record.get("files_metadata") or {}
                variant = variants.get("original") if isinstance(variants, dict) else None
                if not isinstance(variant, dict) or not variant.get("s3_key"):
                    raise RuntimeError("Generated speech original variant is missing")
                encrypted_bytes = await s3.get_file(
                    bucket_name=get_bucket_name("chatfiles", s3.environment),
                    object_key=str(variant["s3_key"]),
                )
                plaintext = decrypt_media_payload(
                    encrypted_data=encrypted_bytes,
                    aes_key=await _asset_key(record, user_id=str(row["user_id"]), directus=directus, encryption=encryption),
                    variant=variant,
                    legacy_nonce_b64=record.get("aes_nonce"),
                )
                digest = hashlib.sha256(plaintext).hexdigest()
                object_key = f"{PUBLIC_OBJECT_PREFIX}/sha256-{digest}.mp3"
                uploaded = await s3.upload_file(
                    PUBLIC_BUCKET_KEY,
                    object_key,
                    plaintext,
                    "audio/mpeg",
                    metadata={"source-sha256": digest, "purpose": "reviewed-public-example-speech"},
                )
                public_segments.append({
                    "segment_id": str(row["segment_id"]),
                    "public_url": str(uploaded.get("url") or uploaded.get("file_url") or ""),
                    "sha256": digest,
                    "duration_seconds": float(row.get("duration_seconds") or 0),
                })
            output_messages.append({"assistant_message_id": message_id, "segments": public_segments})
    finally:
        await directus.close()
    manifest = {"reviewed": True, "source_chat_id": args.chat_id, "messages": output_messages}
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(manifest, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    return manifest


def main() -> int:
    args = parse_args()
    manifest = asyncio.run(publish(args))
    output = manifest if args.print_manifest else {"published_messages": len(manifest["messages"]), "manifest": str(args.output)}
    print(json.dumps(output, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
