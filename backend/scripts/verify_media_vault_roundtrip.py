#!/usr/bin/env python3
"""Verify wrapped-key-only media through the real dev REST download path.

Runs inside the API container with existing Vault, Directus, and S3 access.
Creates one synthetic v2 object and temporary index row, downloads plaintext
through api.dev.openmates.org, and removes both resources in a finally block.
Output contains only stable pass/fail checks and no identifiers or key material.
"""

from __future__ import annotations

import asyncio
import hashlib
import json
import os
import sys
import time
import uuid

import httpx

from backend.core.api.app.services.directus import DirectusService
from backend.core.api.app.services.s3.service import S3UploadService
from backend.core.api.app.utils.encryption import EncryptionService
from backend.core.api.app.utils.secrets_manager import SecretsManager
from backend.shared.python_utils.generated_assets import create_download_token
from backend.shared.python_utils.media_encryption import MEDIA_ENCRYPTION_V2, encrypt_media_variants


PUBLIC_API_URL = "https://api.dev.openmates.org"


async def main() -> int:
    if os.getenv("SERVER_ENVIRONMENT") == "production":
        print(json.dumps({"status": "fail", "error": "production_target_refused"}))
        return 1

    secrets = SecretsManager()
    await secrets.initialize()
    encryption = EncryptionService()
    directus = DirectusService(encryption_service=encryption)
    s3 = S3UploadService(secrets_manager=secrets, directus_service=directus)
    await s3.initialize()

    row_id = None
    object_key = None
    checks = {
        "vault_wrap": False,
        "raw_key_omitted": False,
        "rest_download": False,
        "plaintext_match": False,
        "cleanup": False,
    }
    try:
        users = await directus.get_items(
            "directus_users",
            params={
                "filter": {"vault_key_id": {"_nnull": True}},
                "fields": "id,vault_key_id",
                "limit": 1,
            },
            no_cache=True,
        )
        if not users or not users[0].get("id") or not users[0].get("vault_key_id"):
            raise RuntimeError("eligible_dev_user_unavailable")

        user_id = str(users[0]["id"])
        vault_key_id = str(users[0]["vault_key_id"])
        plaintext = b"OpenMates wrapped-key media verification"
        encrypted = encrypt_media_variants({"original": plaintext}, write_version=2)
        wrapped_key, _ = await encryption.encrypt_with_user_key(encrypted.aes_key_b64, vault_key_id)
        if not wrapped_key:
            raise RuntimeError("vault_wrap_failed")
        checks["vault_wrap"] = True

        asset_id = str(uuid.uuid4())
        object_key = f"verification/{asset_id}/original.bin"
        await s3.upload_file(
            bucket_key="chatfiles",
            file_key=object_key,
            content=encrypted.payloads["original"],
            content_type="application/octet-stream",
        )
        record = {
            "embed_id": asset_id,
            "user_id": user_id,
            "content_hash": hashlib.sha256(plaintext).hexdigest(),
            "original_filename": "wrapped-key-verification.bin",
            "content_type": "application/octet-stream",
            "file_size_bytes": len(plaintext),
            "s3_base_url": "",
            "files_metadata": {
                "original": {
                    "s3_key": object_key,
                    "size_bytes": len(encrypted.payloads["original"]),
                    "format": "bin",
                    "encryption": MEDIA_ENCRYPTION_V2,
                }
            },
            "aes_nonce": "",
            "vault_wrapped_aes_key": wrapped_key,
            "malware_scan": "clean",
            "created_at": int(time.time()),
        }
        success, created = await directus.create_item("upload_files", record)
        if not success or not created or not created.get("id"):
            raise RuntimeError("temporary_index_failed")
        row_id = str(created["id"])
        checks["raw_key_omitted"] = "aes_key" not in record

        token = create_download_token(asset_id=asset_id, user_id=user_id, variant="original")
        async with httpx.AsyncClient(timeout=30, follow_redirects=True) as client:
            response = await client.get(
                f"{PUBLIC_API_URL}/v1/generated-assets/{asset_id}/files/original/download",
                params={"token": token},
            )
        checks["rest_download"] = response.status_code == 200
        checks["plaintext_match"] = response.content == plaintext
    except Exception as exc:
        print(json.dumps({"status": "fail", "error": type(exc).__name__, "checks": checks}))
        return 1
    finally:
        cleanup_ok = True
        if row_id:
            cleanup_ok = bool(await directus.delete_item("upload_files", row_id)) and cleanup_ok
        if object_key:
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
