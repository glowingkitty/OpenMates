"""Runner-private chat email probe using real broker, worker, Directus and Mailpit.

The completion is synthetic; notification enqueue, delayed worker dispatch,
eligibility, reservation, rendering and SMTP are production code paths.
"""

from __future__ import annotations

import asyncio
import hashlib
import html
import json
import os
import re
import time
import uuid
from datetime import datetime

import httpx

from backend.core.api.app.services.cache import CacheService
from backend.core.api.app.services.chat_email_notification_service import (
    candidate_key, enqueue_chat_email,
)
from backend.core.api.app.services.directus import DirectusService
from backend.core.api.app.services.email_delivery_guard import build_delivery_id, build_delivery_key
from backend.core.api.app.services.notification_presence import (
    classify_lifecycle_client, clear_presence, mark_message_viewed,
    refresh_legacy_apple_presence_on_message, report_presence,
)
from backend.core.api.app.services.team_chat_notification_service import (
    issue_preview_capability, queue_committed_team_message, stage_team_preview,
)
from backend.core.api.app.utils.encryption import EncryptionService
from backend.core.api.app.utils.newsletter_utils import hash_email


def _require_isolation() -> str:
    required = {"CI": "true", "OPENMATES_CI_ISOLATED": "1", "OPENMATES_CI_MAIL_CAPTURE": "1",
                "CMS_URL": "http://cms:8055", "SERVER_ENVIRONMENT": "development"}
    if any(os.getenv(key) != value for key, value in required.items()):
        raise RuntimeError("Chat email probe requires isolated CI Mailpit stack")
    email = os.getenv("PROBE_EMAIL", "").lower()
    if not re.fullmatch(r"ci-[a-z0-9+._-]+@example\.com", email):
        raise RuntimeError("Chat email probe requires a fresh CI example.com account")
    return email


def _admin() -> httpx.Client:
    client = httpx.Client(base_url="http://cms:8055", timeout=20)
    response = client.post("/auth/login", json={"email": os.environ["DATABASE_ADMIN_EMAIL"],
                                                "password": os.environ["DATABASE_ADMIN_PASSWORD"], "mode": "json"})
    response.raise_for_status()
    client.headers["Authorization"] = "Bearer " + response.json()["data"]["access_token"]
    return client


def _data(response: httpx.Response):
    response.raise_for_status()
    return response.json()["data"]


def _one(client: httpx.Client, path: str, filters: dict[str, str]) -> dict:
    rows = _data(client.get(path, params={**filters, "limit": 2}))
    if not isinstance(rows, list) or len(rows) != 1:
        raise AssertionError(f"Expected one isolated fixture at {path}")
    return rows[0]


def _json_object(value: object) -> dict:
    if isinstance(value, str):
        value = json.loads(value)
    return dict(value) if isinstance(value, dict) else {}


def _mailpit_messages(client: httpx.Client, email: str, since: float) -> list[dict]:
    response = client.get("/api/v1/messages?limit=100")
    response.raise_for_status()
    matches = []
    for item in response.json().get("messages", []):
        subject = item.get("Subject") or ""
        if "messaged you in OpenMates" not in subject and "New message from" not in subject:
            continue
        if not any(address.get("Address", "").lower() == email for address in item.get("To", [])):
            continue
        created = datetime.fromisoformat(item["Created"].replace("Z", "+00:00")).timestamp()
        if created + 2 < since:
            continue
        full = client.get(f"/api/v1/message/{item['ID']}")
        full.raise_for_status()
        matches.append((created, item['ID'], full.json()))
    return [message for _, _, message in sorted(matches, key=lambda match: match[:2])]


async def _wait_for_mail(client: httpx.Client, email: str, since: float, expected: int, timeout: float = 75) -> list[dict]:
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        messages = _mailpit_messages(client, email, since)
        if len(messages) >= expected:
            return messages
        await asyncio.sleep(1)
    raise AssertionError(f"Expected {expected} captured chat emails; got {len(_mailpit_messages(client, email, since))}")


