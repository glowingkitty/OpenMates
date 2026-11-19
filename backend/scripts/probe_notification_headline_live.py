"""Dev-only proof for a real chat: read the headline the pipeline staged and show the push.

Runs in the dev API container after a real chat reply. It finds the user (operator
input: account e-mail on stdin, never printed), opens the Vault-sealed
`notification_headline:*` entries that user's chats staged, and for the newest one
composes the push exactly like the dispatcher and seals it to a throwaway device
key (see probe_notification_summary_push.seal_and_open). The chat title is passed
in by the operator because real titles are client-side encrypted and unknown here.

    echo '{"email": "..."}' | docker exec -i api python \
        /app/backend/scripts/probe_notification_headline_live.py --chat-title "Example garden shop"
"""
from __future__ import annotations

import argparse
import asyncio
import base64
import hashlib
import json
import sys

sys.path[:0] = ["/app", "/app/backend"]

from backend.apps.ai.processing.notification_summary import NOTIFICATION_ICONS  # noqa: E402
from backend.core.api.app.services.cache import CacheService  # noqa: E402
from backend.core.api.app.services.directus.directus import DirectusService  # noqa: E402
from backend.core.api.app.utils.encryption import EncryptionService  # noqa: E402
from backend.scripts.probe_notification_summary_push import seal_and_open  # noqa: E402


async def newest_headline(email: str) -> dict:
    cache, directus, encryption = CacheService(), DirectusService(), EncryptionService()
    try:
        hashed = base64.b64encode(hashlib.sha256(email.strip().lower().encode()).digest()).decode()
        ok, user, _ = await directus.get_user_by_hashed_email(hashed)
        if not ok or not user:
            raise SystemExit("account lookup failed")
        ok, profile, _ = await directus.get_user_profile(user["id"])
        client = await cache.client
        found = []
        async for key in client.scan_iter(match="notification_headline:*"):
            ciphertext = await client.get(key)
            ttl = await client.ttl(key)
            try:
                found.append((ttl, json.loads(await encryption.decrypt_with_user_key(
                    ciphertext.decode() if isinstance(ciphertext, bytes) else ciphertext, profile["vault_key_id"]))))
            except Exception:  # noqa: BLE001 - other users' entries do not open with this key; skipping them is the point
                continue
        if not found:
            raise SystemExit("no staged headline for this account (expired or not produced)")
        return max(found, key=lambda item: item[0])[1]
    finally:
        await directus.close()
        await cache.close()


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--chat-title", required=True)
    parser.add_argument("--preview", default="")
    args = parser.parse_args()
    staged = asyncio.run(newest_headline(json.loads(sys.stdin.read())["email"]))
    headline = f"{NOTIFICATION_ICONS[staged['type']]} {staged['summary']}"
    wire, opened = seal_and_open(headline, args.chat_title, args.preview)
    print(json.dumps({"staged_by_pipeline": staged, "summary_chars": len(staged["summary"]),
                      "on_the_wire_to_apns": wire, "decrypted_on_device": opened}, indent=2, ensure_ascii=False))
    print("live notification headline proof passed")


if __name__ == "__main__":
    main()
