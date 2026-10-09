"""Isolated-CI probe for real scheduled completion push/email dispatch.

The browser spec creates two real owner-authenticated schedules and passes their
durable run IDs here. This script never fabricates completed Workflow rows.
"""

from __future__ import annotations

import asyncio
import hashlib
import html
import json
import os
import re
import time
from types import SimpleNamespace
from html.parser import HTMLParser
from urllib.parse import parse_qs, urlsplit

import httpx

from backend.core.api.app.services.cache import CacheService
from backend.core.api.app.services.directus import DirectusService
from backend.core.api.app.services.email_template import EmailTemplateService
from backend.core.api.app.services.push_notification_service import push_notification_service
from backend.core.api.app.services.workflow_completion_notification_service import (
    COLLECTION, completion_url, dispatch_completion, owner_run_completion_projection,
)
from backend.core.api.app.services.workflow_models import WorkflowRunContentStorage, WorkflowRunDetail
from backend.core.api.app.services.workflow_service import DirectusWorkflowRepository, WorkflowService, _hash_owner_id
from backend.core.api.app.utils.encryption import EncryptionService
from backend.core.api.app.utils.newsletter_utils import hash_email
from backend.core.api.app.utils.secrets_manager import SecretsManager


def _require_isolation() -> str:
    required = {"CI": "true", "OPENMATES_CI_ISOLATED": "1", "OPENMATES_CI_MAIL_CAPTURE": "1",
                "CMS_URL": "http://cms:8055", "SERVER_ENVIRONMENT": "development"}
    if any(os.getenv(key) != value for key, value in required.items()):
        raise RuntimeError("Workflow completion probe requires isolated CI mail stack")
    email = os.getenv("PROBE_EMAIL", "").lower()
    if not re.fullmatch(r"ci-[a-z0-9+._-]+@example\.com", email):
        raise RuntimeError("Workflow completion probe requires a fresh CI example.com account")
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
        raise AssertionError(f"Expected exactly one isolated record at {path}")
    return rows[0]


def _user(admin: httpx.Client, email: str) -> dict:
    return _one(admin, "/users", {"filter[hashed_email][_eq]": hash_email(email)})


def _json(value: object) -> dict:
    if isinstance(value, str):
        value = json.loads(value)
    return dict(value) if isinstance(value, dict) else {}


def _verified_contact(admin: httpx.Client, user: dict) -> None:
    contact = _one(admin, "/items/account_contact_emails", {
        "filter[user_id][_eq]": user["id"],
        "filter[hashed_email][_eq]": user["hashed_email"],
    })
    assert contact.get("verified_at") and contact.get("purpose") == "account_lifecycle"


def _prepare(admin: httpx.Client, email: str) -> None:
    user = _user(admin, email)
    _verified_contact(admin, user)
    prefs = _json(user.get("email_notification_preferences"))
    choices = _json(user.get("email_notification_preference_choices"))
    prefs.update(workflowRuns=True, includeContent=False)
    choices["workflowRuns"] = {"source": "user", "value": True}
    choices["includeContent"] = {"source": "user", "value": False}
    _data(admin.patch(f"/users/{user['id']}", json={
        "email_notifications_enabled": True,
        "email_notification_preferences": prefs,
        "email_notification_preference_choices": choices,
    }))
    print("WORKFLOW_COMPLETION_NOTIFICATION_PROBE_PREPARED")


def _mail_messages(mailpit: httpx.Client, email: str) -> list[dict]:
    response = mailpit.get("/api/v1/messages?limit=100")
    response.raise_for_status()
    matches = []
    for item in response.json().get("messages", []):
        if item.get("Subject") != "Your scheduled Workflow completed":
            continue
        if not any(address.get("Address", "").lower() == email for address in item.get("To", [])):
            continue
        full = mailpit.get(f"/api/v1/message/{item['ID']}")
        full.raise_for_status()
        matches.append(full.json())
    return matches


class _Anchors(HTMLParser):
    def __init__(self) -> None:
        super().__init__()
        self.hrefs: list[str] = []

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        if tag == "a":
            self.hrefs.extend(value for key, value in attrs if key == "href" and isinstance(value, str))


def _run_links(message: dict, run_id: str) -> list[str]:
    parser = _Anchors()
    parser.feed(message.get("HTML") or "")
    return [href for href in parser.hrefs
            if parse_qs(urlsplit(href).fragment).get("run-id") == [run_id]]


def _actual_link(message: dict, run_id: str) -> str:
    matches = _run_links(message, run_id)
    assert len(matches) == 1, f"Expected one actual SMTP link for run {run_id}"
    return matches[0]


def _current_run_messages(messages: list[dict], rows: tuple[dict, dict]) -> dict[str, dict]:
    """Ignore prior attempts while rejecting duplicates for either current run."""
    selected = {}
    for row in rows:
        matching = [message for message in messages if _run_links(message, row["run_id"])]
        assert len(matching) == 1, f"Expected one completion email for current run {row['run_id']}; found {len(matching)}"
        assert _run_links(matching[0], row["run_id"]) == [completion_url(row)], (
            f"Completion email for current run {row['run_id']} has the wrong target"
        )
        selected[row["run_id"]] = matching[0]
    assert len(selected) == len(rows)
    return selected