async def _run(admin: httpx.Client, email: str, user: dict) -> None:
    user_id = user["id"]
    chat_id = str(uuid.uuid4())
    now = int(time.time())
    original = {key: user.get(key) for key in (
        "email_notifications_enabled", "email_notification_preferences", "email_notification_preference_choices",
    )}
    preferences = _json_object(user.get("email_notification_preferences"))
    choices = _json_object(user.get("email_notification_preference_choices"))
    cache = CacheService()
    encryption = EncryptionService()
    directus = DirectusService(encryption_service=encryption)
    mailpit = httpx.Client(base_url="http://mailpit:8025", timeout=10)
    candidate_keys = []
    delivery_ids = []
    extra_fixtures = []
    chat_created = False
    preferences_patched = False
    try:
        contact = _one(admin, "/items/account_contact_emails", {
            "filter[user_id][_eq]": user_id, "filter[hashed_email][_eq]": user["hashed_email"],
        })
        assert contact.get("verified_at") and contact.get("purpose") == "account_lifecycle"
        preferences.update(aiResponses=True, includeContent=False)
        choices["aiResponses"] = {"source": "user", "value": True}
        choices["includeContent"] = {"source": "user", "value": False}
        _data(admin.patch(f"/users/{user_id}", json={
            "email_notifications_enabled": True, "email_notification_preferences": preferences,
            "email_notification_preference_choices": choices,
        }))
        preferences_patched = True
        _data(admin.post("/items/chats", json={
            "id": chat_id, "hashed_user_id": hashlib.sha256(user_id.encode()).hexdigest(),
            "messages_v": 0, "title_v": 0, "metadata_v": 0, "unread_count": 0,
            "created_at": now, "updated_at": now, "last_edited_overall_timestamp": now,
            "last_message_timestamp": now,
        }))
        chat_created = True
        assert await encryption.initialize()
        since = time.time()

        async def enqueue(message_id: str, *, preview: str, title: str = "") -> bool:
            key = candidate_key(user_id, chat_id, message_id)
            candidate_keys.append(key)
            delivery_ids.append(build_delivery_id(build_delivery_key(
                email_type="chat_response", campaign_key=message_id,
                recipient_kind="directus_user", recipient_id=user_id, stage=chat_id,
            )))
            return await enqueue_chat_email(
                cache_service=cache, directus_service=directus, encryption_service=encryption,
                user_id=user_id, chat_id=chat_id, message_id=message_id,
                sender_name="Mate", preview=preview, title=title,
            )

        private_marker = "PRIVATE-CI-CHAT-CONTENT"
        first = str(uuid.uuid4())
        assert await enqueue(first, preview=private_marker, title="Private chat title")
        assert not await enqueue(first, preview=private_marker, title="Private chat title")
        raw = await (await cache.client).get(candidate_keys[-1])
        assert raw and private_marker.encode() not in raw and b"Private chat title" not in raw
        candidate = json.loads(raw)
        assert "encrypted_preview" not in candidate
        messages = await _wait_for_mail(mailpit, email, since, 1)
        assert len(messages) == 1
        body = html.unescape(messages[0].get("HTML") or "")
        assert private_marker not in body and "Private chat title" not in body
        assert f"/#chat-id={chat_id}" in body
        assert "/#settings/notifications/chat" in body
        assert "token=" not in body and "share=" not in body
        anonymous = httpx.get(f"http://api:8000/v1/chats/{chat_id}/messages/window", timeout=10)
        assert anonymous.status_code in (401, 403), anonymous.status_code

        # Revoke consent after queueing. The worker must read Directus again.
        revoked = str(uuid.uuid4())
        assert await enqueue(revoked, preview="REVOKED-MUST-NOT-EMAIL")
        preferences["aiResponses"] = False
        choices["aiResponses"] = {"source": "user", "value": False}
        _data(admin.patch(f"/users/{user_id}", json={"email_notification_preferences": preferences,
                                                    "email_notification_preference_choices": choices}))
        await asyncio.sleep(20)
        assert len(_mailpit_messages(mailpit, email, since)) == 1

        preferences.update(aiResponses=True, includeContent=True)
        choices["aiResponses"] = {"source": "user", "value": True}
        choices["includeContent"] = {"source": "user", "value": True}
        _data(admin.patch(f"/users/{user_id}", json={"email_notification_preferences": preferences,
                                                    "email_notification_preference_choices": choices}))
        preview_marker = "<script>PREVIEW-ESCAPED</script>"
        preview = preview_marker + "\n" + "\n".join(f"line {i}" for i in range(1, 20))
        opted_in = str(uuid.uuid4())
        assert await enqueue(opted_in, preview=preview, title="T" * 80)
        raw = await (await cache.client).get(candidate_keys[-1])
        assert raw and preview_marker.encode() not in raw and b"line 1" not in raw
        assert b"encrypted_preview" in raw
        messages = await _wait_for_mail(mailpit, email, since, 2)
        assert len(messages) == 2
        opted_body = messages[-1].get("HTML") or ""
        assert "T" * 60 in opted_body and "T" * 61 not in opted_body
        assert "&lt;script&gt;PREVIEW-ESCAPED&lt;/script&gt;" in opted_body
        assert preview_marker not in opted_body and "line 10" not in opted_body

        viewed = str(uuid.uuid4())
        assert await enqueue(viewed, preview="VIEWED-MUST-NOT-EMAIL")
        await mark_message_viewed(cache, user_id, chat_id, viewed)
        await asyncio.sleep(20)
        assert len(_mailpit_messages(mailpit, email, since)) == 2

        active = str(uuid.uuid4())
        assert await enqueue(active, preview="ACTIVE-MUST-NOT-EMAIL")
        await report_presence(cache, user_id, "probe-web-connection", "web", True, now=time.time())
        try:
            await asyncio.sleep(20)
            assert len(_mailpit_messages(mailpit, email, since)) == 2
        finally:
            await clear_presence(cache, user_id, "probe-web-connection")

        # Installed Apple clients declare lifecycle without client_type. Their
        # existing headers classify that declaration, and foreground elsewhere
        # still suppresses the real delayed worker globally. A headerless SDK
        # connection must not acquire this human lease.
        assert classify_lifecycle_client({}, {}) == ("automation", False)
        assert classify_lifecycle_client({}, {
            "user-agent": "OpenMates-Apple/1.0",
            "x-openmates-client": "macos",
            "x-openmates-bundle-id": "org.openmates.mac",
        }) == ("apple", True)
        legacy_apple = str(uuid.uuid4())
        assert await enqueue(legacy_apple, preview="LEGACY-APPLE-MUST-NOT-EMAIL")
        await refresh_legacy_apple_presence_on_message(
            cache, user_id, "probe-legacy-apple", True, chat_id=str(uuid.uuid4()),
        )
        try:
            await asyncio.sleep(20)
            assert len(_mailpit_messages(mailpit, email, since)) == 2
        finally:
            await refresh_legacy_apple_presence_on_message(cache, user_id, "probe-legacy-apple", False)

        # A synthetic committed Team message exercises the real recipient-
        # consent capability, per-recipient Vault staging, fanout and SMTP.
        # The recipient remains the actual verified isolated signup account.
        # Permanent chat ciphertext has no server-readable chat key fixture.
        team_id, sender_id = str(uuid.uuid4()), str(uuid.uuid4())
        team_hash = hashlib.sha256(team_id.encode()).hexdigest()
        sender_hash = hashlib.sha256(sender_id.encode()).hexdigest()
        _data(admin.post("/users", json={"id": sender_id, "status": "active"}))
        extra_fixtures.append(("/users", sender_id))
        team = _data(admin.post("/items/teams", json={
            "team_id": team_id, "hashed_team_id": team_hash,
            "encrypted_name": "opaque-client-team-ciphertext",
            "created_by_user_hash": sender_hash, "status": "active",
            "created_at": now, "updated_at": now,
        }))
        extra_fixtures.append(("/items/teams", team["id"]))
        for member_id, role in ((sender_id, "owner"), (user_id, "member")):
            membership = _data(admin.post("/items/team_memberships", json={
                "hashed_team_id": team_hash,
                "hashed_user_id": hashlib.sha256(member_id.encode()).hexdigest(),
                "role": role, "status": "active", "created_at": now, "updated_at": now,
            }))
            extra_fixtures.append(("/items/team_memberships", membership["id"]))
        _data(admin.patch(f"/items/chats/{chat_id}", json={"hashed_team_id": team_hash}))
        team_message_id = str(uuid.uuid4())
        capability = await issue_preview_capability(
            directus=directus, cache=cache, team_id=team_id, chat_id=chat_id, sender_id=sender_id,
        )
        assert capability["recipient_count"] == 1 and capability["capability_id"]
        team_preview = "<strong>TEAM-PREVIEW-ESCAPED</strong>"
        assert await stage_team_preview(
            directus=directus, cache=cache, encryption=encryption, team_id=team_id,
            chat_id=chat_id, message_id=team_message_id, sender_id=sender_id,
            capability_id=capability["capability_id"], preview=team_preview, title="Team preview title",
        ) == 1
        committed = _data(admin.post("/items/messages", json={
            "client_message_id": team_message_id, "chat_id": chat_id,
            "hashed_user_id": sender_hash, "role": "user",
            "encrypted_content": "opaque-client-message-ciphertext", "created_at": now,
        }))
        extra_fixtures.append(("/items/messages", committed["id"]))
        team_candidate_key = candidate_key(user_id, chat_id, team_message_id)
        candidate_keys.append(team_candidate_key)
        delivery_ids.append(build_delivery_id(build_delivery_key(
            email_type="chat_response", campaign_key=team_message_id,
            recipient_kind="directus_user", recipient_id=user_id, stage=chat_id,
        )))
        assert await queue_committed_team_message(
            directus=directus, cache=cache, encryption=encryption, team_id=team_id,
            chat_id=chat_id, message_id=team_message_id, sender_id=sender_id,
        ) == 1
        raw = await (await cache.client).get(team_candidate_key)
        assert raw and team_preview.encode() not in raw and b"encrypted_preview" in raw
        team_messages = await _wait_for_mail(mailpit, email, since, 3)
        assert len(team_messages) == 3
        assert "&lt;strong&gt;TEAM-PREVIEW-ESCAPED&lt;/strong&gt;" in team_messages[-1].get("HTML", "")
        assert team_preview not in team_messages[-1].get("HTML", "")
        assert f"/#chat-id={chat_id}&team-id={team_id}" in html.unescape(team_messages[-1].get("HTML", ""))
    finally:
        redis = await cache.client
        for key in candidate_keys:
            await redis.delete(key)
        for delivery_id in delivery_ids:
            response = admin.delete(f"/items/email_deliveries/{delivery_id}")
            if response.status_code not in (200, 204, 404):
                raise RuntimeError("Failed to remove disposable email delivery fixture")
        for path, fixture_id in reversed(extra_fixtures):
            response = admin.delete(f"{path}/{fixture_id}")
            if response.status_code not in (200, 204, 404):
                raise RuntimeError("Failed to remove disposable Team notification fixture")
        if chat_created:
            response = admin.delete(f"/items/chats/{chat_id}")
            if response.status_code not in (200, 204, 404):
                raise RuntimeError("Failed to remove disposable chat fixture")
        if preferences_patched:
            _data(admin.patch(f"/users/{user_id}", json=original))
        mailpit.close()
        await directus.close()
        await encryption.close()
        await cache.close()


async def main() -> None:
    email = _require_isolation()
    admin = _admin()
    try:
        user = _one(admin, "/users", {"filter[hashed_email][_eq]": hash_email(email)})
        await _run(admin, email, user)
    finally:
        admin.close()
    print("real chat response Mailpit roundtrip passed")


if __name__ == "__main__":
    asyncio.run(main())
