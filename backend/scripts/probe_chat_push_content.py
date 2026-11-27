"""Dev-only proof: assistant reply -> chat push content -> device-sealed APNs payload.

Run in the dev API container (synthetic reply, synthetic device key, nothing is
sent to Apple, no user data):

    docker exec api python /app/backend/scripts/probe_chat_push_content.py [language]

It projects a realistic markdown/embed/code reply exactly like the completion
dispatcher, composes the notification (chat title as title, answer excerpt as
body), seals it with the production APNs code for a throwaway device key and
prints what travels on the wire next to what the device decrypts.
"""
from __future__ import annotations

import base64
import json
import os
import sys
from types import SimpleNamespace
from unittest.mock import patch

from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import x25519
from cryptography.hazmat.primitives.ciphers.aead import AESGCM
from cryptography.hazmat.primitives.kdf.hkdf import HKDF

SYNTHETIC_REPLY = (
    "```json\n{\"type\":\"app_skill_use\",\"embed_id\":\"synthetic\",\"app_id\":\"web\",\"skill_id\":\"search\"}\n```\n"
    "## Raised beds for a small garden\n\n"
    "**Good news:** a 1.2 m wide bed is the sweet spot, because you can reach the middle from both sides "
    "without stepping on the soil. Here is a simple plan:\n\n"
    "- Fill the bottom third with branches and coarse compost.\n"
    "- Add a layer of leaves, then 20 cm of good topsoil.\n"
    "- Plant tomatoes on the sunny side and lettuce in the shade of them.\n\n"
    "| Plant | Spacing |\n|---|---|\n| Tomato | 50 cm |\n| Lettuce | 25 cm |\n\n"
    "```python\nprint('synthetic code that must not appear')\n```\n"
    "Water in the morning and mulch with straw to keep the soil moist through the summer. "
    "If you want, I can also draw up a planting calendar for the whole season, including "
    "succession sowing so you get a continuous harvest from May until the first frost."
) * 3
CHAT_TITLE = "Garden planning notes"


def _b64(value: bytes) -> str:
    return base64.urlsafe_b64encode(value).decode().rstrip("=")


def _unb64(value: str) -> bytes:
    return base64.urlsafe_b64decode(value + "=" * (-len(value) % 4))


def seal_and_open(language: str) -> tuple[dict, dict, int]:
    from backend.core.api.app.services.push_notification_content import compose_push_content
    from backend.core.api.app.services.push_notification_service import (
        APNS_CHAT_CATEGORY, APNS_ENCRYPTION_INFO, APNS_ENCRYPTION_VERSION, PushNotificationService,
        notification_preview_text,
    )
    content = compose_push_content(preferences={}, chat_title=CHAT_TITLE, hidden=False,
                                   preview_text=notification_preview_text(SYNTHETIC_REPLY, lang=language))
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
            target, content.title, content.body, "synthetic-chat", APNS_CHAT_CATEGORY, None,
            encrypted_title=content.sealed_title, encrypted_context=content.context, language=language)
    assert sent and captured, "APNs send path did not run"
    wire = captured[0]
    envelope = wire["encrypted_notification"]
    ephemeral = x25519.X25519PublicKey.from_public_bytes(_unb64(envelope["ephemeral_public_key"]))
    key = HKDF(algorithm=hashes.SHA256(), length=32, salt=None, info=APNS_ENCRYPTION_INFO).derive(private.exchange(ephemeral))
    opened = json.loads(AESGCM(key).decrypt(_unb64(envelope["nonce"]), _unb64(envelope["ciphertext"]), None))
    wire_text = json.dumps(wire, ensure_ascii=False)
    assert CHAT_TITLE not in wire_text and "raised" not in wire_text.lower()
    assert opened["title"] == CHAT_TITLE and opened["body"].endswith("…") and "\n" in opened["body"]
    assert "synthetic code" not in opened["body"] and "app_skill_use" not in opened["body"]
    size = len(json.dumps(wire, ensure_ascii=False, separators=(",", ":")).encode("utf-8"))
    return wire, opened, size


def main() -> None:
    language = sys.argv[1] if len(sys.argv) > 1 else "en"
    wire, opened, size = seal_and_open(language)
    # Synthetic fixture text only; no user data passes through this probe.
    sys.stdout.write(f"APNs alert (public): {json.dumps(wire['aps']['alert'], ensure_ascii=False)}\n")
    sys.stdout.write(f"APNs payload bytes: {size} of 4096\n")
    sys.stdout.write(f"Device title: {opened['title']}\nDevice body:\n{opened['body']}\n")
    print("chat push content proof passed")


if __name__ == "__main__":
    main()