_DELIVERY_METADATA_KEYS = frozenset({
    "type", "status", "delivery_id", "chat_id", "message_id", "client_persisted",
    "delivered_result_count", "pending_result_count",
})


def _assert_pruned_run_metadata(run: WorkflowRunDetail, private_values: tuple[str, ...]) -> None:
    """Allow only delivery routing/status after encrypted run content is removed."""
    assert run.content_available is False
    assert run.content_storage == WorkflowRunContentStorage.DELETED
    assert run.encrypted_content_ref is None and run.encrypted_content_checksum is None
    assert run.content_expires_at is None
    assert set(run.output_summary) <= {"deliveries"}
    deliveries = run.output_summary.get("deliveries") or {}
    assert isinstance(deliveries, dict)
    for metadata in deliveries.values():
        assert isinstance(metadata, dict) and set(metadata) <= _DELIVERY_METADATA_KEYS
        assert metadata.get("type") == "send_chat_message"
    for node in run.node_runs:
        assert node.input_summary == {}
        assert node.output_summary == deliveries.get(node.node_id, {})
    exposed = json.dumps(run.model_dump(mode="json"))
    assert not any(value and value in exposed for value in private_values)


def _run_and_outbox(admin: httpx.Client, user: dict, workflow_id: str, run_id: str) -> dict:
    run = _one(admin, "/items/workflow_runs", {
        "filter[run_id][_eq]": run_id,
        "filter[workflow_id][_eq]": workflow_id,
        "filter[hashed_user_id][_eq]": _hash_owner_id(user["id"]),
    })
    assert run["status"] == "completed" and run["trigger_type"] == "schedule" and isinstance(run.get("finished_at"), int)
    row = _one(admin, f"/items/{COLLECTION}", {"filter[run_id][_eq]": run_id})
    assert row["owner_user_id"] == user["id"] and row["workflow_id"] == workflow_id
    assert row["notification_id"] == f"workflow-completed-{run_id}"
    return row


