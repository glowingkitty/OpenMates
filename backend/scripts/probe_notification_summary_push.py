"""Dev-only proof: real post-processing model -> push content -> device-sealed APNs payload.

Run in the dev API container (synthetic reply, synthetic device key, no network
send to APNs, no user data):

    docker exec api python /app/backend/scripts/probe_notification_summary_push.py

It calls the production `handle_postprocessing` (production model and tool, only the
bounded decision step is frozen), composes the push exactly like the dispatcher,
seals it with the production APNs envelope code for a throwaway device key and
prints what travels on the wire next to what the device decrypts.
"""
from __future__ import annotations

import asyncio
import base64
import json
import logging
import os
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

import yaml
from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import x25519
from cryptography.hazmat.primitives.ciphers.aead import AESGCM
from cryptography.hazmat.primitives.kdf.hkdf import HKDF

SYNTHETIC_REPLY = (
    "I added 4 Gemini models to the provider config and ran the test suite: 31 tests pass. "
    "The changes are in providers/google.yml. (Synthetic reply for a notification proof.)"
)
CHAT_TITLE = "Garden planning notes"


def _b64(value: bytes) -> str:
    return base64.urlsafe_b64encode(value).decode().rstrip("=")


def _unb64(value: str) -> bytes:
    return base64.urlsafe_b64decode(value + "=" * (-len(value) % 4))


def seal_and_open(headline: str, chat_title: str, preview_text: str) -> tuple[dict, dict]:
    """Compose the push like the dispatcher, send it through the production APNs code
    to a capturing client (nothing reaches Apple) and open it with a throwaway device key.

    Returns (what goes to APNs, what the device decrypts)."""
    from backend.core.api.app.services.push_notification_content import compose_push_content
    from backend.core.api.app.services.push_notification_service import (
        APNS_CHAT_CATEGORY, APNS_ENCRYPTION_INFO, APNS_ENCRYPTION_VERSION, PushNotificationService,
    )
    content = compose_push_content(preferences={}, headline=headline, chat_title=chat_title, mate_name="Mate",
                                   preview_text=preview_text, hidden=False)

    private = x25519.X25519PrivateKey.generate()
    public = private.public_key().public_bytes(serialization.Encoding.Raw, serialization.PublicFormat.Raw)
    target = {"type": "apns", "token": "synthetic-device", "encryption_version": APNS_ENCRYPTION_VERSION,
              "notification_public_key": _b64(public)}
    captured: list[dict] = []

    class CapturingClient:
        """Stands in for the HTTP client so nothing reaches Apple; keeps the exact request body."""
        def __init__(self, **kwargs): pass
        def __enter__(self): return self
        def __exit__(self, *args): return False
        def post(self, url, json, headers):
            captured.append(json)
            return SimpleNamespace(status_code=200, text="")

    os.environ.update(APNS_TEAM_ID="synthetic-team", APNS_KEY_ID="synthetic-key", APNS_PRIVATE_KEY="synthetic-key-material")
    service = PushNotificationService()
    with patch("httpx.Client", CapturingClient), patch.object(service, "_build_apns_jwt", lambda **kwargs: "synthetic-auth"):
        sent = service._send_apns_notification(
            target, content.title if content.sealed_title is None else "OpenMates", content.body, "synthetic-chat",
            APNS_CHAT_CATEGORY, None, encrypted_title=content.sealed_title, encrypted_context=content.context)
    assert sent and captured, "APNs send path did not run"
    wire = captured[0]
    envelope = wire["encrypted_notification"]
    ephemeral = x25519.X25519PublicKey.from_public_bytes(_unb64(envelope["ephemeral_public_key"]))
    key = HKDF(algorithm=hashes.SHA256(), length=32, salt=None, info=APNS_ENCRYPTION_INFO).derive(private.exchange(ephemeral))
    opened = json.loads(AESGCM(key).decrypt(_unb64(envelope["nonce"]), _unb64(envelope["ciphertext"]), None))
    wire_text = json.dumps(wire, ensure_ascii=False)
    assert headline.split(" ", 1)[1] not in wire_text and chat_title not in wire_text
    assert opened["title"] == headline and opened["body"] == f'in "{chat_title}"'
    return wire, opened


async def main() -> None:
    from backend.apps.ai.processing import postprocessor
    from backend.core.api.app.utils.secrets_manager import SecretsManager

    logging.disable(logging.CRITICAL)
    instructions = yaml.safe_load((Path(__file__).resolve().parents[1] / "apps/ai/base_instructions.yml").read_text())
    manager = SecretsManager()
    await manager.initialize()
    try:
        async def frozen_decisions(**_kwargs):
            return {"harmful_response": 0.0, "top_recommended_apps_for_user": ["web"]}
        with patch.object(postprocessor, "_postprocessing_decisions_with_jev", frozen_decisions):
            result = await postprocessor.handle_postprocessing(
                task_id="synthetic-notification-proof", user_message="Add the Gemini models and run the tests.",
                assistant_response=SYNTHETIC_REPLY, chat_summary=None, chat_tags=[],
                message_history=[{"role": "user", "content": "Add the Gemini models and run the tests."}],
                base_instructions=instructions, secrets_manager=manager, cache_service=None,
                available_app_ids=["web"], output_language="en", user_system_language="en",
                translate_ui_metadata=False,
            )
    finally:
        await manager.close()
    assert result and result.notification_type and result.notification_summary, "model returned no usable summary"
    headline = f"{postprocessor_icons()[result.notification_type]} {result.notification_summary}"
    wire, opened = seal_and_open(headline, CHAT_TITLE, SYNTHETIC_REPLY)
    print(json.dumps({"model_type": result.notification_type, "model_summary": result.notification_summary,
                      "summary_chars": len(result.notification_summary),
                      "on_the_wire_to_apns": wire, "decrypted_on_device": opened}, indent=2, ensure_ascii=False))
    print("notification summary push proof passed")


def postprocessor_icons() -> dict[str, str]:
    from backend.apps.ai.processing.notification_summary import NOTIFICATION_ICONS
    return NOTIFICATION_ICONS


if __name__ == "__main__":
    asyncio.run(main())
