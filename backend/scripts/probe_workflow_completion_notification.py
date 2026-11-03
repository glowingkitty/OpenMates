"""Runner-isolated actual-message alerts; status-only Workflow runs remain silent."""
from __future__ import annotations
import asyncio
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
from backend.core.api.app.services.notification_event_service import NotificationEventService
from backend.core.api.app.services.push_notification_service import push_notification_service
from backend.core.api.app.services.workflow_chat_notification_service import COLLECTION, message_url, dispatch_chat_notification
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
    prefs.update(workflowRuns=True, aiResponses=True, includeContent=False)
    choices["aiResponses"] = {"source": "user", "value": True}
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
    def handle_starttag(self, tag, attrs):
        if tag == "a":
            self.hrefs.extend(value for key, value in attrs if key == "href" and isinstance(value, str))


def _message_links(message: dict, message_id: str) -> list[str]:
    parser = _Anchors()
    parser.feed(message.get("HTML") or "")
    return [href for href in parser.hrefs if parse_qs(urlsplit(href).fragment).get("message-id") == [message_id]]


def _current_message_emails(messages: list[dict], rows: list[dict]) -> dict[str, dict]:
    selected = {}
    for row in rows:
        matching = [message for message in messages if _message_links(message, row["message_id"])]
        assert len(matching) == 1, f"Expected one chat email for {row['message_id']}; found {len(matching)}"
        assert _message_links(matching[0], row["message_id"]) == [message_url(row)], "Actual-message email has the wrong target"
        selected[row["message_id"]] = matching[0]
    return selected


_DELIVERY_METADATA_KEYS = frozenset({
    "type", "status", "delivery_id", "chat_id", "message_id", "client_persisted",
    "delivered_result_count", "pending_result_count",
})


def _assert_pruned_run_metadata(
    run: WorkflowRunDetail, private_values: tuple[str, ...], expected_targets: list[dict],
) -> None:
    """Prove every exact output route survives pruning without retaining content."""
    assert run.content_available is False
    assert run.content_storage == WorkflowRunContentStorage.DELETED
    assert run.encrypted_content_ref is None and run.encrypted_content_checksum is None
    assert run.content_expires_at is None
    assert set(run.output_summary) <= {"deliveries"}
    deliveries = run.output_summary.get("deliveries") or {}
    assert isinstance(deliveries, dict)
    routing_keys = ("delivery_id", "chat_id", "message_id")
    assert expected_targets, "Pruning proof requires actual expected output targets"
    assert all(target.get("workflow_id") == run.workflow_id and target.get("run_id") == run.id for target in expected_targets)
    expected = {tuple(target.get(key) for key in routing_keys) for target in expected_targets}
    assert len(expected) == len(expected_targets), "Expected output targets must be distinct"
    assert len(deliveries) == len(expected), "Pruned run lost or added delivery targets"
    retained = {tuple(metadata.get(key) for key in routing_keys) for metadata in deliveries.values()}
    assert retained == expected, "Pruned run changed exact delivery/chat/message targets"
    send_nodes = [node for node in run.node_runs if node.node_type == "send_chat_message" and node.status == "completed"]
    assert len(send_nodes) == len(expected), "Pruned run lost or added completed Send nodes"
    assert {node.node_id for node in send_nodes} == set(deliveries), "Pruned Send nodes do not match delivery metadata"
    for metadata in deliveries.values():
        assert isinstance(metadata, dict) and set(metadata) <= _DELIVERY_METADATA_KEYS
        assert metadata.get("type") == "send_chat_message"
    for node in run.node_runs:
        assert node.input_summary == {}
        assert node.output_summary == deliveries.get(node.node_id, {})
    exposed = json.dumps(run.model_dump(mode="json"))
    assert not any(value and value in exposed for value in private_values)



def _real_run(admin, user, workflow_id, run_id):
    row = _one(admin, "/items/workflow_runs", {"filter[run_id][_eq]": run_id,
        "filter[workflow_id][_eq]": workflow_id, "filter[hashed_user_id][_eq]": _hash_owner_id(user["id"])})
    assert row["status"] == "completed" and row["trigger_type"] == "schedule"
    return row