async def _inspect(admin: httpx.Client, email: str) -> None:
    ids = [os.getenv(key, "") for key in (
        "WORKFLOW_ID", "RUN_ID", "NO_CHAT_WORKFLOW_ID", "NO_CHAT_RUN_ID",
    )]
    if not all(re.fullmatch(r"[a-f0-9-]{36}", value) for value in ids):
        raise RuntimeError("Inspect mode requires four real Workflow/run UUIDs")
    workflow_id, run_id, no_chat_workflow_id, no_chat_run_id = ids
    user = _user(admin, email)
    _verified_contact(admin, user)
    deadline = time.monotonic() + 65
    while True:
        chat_row = _run_and_outbox(admin, user, workflow_id, run_id)
        no_chat_row = _run_and_outbox(admin, user, no_chat_workflow_id, no_chat_run_id)
        if all(row.get("event_state") == "published" and row.get("email_state") == "sent"
               for row in (chat_row, no_chat_row)):
            break
        if time.monotonic() >= deadline:
            raise AssertionError("Scheduled completion dispatch did not reach event/email acceptance within 65s")
        await asyncio.sleep(2)
    assert all(chat_row.get(key) for key in ("chat_id", "message_id", "delivery_id")), chat_row
    assert not any(no_chat_row.get(key) for key in ("chat_id", "message_id", "delivery_id")), no_chat_row
    delivery = _one(admin, "/items/workflow_chat_deliveries", {
        "filter[delivery_id][_eq]": chat_row["delivery_id"],
        "filter[run_id][_eq]": run_id,
        "filter[hashed_user_id][_eq]": hashlib.sha256(user["id"].encode()).hexdigest(),
    })
    assert delivery["chat_id"] == chat_row["chat_id"] and delivery["message_id"] == chat_row["message_id"]
    assert "chat-id=" in completion_url(chat_row) and "chat-id=" not in completion_url(no_chat_row)

    mailpit = httpx.Client(base_url="http://mailpit:8025", timeout=10)
    links: dict[str, str] = {}
    try:
        messages = _current_run_messages(_mail_messages(mailpit, email), (chat_row, no_chat_row))
        for row in (chat_row, no_chat_row):
            message = messages[row["run_id"]]
            body = html.unescape(message.get("HTML") or "")
            assert row["run_id"] in body and "completed at" in body
            links["chat" if row is chat_row else "run"] = _actual_link(message, row["run_id"])
        secrets = SecretsManager()
        encryption = EncryptionService()
        cache = CacheService()
        directus = DirectusService(cache_service=cache, encryption_service=encryption)
        try:
            await secrets.initialize()
            assert await encryption.initialize()
            task = SimpleNamespace(
                directus_service=directus, encryption_service=encryption, cache_service=cache,
                secrets_manager=secrets, email_template_service=EmailTemplateService(secrets_manager=secrets),
            )
            service = WorkflowService(repository=DirectusWorkflowRepository())
            private_titles = [service.get_workflow(workflow, user["id"]).title
                              for workflow in (workflow_id, no_chat_workflow_id)]
            for message in messages.values():
                assert not any(title in (message.get("HTML") or "") for title in private_titles)
            # Requeue the ledger projection without touching the completed run.
            # Stable event and email idempotency must suppress duplicate sends.
            for row in (chat_row, no_chat_row):
                result = await dispatch_completion(task, row["run_id"], service)
                assert result["status"] == "completed"
            _current_run_messages(_mail_messages(mailpit, email), (chat_row, no_chat_row))

            # Intercept only this probe process's APNs provider boundary. A
            # synthetic token never reaches Apple, and no token enters Celery.
            original_push = {
                "push_notification_enabled": user.get("push_notification_enabled"),
                "push_notification_subscription": user.get("push_notification_subscription"),
                "push_notification_preferences": user.get("push_notification_preferences"),
            }
            original_initialize = push_notification_service.initialize
            original_ready = push_notification_service.is_apns_ready
            original_send = push_notification_service.send_push_notification
            captured: list[dict] = []

            async def initialized(*_args: object) -> None:
                return None

            def capture(**kwargs: object) -> bool:
                captured.append(dict(kwargs))
                return True

            try:
                _data(admin.patch(f"/users/{user['id']}", json={
                    "push_notification_enabled": True,
                    "push_notification_preferences": {"workflowRuns": True},
                    "push_notification_subscription": json.dumps({
                        "type": "apns", "platform": "ios", "token": "isolated-probe-token",
                    }),
                }))
                _data(admin.patch(f"/items/{COLLECTION}/{chat_row['id']}", json={
                    "push_state": "pending", "push_target_states": {},
                }))
                push_notification_service.initialize = initialized
                push_notification_service.is_apns_ready = lambda: True
                push_notification_service.send_push_notification = capture
                first = await dispatch_completion(task, run_id, service)
                assert first["push"] == "accepted" and len(captured) == 1
                envelope = captured[0]
                assert envelope["title"] == "OpenMates"
                assert envelope["body"] == "Your scheduled Workflow completed"
                assert envelope["category"] == "OPENMATES_WORKFLOW_COMPLETED"
                assert envelope["workflow_routing"]["notification_id"] == chat_row["notification_id"]
                assert envelope["workflow_routing"]["delivery_id"] == chat_row["delivery_id"]
                assert isinstance(envelope.get("encrypted_title"), str) and envelope["encrypted_title"]
                _data(admin.patch(f"/items/{COLLECTION}/{chat_row['id']}", json={"push_state": "pending"}))
                replay = await dispatch_completion(task, run_id, service)
                assert replay["push"] == "accepted" and len(captured) == 1
                _current_run_messages(_mail_messages(mailpit, email), (chat_row, no_chat_row))
            finally:
                push_notification_service.initialize = original_initialize
                push_notification_service.is_apns_ready = original_ready
                push_notification_service.send_push_notification = original_send
                _data(admin.patch(f"/users/{user['id']}", json=original_push))
            if os.getenv("PRUNE_RUN_CONTENT") == "1":
                before = service.get_run(workflow_id, run_id, user["id"])
                ref = before.encrypted_content_ref
                assert ref and before.content_available, "Real scheduled run content must exist before pruning"
                assert service.repository.prune_run_content(workflow_id, run_id, user["id"], ref)
                service.repository.delete_encrypted_blob(ref)
                assert service.repository.get_encrypted_blob(ref) is None
                pruned = service.get_run(workflow_id, run_id, user["id"])
                _assert_pruned_run_metadata(pruned, (
                    *private_titles, "Scheduled notification integration result", "Scheduled completion chat",
                ))
                projection = await owner_run_completion_projection(directus, pruned, user["id"])
                assert projection and projection["chat_id"] == chat_row["chat_id"]
                assert projection["message_id"] == chat_row["message_id"]
                assert projection["delivery_id"] == chat_row["delivery_id"]
        finally:
            await directus.close()
            await encryption.close()
            await cache.close()
            await secrets.close()
    finally:
        mailpit.close()
    print("WORKFLOW_COMPLETION_LINKS=" + json.dumps(links, separators=(",", ":")))
    print("WORKFLOW_COMPLETION_NOTIFICATION_PROBE_OK")


async def main() -> None:
    email = _require_isolation()
    admin = _admin()
    try:
        if os.getenv("PROBE_MODE") == "prepare":
            _prepare(admin, email)
        elif os.getenv("PROBE_MODE", "inspect") == "inspect":
            await _inspect(admin, email)
        else:
            raise RuntimeError("PROBE_MODE must be prepare or inspect")
    finally:
        admin.close()


if __name__ == "__main__":
    asyncio.run(main())
