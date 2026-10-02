"""Runner-private product probe: real Directus digest to captured CI SMTP.

Invoked only by the isolated Playwright spec through Docker exec. Fixture writes
synthetic run metadata in the disposable CMS; email rendering, consent checks,
reservation and SMTP delivery use the production services.
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
from datetime import datetime, timedelta, timezone
from types import SimpleNamespace

import httpx

from backend.core.api.app.services.directus import DirectusService
from backend.core.api.app.services.email_template import EmailTemplateService
from backend.core.api.app.services.email_delivery_guard import build_delivery_id, build_delivery_key
from backend.core.api.app.services.workflow_digest_service import digest_window
from backend.core.api.app.tasks.email_tasks.workflow_digest_email_task import (
    _async_retry_workflow_digest, send_user_workflow_digest,
)
from backend.core.api.app.utils.encryption import EncryptionService
from backend.core.api.app.utils.newsletter_utils import hash_email
from backend.core.api.app.utils.secrets_manager import SecretsManager


def _require_isolation() -> str:
    required = {"CI": "true", "OPENMATES_CI_ISOLATED": "1", "OPENMATES_CI_MAIL_CAPTURE": "1",
                "CMS_URL": "http://cms:8055", "SERVER_ENVIRONMENT": "development"}
    if any(os.getenv(key) != expected for key, expected in required.items()):
        raise RuntimeError("Workflow digest probe requires the isolated CI mail stack")
    email = os.getenv("PROBE_EMAIL", "").lower()
    if not re.fullmatch(r"ci-[a-z0-9+._-]+@example\.com", email):
        raise RuntimeError("Workflow digest probe requires a fresh CI example.com account")
    os.environ["FRONTEND_URL"] = "http://localhost:5173"
    return email


def _admin() -> httpx.Client:
    client = httpx.Client(base_url="http://cms:8055", timeout=20)
    response = client.post("/auth/login", json={
        "email": os.environ["DATABASE_ADMIN_EMAIL"],
        "password": os.environ["DATABASE_ADMIN_PASSWORD"], "mode": "json",
    })
    response.raise_for_status()
    client.headers["Authorization"] = "Bearer " + response.json()["data"]["access_token"]
    return client


def _data(response: httpx.Response) -> dict | list:
    response.raise_for_status()
    return response.json()["data"]


def _one(client: httpx.Client, path: str, filters: dict[str, str]) -> dict:
    rows = _data(client.get(path, params={**filters, "limit": 2}))
    if not isinstance(rows, list) or len(rows) != 1:
        raise AssertionError(f"Expected one disposable fixture record at {path}")
    return rows[0]


def _create(client: httpx.Client, collection: str, payload: dict, cleanup: list[tuple[str, str]]) -> dict:
    row = _data(client.post(f"/items/{collection}", json=payload))
    assert isinstance(row, dict) and row.get("id")
    cleanup.append((collection, row["id"]))
    return row


def _mailpit_messages(client: httpx.Client, email: str, *, since: float) -> list[dict]:
    response = client.get("/api/v1/messages?limit=100")
    response.raise_for_status()
    matches: list[tuple[float, str, dict]] = []
    for item in response.json().get("messages", []):
        if item.get("Subject") != "Your daily Workflow runs":
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


def _json_object(value: object) -> dict:
    if isinstance(value, str):
        value = json.loads(value)
    return dict(value) if isinstance(value, dict) else {}


async def _send_fixture(
    admin: httpx.Client, email: str, user: dict, cleanup: list[tuple[str, str]],
) -> None:
    user_id = user["id"]
    owner_hash = "user_sha256:" + hashlib.sha256(user_id.encode()).hexdigest()
    delivery_hash = owner_hash.removeprefix("user_sha256:")
    cutoff = datetime.now(timezone.utc).replace(hour=9, minute=0, second=0, microsecond=0)
    if datetime.now(timezone.utc) < cutoff:
        cutoff -= timedelta(days=1)
    start, end = digest_window(cutoff)
    workflow_id = str(uuid.uuid4())
    version_id = str(uuid.uuid4())
    title = "Private Workflow title CI"
    output_marker = "PRIVATE-OUTPUT-MUST-NOT-EMAIL"
    private_message_marker = "PRIVATE-SEND-MESSAGE-MUST-NOT-EMAIL"
    preview_message_marker = "OPTED-IN-INTENDED-SEND-MESSAGE"

    secrets = SecretsManager()
    encryption = EncryptionService()
    directus = DirectusService(encryption_service=encryption)
    try:
        await secrets.initialize()
        assert await encryption.initialize()
        email_service = EmailTemplateService(secrets_manager=secrets)
        task = SimpleNamespace(directus_service=directus, encryption_service=encryption,
                               email_template_service=email_service)

        # Preserve an actual, verified signup contact. Consent is a disposable
        # user preference; this test never fabricates the address or verification.
        contact = _one(admin, "/items/account_contact_emails", {
            "filter[user_id][_eq]": user_id, "filter[hashed_email][_eq]": user["hashed_email"],
        })
        assert contact.get("verified_at") and contact.get("purpose") == "account_lifecycle"
        preferences = _json_object(user.get("email_notification_preferences"))
        choices = _json_object(user.get("email_notification_preference_choices"))
        preferences.update(workflowRuns=True, includeContent=False)
        choices["workflowRuns"] = {"source": "user", "value": True}
        _data(admin.patch(f"/users/{user_id}", json={
            "email_notifications_enabled": True,
            "email_notification_preferences": preferences,
            "email_notification_preference_choices": choices,
        }))

        plaintext = json.dumps(title)
        ciphertext, key_version = await encryption.encrypt_with_user_key(plaintext, user["vault_key_id"])
        title_ref = f"vault://workflows/workflow_title/{uuid.uuid4()}"
        _create(admin, "workflow_encrypted_blobs", {
            "ref": title_ref, "hashed_user_id": owner_hash, "kind": "workflow_title",
            "ciphertext": ciphertext,
            "checksum": "sha256:" + hashlib.sha256(plaintext.encode()).hexdigest(),
            "vault_key_ref": user["vault_key_id"], "key_version": key_version,
            "created_at": int(time.time()),
        }, cleanup)
        _create(admin, "workflows", {
            "id": workflow_id, "workflow_id": workflow_id, "hashed_user_id": owner_hash,
            "encrypted_title": ciphertext, "status": "disabled", "enabled": False,
            "lifecycle": "persisted", "source": "system", "version": 1,
            "current_version_id": version_id, "trigger_type": "schedule",
            "record_json": {"id": workflow_id, "owner_hash": owner_hash, "encrypted_title_ref": title_ref},
            "created_at": start, "updated_at": start,
        }, cleanup)

        def seed_run(at: int, trigger_type: str, status: str, *, owner: str = owner_hash) -> str:
            run_id = str(uuid.uuid4())
            _create(admin, "workflow_runs", {
                "run_id": run_id, "workflow_id": workflow_id, "version_id": version_id,
                "hashed_user_id": owner, "trigger_type": trigger_type,
                "acceptance_idempotency_key": "sha256:" + uuid.uuid4().hex,
                "accepted_at": at, "started_at": at + 1, "finished_at": at + 4,
                "status": status, "content_available": False,
                "error_summary": output_marker if status == "failed" else None,
            }, cleanup)
            return run_id

        first = seed_run(start, "schedule", "completed")
        second = seed_run(end - 1, "schedule", "failed")
        preview = seed_run(end, "schedule", "completed")
        manual = seed_run(start + 2, "manual", "completed")
        test = seed_run(start + 3, "test", "completed")
        outside = seed_run(start - 1, "schedule", "completed")
        foreign = seed_run(start + 4, "schedule", "completed", owner="user_sha256:" + uuid.uuid4().hex)
        del outside, foreign

        async def seal_delivery(message: str) -> str:
            plaintext = json.dumps({"title": "Selected message", "message": message, "embeds": []})
            ciphertext, key_version = await encryption.encrypt_with_user_key(plaintext, user["vault_key_id"])
            return json.dumps({"ciphertext": ciphertext, "vault_key_id": user["vault_key_id"], "key_version": key_version})

        private_payload = await seal_delivery(private_message_marker)
        preview_payload = await seal_delivery(preview_message_marker)
        delivery_records: list[tuple[str, str]] = []
        for state in ("delivery_pending", "claimed", "acknowledged"):
            delivery_id = str(uuid.uuid4())
            record = _create(admin, "workflow_chat_deliveries", {
                "delivery_id": delivery_id, "workflow_id": workflow_id, "run_id": first,
                "hashed_user_id": delivery_hash, "chat_id": str(uuid.uuid4()),
                "message_id": str(uuid.uuid4()), "node_id": "send", "status": state,
                "encrypted_payload": private_payload if state == "delivery_pending" else "vault:v1:synthetic-ci-fixture",
                "created_at": start, "expires_at": end + 7 * 86400,
            }, cleanup)
            delivery_records.append((record["id"], state))
        for state in ("cancelled", "expired", "failed", "delivery_pending", "claimed"):
            stale = state in ("delivery_pending", "claimed")
            persisted = state == "claimed"
            record = _create(admin, "workflow_chat_deliveries", {
                "delivery_id": str(uuid.uuid4()), "workflow_id": workflow_id, "run_id": first,
                "hashed_user_id": delivery_hash, "chat_id": str(uuid.uuid4()),
                "message_id": str(uuid.uuid4()), "node_id": "send", "status": state,
                "encrypted_payload": "", "created_at": start,
                "expires_at": int(time.time()) - 5 if stale else end + 7 * 86400,
                "client_persisted_at": int(time.time()) - 10 if persisted else None,
                "encrypted_chat_metadata": "client-ciphertext" if persisted else None,
                "encrypted_message": "client-ciphertext" if persisted else None,
            }, cleanup)
            delivery_records.append((record["id"], state))
        preview_delivery = _create(admin, "workflow_chat_deliveries", {
            "delivery_id": str(uuid.uuid4()), "workflow_id": workflow_id, "run_id": preview,
            "hashed_user_id": delivery_hash, "chat_id": str(uuid.uuid4()),
            "message_id": str(uuid.uuid4()), "node_id": "send", "status": "delivery_pending",
            "encrypted_payload": preview_payload,
            "created_at": end, "expires_at": end + 7 * 86400,
        }, cleanup)
        delivery_records.append((preview_delivery["id"], "delivery_pending"))

        mailpit = httpx.Client(base_url="http://mailpit:8025", timeout=10)
        # A failed browser attempt may still have sent its email. Remove only
        # this fresh fixture user's deterministic rows so a retry starts clean.
        for endpoint in (cutoff, cutoff + timedelta(days=1)):
            cleanup.append(("email_deliveries", build_delivery_id(build_delivery_key(
                email_type="daily_notification", campaign_key="workflowRuns",
                recipient_kind="directus_user", recipient_id=user_id,
                stage=endpoint.date().isoformat(),
            ))))
        try:
            since = time.time()
            # The preceding day contains the run immediately before this
            # window's lower boundary. Two days back is genuinely empty.
            empty = await send_user_workflow_digest(task, user_id, cutoff - timedelta(days=2))
            assert empty == "empty", empty
            expired = await send_user_workflow_digest(
                task, user_id, cutoff - timedelta(days=2), require_current_cutoff=True,
            )
            assert expired == "expired_digest", expired
            assert await _async_retry_workflow_digest(
                task, user_id, int((cutoff - timedelta(days=2)).timestamp()), 1,
            ) == "expired_retry"
            assert not _mailpit_messages(mailpit, email, since=since)

            sent = await send_user_workflow_digest(task, user_id, cutoff, require_current_cutoff=True)
            assert sent == "sent", sent
            duplicate = await send_user_workflow_digest(task, user_id, cutoff, require_current_cutoff=True)
            assert duplicate == "already_reserved", duplicate
            messages = _mailpit_messages(mailpit, email, since=since)
            assert len(messages) == 1, "Expected exactly one captured daily digest"
            body = html.unescape(messages[0].get("HTML") or "")
            text = messages[0].get("Text") or ""
            assert first in body and second in body
            assert manual not in body and test not in body and preview not in body
            assert title not in body and output_marker not in body and output_marker not in text
            assert private_message_marker not in body and preview_message_marker not in body
            assert "Awaiting device delivery" in body and "Delivered to a device" in body
            assert "Chat message delivery" in body and "Expired" in body
            digest_text = " ".join(re.sub(r"<[^>]+>", " ", body).split())
            assert re.search(r"Awaiting device delivery:\s*3", digest_text)
            assert re.search(r"Delivered to a device:\s*1", digest_text)
            assert re.search(r"Expired:\s*2", digest_text)
            assert f"http://localhost:5173/#workflow-id={workflow_id}&workflow-tab=runs&run-id={first}" in body
            assert "http://localhost:5173/#settings/notifications/chat" in body
            anonymous = httpx.get(f"http://api:8000/v1/workflows/{workflow_id}/runs/{first}", timeout=10)
            assert anonymous.status_code in (401, 403), anonymous.status_code

            preferences["includeContent"] = True
            choices["includeContent"] = {"source": "user", "value": True}
            _data(admin.patch(f"/users/{user_id}", json={
                "email_notification_preferences": preferences,
                "email_notification_preference_choices": choices,
            }))
            preview_sent = await send_user_workflow_digest(task, user_id, cutoff + timedelta(days=1))
            assert preview_sent == "sent", preview_sent
            preview_messages = _mailpit_messages(mailpit, email, since=since)
            assert len(preview_messages) == 2, "Expected one private and one opted-in digest"
            preview_body = html.unescape(preview_messages[-1].get("HTML") or "")
            assert title in preview_body and preview in preview_body
            assert first not in preview_body and second not in preview_body
            assert output_marker not in preview_body
            assert preview_message_marker in preview_body and private_message_marker not in preview_body
            for record_id, state in delivery_records:
                current = _data(admin.get(f"/items/workflow_chat_deliveries/{record_id}"))
                assert isinstance(current, dict) and current.get("status") == state
        finally:
            mailpit.close()
    finally:
        await directus.close()
        await encryption.close()
        await secrets.close()


async def main() -> None:
    email = _require_isolation()
    admin = _admin()
    cleanup: list[tuple[str, str]] = []
    user = _one(admin, "/users", {"filter[hashed_email][_eq]": hash_email(email)})
    original = {key: user.get(key) for key in (
        "email_notifications_enabled", "email_notification_preferences", "email_notification_preference_choices",
    )}
    try:
        await _send_fixture(admin, email, user, cleanup)
    finally:
        for collection, row_id in reversed(cleanup):
            response = admin.delete(f"/items/{collection}/{row_id}")
            if response.status_code not in (200, 204, 404):
                raise RuntimeError(f"Could not remove disposable {collection} fixture")
        _data(admin.patch(f"/users/{user['id']}", json=original))
        admin.close()
    print("real workflow digest Mailpit roundtrip passed")


if __name__ == "__main__":
    asyncio.run(main())
