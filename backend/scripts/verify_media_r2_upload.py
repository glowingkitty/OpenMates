#!/usr/bin/env python3
"""Verify an actual R2 upload through the public first-party dev route.

The refresh token is read from stdin so credentials never appear in commands or
output. The verifier checks the upload service's active writer metadata, confirms
wrapped-key-only Directus persistence, reads plaintext through the signed dev
REST route, and removes every temporary Directus and S3 resource in a finally
block. Stable output contains no identifiers, keys, or private response data.
"""

from __future__ import annotations

import asyncio
import io
import json
import os
import sys
import time

import httpx
from PIL import Image

from backend.core.api.app.services.directus import DirectusService
from backend.core.api.app.services.s3.config import get_bucket_name
from backend.core.api.app.services.s3.service import S3UploadService
from backend.core.api.app.utils.encryption import EncryptionService
from backend.core.api.app.utils.secrets_manager import SecretsManager
from backend.shared.python_utils.generated_assets import create_download_token
from backend.shared.python_utils.media_encryption import MEDIA_ENCRYPTION_V2


PUBLIC_API_URL = "https://api.dev.openmates.org"
PUBLIC_UPLOAD_URL = "https://upload.openmates.org/v1/upload/file"
DEV_ORIGIN = "https://app.dev.openmates.org"


def _make_unique_png() -> bytes:
    marker = time.time_ns()
    image = Image.new(
        "RGB",
        (2, 2),
        (
            marker & 0xFF,
            (marker >> 8) & 0xFF,
            (marker >> 16) & 0xFF,
        ),
    )
    output = io.BytesIO()
    image.save(output, format="PNG")
    return output.getvalue()


async def main() -> int:
    if os.getenv("SERVER_ENVIRONMENT") == "production":
        print(json.dumps({"status": "fail", "error": "production_target_refused"}))
        return 1

    refresh_token = sys.stdin.read().strip()
    if not refresh_token:
        print(json.dumps({"status": "fail", "error": "refresh_token_missing"}))
        return 1

    secrets = SecretsManager()
    await secrets.initialize()
    encryption = EncryptionService()
    directus = DirectusService(encryption_service=encryption)
    s3 = S3UploadService(secrets_manager=secrets, directus_service=directus)
    await s3.initialize()

    row_id = None
    object_keys: list[str] = []
    checks = {
        "public_upload": False,
        "v2_metadata": False,
        "distinct_prefixed_nonces": False,
        "raw_key_omitted": False,
        "vault_key_persisted": False,
        "rest_download": False,
        "plaintext_match": False,
        "cleanup": False,
    }
    try:
        plaintext = _make_unique_png()
        async with httpx.AsyncClient(timeout=90, follow_redirects=True) as client:
            upload_response = await client.post(
                PUBLIC_UPLOAD_URL,
                headers={"Origin": DEV_ORIGIN},
                cookies={"auth_refresh_token": refresh_token},
                files={"file": ("r2-verification.png", plaintext, "image/png")},
            )
        if upload_response.status_code != 200:
            raise RuntimeError(f"public_upload_http_{upload_response.status_code}")
        checks["public_upload"] = True

        upload = upload_response.json()
        embed_id = str(upload.get("embed_id") or "")
        files_metadata = upload.get("files") or {}
        if not embed_id or not files_metadata:
            raise RuntimeError("public_upload_contract_invalid")
        checks["v2_metadata"] = all(
            metadata.get("encryption") == MEDIA_ENCRYPTION_V2
            for metadata in files_metadata.values()
        )
        object_keys = [
            str(metadata["s3_key"])
            for metadata in files_metadata.values()
            if metadata.get("s3_key")
        ]

        rows = await directus.get_items(
            "upload_files",
            params={
                "filter": {"embed_id": {"_eq": embed_id}},
                "fields": "id,user_id,aes_key,aes_nonce,vault_wrapped_aes_key,files_metadata",
                "limit": 1,
            },
            no_cache=True,
        )
        if not rows:
            raise RuntimeError("persisted_upload_missing")
        row = rows[0]
        row_id = str(row["id"])
        checks["raw_key_omitted"] = not row.get("aes_key") and not row.get("aes_nonce")
        checks["vault_key_persisted"] = bool(row.get("vault_wrapped_aes_key"))

        bucket_name = get_bucket_name("chatfiles", s3.environment)
        encrypted_payloads = [
            await s3.get_file(bucket_name, object_key) for object_key in object_keys
        ]
        prefixes = [payload[:12] for payload in encrypted_payloads if payload]
        checks["distinct_prefixed_nonces"] = (
            len(prefixes) == len(object_keys)
            and len(prefixes) > 1
            and len(set(prefixes)) == len(prefixes)
        )

        token = create_download_token(
            asset_id=embed_id,
            user_id=str(row["user_id"]),
            variant="original",
        )
        async with httpx.AsyncClient(timeout=30, follow_redirects=True) as client:
            download_response = await client.get(
                f"{PUBLIC_API_URL}/v1/generated-assets/{embed_id}/files/original/download",
                params={"token": token},
            )
        checks["rest_download"] = download_response.status_code == 200
        checks["plaintext_match"] = download_response.content == plaintext
    except Exception as exc:
        print(json.dumps({"status": "fail", "error": type(exc).__name__, "checks": checks}))
        return 1
    finally:
        cleanup_ok = True
        if row_id:
            cleanup_ok = bool(await directus.delete_item("upload_files", row_id)) and cleanup_ok
        for object_key in object_keys:
            try:
                await s3.delete_file("chatfiles", object_key)
            except Exception:
                cleanup_ok = False
        checks["cleanup"] = cleanup_ok
        await directus.close()
        await encryption.close()
        await secrets.aclose()

    status = "pass" if all(checks.values()) else "fail"
    print(json.dumps({"status": status, "checks": checks}))
    return 0 if status == "pass" else 1


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
