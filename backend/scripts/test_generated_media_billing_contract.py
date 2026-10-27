#!/usr/bin/env python3
# contract-test-file: infrastructure
"""Exercise actual media charge helpers and ledger replay in disposable CI only."""
from __future__ import annotations

import asyncio
import base64
import hashlib
import json
import logging
import os
import sys
import uuid
from pathlib import Path
from typing import Any

import httpx

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))


async def run() -> None:
    """Charge completed synthetic outputs without invoking any paid provider."""
    if (os.getenv("SERVER_ENVIRONMENT") != "development"
            or os.getenv("PRODUCTION_URL") != "http://localhost:5173"):
        raise RuntimeError("Disposable isolated CI API required")
    email = json.load(sys.stdin)["email"]
    allowed = {value for key, value in os.environ.items()
               if key.startswith("OPENMATES_TEST_ACCOUNT_CI_") and key.endswith("_EMAIL")}
    if email not in allowed or not os.getenv("INTERNAL_API_SHARED_TOKEN"):
        raise RuntimeError("Fresh allowlisted CI owner and internal credential required")

    from backend.core.api.app.services.cache import CacheService
    from backend.core.api.app.services.directus.directus import DirectusService
    from backend.core.api.app.utils.encryption import EncryptionService
    from backend.apps.audio.tasks.common import charge_audio_generation_credits
    from backend.apps.code.tasks.image_to_html_task import charge_image_to_html_credits
    from backend.apps.images.tasks.generate_task import _charge_image_generation_credits
    from backend.apps.images.tasks.vectorize_task import _charge_vectorize_credits
    from backend.apps.models3d.billing import charge_model_generation_credits
    from backend.apps.music.tasks.generate_task import _charge_music_generation_credits
    from backend.apps.videos.tasks.generate_task import _charge_video_generation_credits
    from backend.apps.videos.tasks.render_remotion_task import _charge_remotion_render_credits

    cache = CacheService()
    encryption = EncryptionService(cache_service=cache)
    directus = DirectusService(cache_service=cache, encryption_service=encryption)
    try:
        hashed_email = base64.b64encode(hashlib.sha256(email.strip().lower().encode()).digest()).decode()
        users = await directus.get_items("directus_users", params={
            "filter[hashed_email][_eq]": hashed_email, "fields": "id,vault_key_id", "limit": 2,
        }, no_cache=True, admin_required=True, raise_on_error=True)
        assert len(users) == 1
        owner = users[0]
        owner_id = owner["id"]
        owner_hash = hashlib.sha256(owner_id.encode()).hexdigest()

        async def balance() -> int:
            rows = await directus.get_items("directus_users", params={
                "filter[id][_eq]": owner_id, "fields": "encrypted_credit_balance", "limit": 1,
            }, no_cache=True, admin_required=True, raise_on_error=True)
            return int(await encryption.decrypt_with_user_key(rows[0]["encrypted_credit_balance"], owner["vault_key_id"]))

        async def rows_for(collection: str, charge_id: str, fields: str) -> list[dict[str, Any]]:
            return await directus.get_items(collection, params={
                "filter[charge_id][_eq]": charge_id, "fields": fields, "limit": 2,
            }, no_cache=True, admin_required=True, raise_on_error=True)

        common = {"user_id": owner_id, "user_id_hash": owner_hash,
                  "chat_id": None, "message_id": None, "log_prefix": "[isolated-media-billing]"}
        cases: list[tuple[str, Any, dict[str, Any]]] = [
            ("video", _charge_video_generation_credits, {
                **common, "app_id": "videos", "skill_id": "generate",
                "model_ref": "fal/minimax/h3-max-turbo/image-to-video", "model_id": "minimax/h3-max-turbo/image-to-video",
                "duration_seconds": 1.0, "resolution": "480p"}),
            ("image", _charge_image_generation_credits, {
                **common, "app_id": "images", "skill_id": "generate_draft", "model_ref": "bfl/flux-2-klein"}),
            ("music", _charge_music_generation_credits, {
                **common, "app_id": "music", "skill_id": "generate", "model_ref": "google/lyria-3-clip-preview"}),
            ("remotion", _charge_remotion_render_credits, {
                **common, "credits": 5, "runtime_seconds": 1, "auto_started": False, "source_version": 1}),
            ("image-to-html", charge_image_to_html_credits, {
                **{key: value for key, value in common.items() if key not in {"chat_id", "message_id"}},
                "app_id": "code", "skill_id": "image_to_html", "credits": 2,
                "usage_details": {}, "api_key_hash": None, "device_hash": None}),
            ("vectorize", _charge_vectorize_credits, {
                **common, "app_id": "images", "skill_id": "vectorize", "model_ref": "recraft/vectorize"}),
            ("models3d", charge_model_generation_credits, {
                **common, "app_id": "models3d", "skill_id": "generate", "credits": 2,
                "api_key_hash": None, "device_hash": None}),
        ]
        task_id = str(uuid.uuid4())
        for label, app_id, skill_id, request_id in [
            ("tts-child-0", "audio", "speak", "child:0"),
            ("tts-child-1", "audio", "speak", "child:1"),
            ("assistant-speech", "assistant_response_speech", "segment", "segment-0"),
        ]:
            cases.append((label, charge_audio_generation_credits, {
                "user_id": owner_id, "app_id": app_id, "skill_id": skill_id,
                "task_id": task_id, "request_id": request_id, "credits": 4,
                "model_ref": "elevenlabs/eleven_v3", "duration_seconds": 1.0,
                "chat_id": None, "message_id": None, "external_request": False,
                "api_key_hash": None, "device_hash": None, "api_key_name": None,
                "log_prefix": "[isolated-media-billing]", "raise_on_failure": True,
            }))

        before = await balance()
        assert before >= 250
        total = 0
        charge_ids = []
        headers = {"X-Internal-Service-Token": os.environ["INTERNAL_API_SHARED_TOKEN"]}
        async with httpx.AsyncClient(base_url="http://api:8000", headers=headers, timeout=45, trust_env=False) as client:
            denied = await client.post("/internal/billing/charge", headers={"X-Internal-Service-Token": "invalid"}, json={})
            assert denied.status_code == 403, f"Invalid internal token returned {denied.status_code}"
            for label, charge, kwargs in cases:
                event_id = str(uuid.uuid4())
                if charge is charge_audio_generation_credits:
                    charge_id = f"audio:{kwargs['task_id']}:{kwargs['request_id']}"
                else:
                    kwargs["event_id"] = event_id
                    charge_id = f"app-skill:{event_id}"
                charge_ids.append(charge_id)
                await charge(**kwargs)
                identities = await rows_for("billing_charge_identities", charge_id, "charge_id,charged_credits,usage_id")
                assert len(identities) == 1, f"{label}: missing committed charge"
                credits = identities[0]["charged_credits"]
                assert credits > 0
                total += credits
                assert await balance() == before - total, f"{label}: debit mismatch"
                await charge(**kwargs)
                assert await balance() == before - total, f"{label}: replay debited twice"
                replay = await rows_for("billing_charge_identities", charge_id, "charge_id,charged_credits,usage_id")
                assert replay == identities, f"{label}: replay changed identity"
                usage = await rows_for("usage", charge_id, "id,charge_id")
                assert len(usage) == 1 and usage[0]["id"] == identities[0]["usage_id"], f"{label}: raw usage mismatch"
            assert len(set(charge_ids)) == len(cases)
            for charge_id in charge_ids:
                identities = await rows_for("billing_charge_identities", charge_id, "charged_credits")
                payload = {"user_id": owner_id, "user_id_hash": owner_hash,
                           "credits": identities[0]["charged_credits"], "app_id": "system", "skill_id": "media_billing_contract",
                           "idempotency_key": f"{charge_id}:refund", "reason": "Disposable media billing proof cleanup"}
                refund = await client.post("/internal/billing/refund", json=payload)
                refund.raise_for_status()
            assert await balance() == before
        print(json.dumps({"passed": True, "flows": [label for label, _, _ in cases],
                          "charges": len(cases), "usage_rows": len(cases), "replay_debits": 0,
                          "balance_restored": True}))
    finally:
        await directus.close()
        await cache.close()


if __name__ == "__main__":
    logging.disable(logging.CRITICAL)
    asyncio.run(run())
