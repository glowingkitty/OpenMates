#!/usr/bin/env python3
# contract-test-file: tooling
"""Inspect the documented Mistral model catalogue without generating audio.

Runs inside the API container with its existing Vault-backed provider access.
Prints only public TTS model identifiers and capability availability booleans.
Catalogue presence does not establish a realtime text-input protocol.
Usage: docker exec -i api python - < backend/scripts/test_mistral_realtime_tts_availability.py
"""

from __future__ import annotations

import asyncio
import json
import logging

import httpx

from backend.core.api.app.utils.secrets_manager import SecretsManager


async def main() -> int:
    logging.basicConfig(level=logging.CRITICAL)
    secrets = SecretsManager()
    try:
        await secrets.initialize()
        key = await secrets.get_secret("kv/data/providers/mistral_ai", "api_key")
        if not key or key == "IMPORTED_TO_VAULT":
            print(json.dumps({"status": "unavailable", "reason": "provider_credentials_unavailable"}))
            return 1
        async with httpx.AsyncClient(timeout=15) as client:
            response = await client.get(
                "https://api.mistral.ai/v1/models",
                headers={"Authorization": f"Bearer {key}"},
            )
            if response.status_code != 200:
                print(json.dumps({"status": "unavailable", "http_status": response.status_code}))
                return 1
            rows = response.json().get("data", [])
            identifiers = sorted({row["id"] for row in rows
                                  if isinstance(row, dict) and isinstance(row.get("id"), str)
                                  and "tts" in row["id"].lower()})
            print(json.dumps({
                "status": "pass",
                "tts_models": identifiers,
                "realtime_tts_listed": "voxtral-mini-tts-realtime-3-0" in identifiers,
                "complete_text_tts_listed": "voxtral-mini-tts-3-0" in identifiers,
                "paid_generation_requests": 0,
            }))
            return 0
    except (httpx.HTTPError, ValueError, TypeError, KeyError):
        print(json.dumps({"status": "unavailable", "reason": "catalogue_check_failed"}))
        return 1
    finally:
        await secrets.aclose()


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