async def _inspect(admin: httpx.Client, email: str) -> None:
    ids = [os.getenv(key, "") for key in ("WORKFLOW_ID", "RUN_ID", "NO_CHAT_WORKFLOW_ID", "NO_CHAT_RUN_ID")]
    if not all(re.fullmatch(r"[a-f0-9-]{36}", value) for value in ids):
        raise RuntimeError("Inspect requires four real Workflow/run UUIDs")
    workflow_id, run_id, no_chat_workflow_id, no_chat_run_id = ids
    user = _user(admin, email)
    _verified_contact(admin, user)
    _real_run(admin, user, workflow_id, run_id)
    _real_run(admin, user, no_chat_workflow_id, no_chat_run_id)
    rows = _data(admin.get(f"/items/{COLLECTION}", params={"filter[run_id][_eq]": run_id, "limit": 10}))
    assert len(rows) == 2, "Every actual Send node must admit its own message"
    assert len({row["message_id"] for row in rows}) == len({row["delivery_id"] for row in rows}) == 2
    assert all(row["owner_user_id"] == user["id"] for row in rows)
    skipped = _data(admin.get(f"/items/{COLLECTION}", params={"filter[run_id][_eq]": no_chat_run_id}))
    assert skipped == [], "Skipped Send creates no chat notification"
    for row in rows:
        pending = _one(admin, "/items/workflow_chat_deliveries", {"filter[delivery_id][_eq]": row["delivery_id"]})
        assert pending["chat_id"] == row["chat_id"] and not pending.get("client_persisted_at")
        assert pending["status"] in {"delivery_pending", "claimed"}
    secrets, encryption, cache = SecretsManager(), EncryptionService(), CacheService()
    directus = DirectusService(cache_service=cache, encryption_service=encryption)
    mailpit = httpx.Client(base_url="http://mailpit:8025", timeout=10)
    try:
        await secrets.initialize()
        assert await encryption.initialize()
        task = SimpleNamespace(directus_service=directus, encryption_service=encryption, cache_service=cache,
            secrets_manager=secrets, email_template_service=EmailTemplateService(secrets_manager=secrets))
        deadline = time.monotonic() + 65
        while True:
            for row in rows:
                await dispatch_chat_notification(task, row["delivery_id"])
            current = _data(admin.get(f"/items/{COLLECTION}", params={"filter[run_id][_eq]": run_id}))
            if all(row["event_state"] == "published" and row["email_state"] == "sent" for row in current):
                break
            assert time.monotonic() < deadline, "Actual chat notifications did not reach mail acceptance"
            await asyncio.sleep(2)
        emails = _current_message_emails(_mail_messages(mailpit, email), rows)
        assert not any(message.get("Subject") == "Your scheduled Workflow completed" for message in _mail_messages(mailpit, email))
        events = await NotificationEventService(cache).get_recent(user["id"], limit=100)
        relevant = [event for event in events if event.get("routing", {}).get("run_id") in {run_id, no_chat_run_id}]
        assert len(relevant) == 2 and all(event["type"] == "chat.assistant_message_received" for event in relevant)
        assert {event["routing"]["message_id"] for event in relevant} == {row["message_id"] for row in rows}
        service = WorkflowService(repository=DirectusWorkflowRepository())
        private_titles = [service.get_workflow(w, user["id"]).title for w in (workflow_id, no_chat_workflow_id)]
        for message in emails.values():
            body = html.unescape(message.get("HTML") or "")
            assert not any(value in body for value in [*private_titles, "Scheduled notification integration result", "Scheduled completion chat"])
        for row in rows:
            await dispatch_chat_notification(task, row["delivery_id"])
        _current_message_emails(_mail_messages(mailpit, email), rows)

        # Process-local provider interception: no synthetic target reaches APNs.
        original_user = {key: user.get(key) for key in ("push_notification_enabled", "push_notification_subscription", "push_notification_preferences")}
        original = (push_notification_service.initialize, push_notification_service.is_apns_ready, push_notification_service.send_push_notification)
        captured = []
        async def initialized(*args):
            return None
        def capture(**kwargs):
            captured.append(kwargs)
            return True
        try:
            _data(admin.patch(f"/users/{user['id']}", json={"push_notification_enabled": True,
                "push_notification_preferences": {"aiResponses": True, "workflowRuns": False},
                "push_notification_subscription": json.dumps({"type": "apns", "platform": "ios", "token": "isolated-probe-token"})}))
            push_notification_service.initialize = initialized
            push_notification_service.is_apns_ready = lambda: True
            push_notification_service.send_push_notification = capture
            for row in rows:
                _data(admin.patch(f"/items/{COLLECTION}/{row['id']}", json={"push_state": "pending", "push_target_states": {}}))
                assert (await dispatch_chat_notification(task, row["delivery_id"]))["push"] == "accepted"
                _data(admin.patch(f"/items/{COLLECTION}/{row['id']}", json={"push_state": "pending"}))
                assert (await dispatch_chat_notification(task, row["delivery_id"]))["push"] == "accepted"
            assert len(captured) == 2
            for envelope, row in zip(captured, rows):
                assert envelope["category"] == "OPENMATES_CHAT_MESSAGE" and envelope["message_id"] == row["message_id"]
                assert envelope["workflow_routing"]["delivery_id"] == row["delivery_id"]
                assert "workflow-completion" not in envelope["url"]
        finally:
            push_notification_service.initialize, push_notification_service.is_apns_ready, push_notification_service.send_push_notification = original
            _data(admin.patch(f"/users/{user['id']}", json=original_user))
        if os.getenv("PRUNE_RUN_CONTENT") == "1":
            before = service.get_run(workflow_id, run_id, user["id"])
            ref = before.encrypted_content_ref
            assert ref and before.content_available
            assert service.repository.prune_run_content(workflow_id, run_id, user["id"], ref)
            service.repository.delete_encrypted_blob(ref)
            _assert_pruned_run_metadata(service.get_run(workflow_id, run_id, user["id"]), tuple(private_titles + ["Scheduled notification integration result", "Scheduled completion chat"]), expected_targets=rows)
        print("WORKFLOW_CHAT_LINKS=" + json.dumps([{**{key: row[key] for key in ("chat_id", "message_id", "delivery_id")}, "url": message_url(row)} for row in rows], separators=(",", ":")))
    finally:
        mailpit.close()
        await directus.close()
        await encryption.close()
        await cache.close()
        await secrets.close()
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
