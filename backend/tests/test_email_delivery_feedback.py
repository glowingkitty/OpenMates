"""Functional delivery reducer, durable eligibility and GET-only polling proof."""
import base64
import hashlib
import json
import os
from datetime import datetime, timedelta, timezone
from types import SimpleNamespace
from unittest.mock import AsyncMock

import httpx
import pytest

from backend.core.api.app.services.email_delivery_feedback import (
    COLLECTION, DeliveryFeedbackUnavailable, apply_event, classify_event,
    email_recipient_allowed, event_in_scope, event_tags, fetch_brevo_events,
    reconcile_delivery_feedback, reconcile_events, transition,
    update_suppression_if_version,
)

NOW = datetime.now(timezone.utc).replace(microsecond=0)
EMAIL = "receiver@example.test"


def event(code="softBounces", reason="unknown", *, minutes=0, identity="message-1", environment="development"):
    return {"email": EMAIL, "event": code, "reason": reason,
            "date": (NOW + timedelta(minutes=minutes)).isoformat(), "messageId": identity,
            "tags": [f"environment:{environment}", "email-type:newsletter", "audience:user"]}


class MemoryDirectus:
    base_url = "http://isolated-directus.test"
    def __init__(self):
        self.rows = {}
        self.known = set()
        self.ignored = set()
        self.health_event = SimpleNamespace(get_last_status=AsyncMock(return_value=None), record_health_event=AsyncMock(return_value=True))

    async def get_items(self, collection, *, params, admin_required, no_cache, raise_on_error):
        assert admin_required and no_cache and raise_on_error
        if collection == COLLECTION:
            row = self.rows.get(params["filter[id][_eq]"])
            return [dict(row)] if row else []
        if collection == "ignored_emails":
            return [{"id": "ignored"}] if self.ignored.intersection(params["filter[hashed_email][_in]"].split(",")) else []
        return [{"id": "local"}] if (collection, params["filter[hashed_email][_eq]"]) in self.known else []

    async def create_item(self, collection, payload, *, admin_required):
        assert collection == COLLECTION and admin_required
        if payload["id"] in self.rows:
            return False, None
        self.rows[payload["id"]] = dict(payload)
        return True, dict(payload)

    async def ensure_auth_token(self, *, admin_required):
        assert admin_required
        return "test-token"

    async def _make_api_request(self, method, url, *, headers, json):
        assert method == "POST" and url.endswith("/email-delivery-feedback/")
        assert headers == {"Authorization": "Bearer test-token"}
        item_id, data, expected_version = json["id"], json["data"], json["expected_version"]
        if self.rows[item_id]["version"] != expected_version:
            return httpx.Response(409, json={"error": {"code": "version_conflict"}})
        self.rows[item_id] = dict(data)
        return httpx.Response(200, json={"data": data})


@pytest.mark.parametrize("kind,reason,expected", [
    ("softBounces", "535 Authentication failed: Your account has been disabled", "recipient_disabled"),
    ("hardBounces", "550 sender IP 77.32.148.6 rejected by SpamCop", "sender_rejection"),
    ("hardBounces", "550 5.1.1 user unknown", "recipient_invalid"),
    ("hardBounces", "552 5.2.2 mailbox full", "mailbox_full"),
    ("softBounces", "535 authentication failed", "sender_rejection"),
    ("blocked", "message content rejected", "sender_rejection"),
    ("softBounces", "mysterious error", "unknown_failure"),
    ("soft_bounce", "mailbox full", "mailbox_full"),
    ("hardBounces", "550 5.7.26 security rejection", "sender_rejection"),
    ("hardBounces", "550 5.7.1 user unknown", "recipient_invalid"),
])
# contract-test: supporting surface=rest_api assertions=notifications.delivery.email-enabled,notifications.delivery.idempotent,newsletter.campaign.eligible-idempotent-delivery
def test_reason_classification(kind, reason, expected):
    assert classify_event(event(kind, reason)) == expected


# contract-test: supporting surface=rest_api assertions=notifications.delivery.email-enabled,notifications.delivery.idempotent,newsletter.campaign.eligible-idempotent-delivery
def test_replay_and_out_of_order_leave_original_cooldown_unchanged():
    first = event(reason="mailbox full")
    row = transition(None, first, environment="development")
    assert row["status"] == "temporary"
    assert transition(row, first, environment="development") is None
    assert transition(row, event(reason="mailbox full", minutes=-1), environment="development") is None
    assert row["suppressed_until"] == (NOW + timedelta(hours=6)).isoformat()


# contract-test: supporting surface=rest_api assertions=notifications.delivery.email-enabled,notifications.delivery.idempotent,newsletter.campaign.eligible-idempotent-delivery
def test_unknown_failure_needs_three_distinct_events_and_never_blocks_forever():
    row = None
    for i in range(3):
        row = transition(row, event(minutes=i, identity=f"message-{i}"), environment="development")
        assert row["status"] == ("clear" if i < 2 else "temporary")
    assert row["suppressed_until"] is not None
    delivered = transition(row, event("delivered", minutes=4), environment="development")
    assert delivered["status"] == "clear" and delivered["recent_failures"] == []
    assert transition(delivered, event(minutes=2, identity="message-2"), environment="development") is None


# contract-test: supporting surface=rest_api assertions=notifications.delivery.email-enabled,notifications.delivery.idempotent,newsletter.campaign.eligible-idempotent-delivery
def test_retries_for_one_message_do_not_count_as_distinct_failures():
    row = transition(None, event(), environment="development")
    assert transition(row, event(minutes=1), environment="development") is None
    assert row["status"] == "clear" and len(row["recent_failures"]) == 1


# contract-test: supporting surface=rest_api assertions=notifications.delivery.email-enabled
def test_unknown_failure_after_expired_cooldown_keeps_recipient_eligible():
    row = transition(None, event(reason="temporary failure", minutes=-121), environment="development")
    updated = transition(row, event(identity="message-2"), environment="development")
    assert updated["status"] == "clear" and updated["suppressed_until"] is None


# contract-test: supporting surface=rest_api assertions=notifications.delivery.email-enabled,notifications.delivery.idempotent,newsletter.campaign.eligible-idempotent-delivery
def test_delivered_does_not_clear_permanent_recipient_failure():
    row = transition(None, event(reason="user unknown"), environment="development")
    assert transition(row, event("delivered", minutes=1), environment="development")["status"] == "permanent"
    assert transition(row, event("delivered"), environment="development") is None


@pytest.mark.asyncio
# contract-test: supporting surface=rest_api assertions=notifications.delivery.email-enabled,notifications.delivery.idempotent,newsletter.campaign.eligible-idempotent-delivery
async def test_environment_tags_and_legacy_scope_require_local_hashed_identity():
    directus = MemoryDirectus()
    assert not await event_in_scope(event(environment="production"), environment="development", directus=directus)
    legacy = event()
    legacy.pop("tags")
    assert not await event_in_scope(legacy, environment="development", directus=directus)
    directus.known.add(("newsletter_subscribers", base64.b64encode(hashlib.sha256(EMAIL.encode()).digest()).decode()))
    assert await event_in_scope(legacy, environment="development", directus=directus)
    assert event_tags({"tag": "environment:dev|email-type:newsletter|audience:user"})["environment"] == "development"
    assert not await event_in_scope(event(environment="unrecognized"), environment="other", directus=directus)


@pytest.mark.asyncio
# contract-test: supporting surface=rest_api assertions=notifications.delivery.email-enabled
# contract-test: supporting surface=rest_api assertions=notifications.delivery.email-enabled,notifications.delivery.idempotent,newsletter.campaign.eligible-idempotent-delivery
async def test_eligibility_has_no_cache_dependency_and_database_failure_is_closed(monkeypatch):
    monkeypatch.setenv("SERVER_ENVIRONMENT", "development")
    directus = MemoryDirectus()
    assert await email_recipient_allowed(" RECEIVER@example.test ", secrets_manager=None, directus=directus)
    await apply_event(directus, event(reason="user unknown"), environment="development")
    assert not await email_recipient_allowed(EMAIL, secrets_manager=None, directus=directus)
    directus.get_items = AsyncMock(return_value=None)
    with pytest.raises(DeliveryFeedbackUnavailable):
        await email_recipient_allowed(EMAIL, secrets_manager=None, directus=directus)


@pytest.mark.asyncio
@pytest.mark.parametrize("status", [403, 503])
# contract-test: supporting surface=rest_api assertions=notifications.delivery.email-enabled,notifications.delivery.idempotent,newsletter.campaign.eligible-idempotent-delivery
async def test_actual_directus_http_errors_cannot_be_interpreted_as_empty_history(status):
    from backend.core.api.app.services.directus import DirectusService
    directus = SimpleNamespace(base_url="http://isolated-directus.test", ensure_auth_token=AsyncMock(return_value="test-token"),
                               _make_api_request=AsyncMock(return_value=httpx.Response(status, json={"errors": [{"message": "unavailable"}]})))
    async def get_items(*args, **kwargs):
        return await DirectusService.get_items(directus, *args, **kwargs)
    directus.get_items = get_items
    with pytest.raises(DeliveryFeedbackUnavailable):
        await email_recipient_allowed(EMAIL, secrets_manager=None, directus=directus)


@pytest.mark.asyncio
@pytest.mark.parametrize("code", ["unsubscribed", "spam"])
# contract-test: supporting surface=rest_api assertions=notifications.delivery.email-enabled
# contract-test: supporting surface=rest_api assertions=notifications.delivery.email-enabled,notifications.delivery.idempotent,newsletter.campaign.eligible-idempotent-delivery
async def test_provider_newsletter_opt_out_does_not_block_account_security_mail(code):
    directus = MemoryDirectus()
    assert not await apply_event(directus, event(code), environment="development")
    assert await email_recipient_allowed(EMAIL, secrets_manager=None, directus=directus)
    assert not directus.rows


@pytest.mark.asyncio
# contract-test: supporting surface=rest_api assertions=notifications.delivery.email-enabled,notifications.delivery.idempotent,newsletter.campaign.eligible-idempotent-delivery
async def test_global_ignore_and_expired_cooldown(monkeypatch):
    monkeypatch.setenv("SERVER_ENVIRONMENT", "development")
    directus = MemoryDirectus()
    directus.ignored.add(base64.b64encode(hashlib.sha256(EMAIL.encode()).digest()).decode())
    assert not await email_recipient_allowed(EMAIL, secrets_manager=None, directus=directus)
    directus.ignored.clear()
    await apply_event(directus, event(reason="temporary failure", minutes=-121), environment="development")
    assert await email_recipient_allowed(EMAIL, secrets_manager=None, directus=directus)


@pytest.mark.asyncio
# contract-test: supporting surface=rest_api assertions=notifications.delivery.email-enabled,notifications.delivery.idempotent,newsletter.campaign.eligible-idempotent-delivery
async def test_concurrent_newer_delivered_event_wins_compare_and_swap():
    directus = MemoryDirectus()
    await apply_event(directus, event(reason="mailbox full", minutes=-2), environment="development")
    original_update = directus._make_api_request
    raced = False

    async def concurrent_update(method, url, *, headers, json):
        nonlocal raced
        item_id = json["id"]
        if not raced:
            raced = True
            directus.rows[item_id] = transition(directus.rows[item_id], event("delivered"), environment="development")
        return await original_update(method, url, headers=headers, json=json)

    directus._make_api_request = concurrent_update
    assert not await apply_event(directus, event(reason="mailbox full", minutes=-1, identity="message-2"), environment="development")
    assert next(iter(directus.rows.values()))["status"] == "clear"


@pytest.mark.asyncio
# contract-test: supporting surface=rest_api assertions=notifications.delivery.idempotent,newsletter.campaign.eligible-idempotent-delivery
# contract-test: supporting surface=rest_api assertions=notifications.delivery.email-enabled,notifications.delivery.idempotent,newsletter.campaign.eligible-idempotent-delivery
async def test_poll_to_durable_state_and_sender_alert_is_separate_and_idempotent():
    directus = MemoryDirectus()
    events = [event("hardBounces", "550 shared sender IP SpamCop", minutes=-2),
              event(reason="mailbox full", minutes=-1, identity="message-2"),
              event(reason="user unknown", environment="production")]
    requests = []

    def provider(request):
        requests.append(request)
        assert request.method == "GET" and request.url.path == "/v3/smtp/statistics/events"
        assert request.headers["api-key"] == "test-key"
        return httpx.Response(200, json={"events": events})

    async with httpx.AsyncClient(transport=httpx.MockTransport(provider)) as client:
        result = await reconcile_delivery_feedback(directus=directus, api_key="test-key", environment="development", client=client)
        assert result["changed"] == 1 and len(directus.rows) == 1
        row = next(iter(directus.rows.values()))
        assert row["status"] == "temporary"
        assert EMAIL not in json.dumps(row) and "SpamCop" not in json.dumps(row) and "message-2" not in json.dumps(row)
        directus.health_event.record_health_event.assert_awaited_once()
        assert directus.health_event.record_health_event.await_args.args[:2] == ("external", "email-delivery-development")
        directus.health_event.get_last_status.return_value = {"new_status": "degraded"}
        again = await reconcile_delivery_feedback(directus=directus, api_key="test-key", environment="development", client=client)
        assert again["changed"] == 0
        assert directus.health_event.record_health_event.await_count == 1
    assert len(requests) == 2


@pytest.mark.asyncio
# contract-test: supporting surface=rest_api assertions=notifications.delivery.email-enabled,notifications.delivery.idempotent,newsletter.campaign.eligible-idempotent-delivery
async def test_read_only_pagination_is_bounded_and_http_failure_never_reports_healthy():
    def provider(request):
        assert request.method == "GET"
        return httpx.Response(503, json={"events": []})
    async with httpx.AsyncClient(transport=httpx.MockTransport(provider)) as client:
        with pytest.raises(DeliveryFeedbackUnavailable):
            await fetch_brevo_events("test-key", client=client)
    offsets = []
    def full_page(request):
        offsets.append(int(request.url.params["offset"]))
        return httpx.Response(200, json={"events": [event(minutes=-1)] * 5000})
    async with httpx.AsyncClient(transport=httpx.MockTransport(full_page)) as client:
        with pytest.raises(DeliveryFeedbackUnavailable):
            await fetch_brevo_events("test-key", client=client)
    assert offsets == [0, 5000, 10000, 15000]


@pytest.mark.integration
@pytest.mark.asyncio
# contract-test: supporting surface=rest_api assertions=notifications.delivery.email-enabled,notifications.delivery.idempotent
# contract-test: supporting surface=rest_api assertions=notifications.delivery.email-enabled,notifications.delivery.idempotent,newsletter.campaign.eligible-idempotent-delivery
async def test_isolated_directus_suppression_roundtrip(monkeypatch):
    """Real schema and CAS proof with synthetic mail; no provider call or send."""
    from uuid import uuid4
    from urllib.parse import urlparse
    if os.getenv("OPENMATES_ISOLATED_EMAIL_FEEDBACK_PROBE") != "1":
        pytest.skip("requires isolated CI Directus target")
    target = urlparse(os.getenv("CMS_URL", ""))
    if not target.hostname or target.hostname.endswith("openmates.org"):
        pytest.fail("suppression probe requires isolated CMS, never a shared application target")
    from backend.core.api.app.services.directus import DirectusService
    monkeypatch.setenv("SERVER_ENVIRONMENT", "ci")
    directus = DirectusService()
    address = f"feedback-{uuid4().hex}@example.test"
    row_id = None
    try:
        synthetic = event(reason="mailbox full", environment="ci", minutes=-2)
        synthetic["email"] = address
        reduced = transition(None, synthetic, environment="ci")
        row_id = reduced["id"]
        denied = await directus._client.post(f"{directus.base_url}/email-delivery-feedback/", json={
            "id": row_id, "expected_version": 1, "data": reduced,
        })
        assert denied.status_code == 403
        result = await reconcile_events(directus=directus, events=[synthetic], environment="ci")
        assert result["changed"] == 1
        assert not await email_recipient_allowed(address, secrets_manager=None, directus=directus)
        assert (await reconcile_events(directus=directus, events=[synthetic], environment="ci"))["changed"] == 0
        delivered = dict(synthetic, event="delivered", date=(NOW - timedelta(minutes=1)).isoformat())
        assert (await reconcile_events(directus=directus, events=[delivered], environment="ci"))["changed"] == 1
        assert await email_recipient_allowed(address, secrets_manager=None, directus=directus)
        assert (await reconcile_events(directus=directus, events=[synthetic], environment="ci"))["changed"] == 0
        # Prove actual SQL CAS, not the generic Directus query-filter helper.
        stale = transition(reduced, dict(synthetic, date=NOW.isoformat(), messageId="stale-write"), environment="ci")
        assert await update_suppression_if_version(directus, stale, reduced["version"]) is None
        rows = await directus.get_items(COLLECTION, params={"filter[id][_eq]": row_id}, admin_required=True, no_cache=True, raise_on_error=True)
        assert rows[0]["status"] == "clear" and rows[0]["version"] == 2
        import asyncio
        current = rows[0]
        candidates = [transition(current, dict(synthetic, date=NOW.isoformat(), messageId=f"race-{i}"), environment="ci") for i in range(2)]
        writes = await asyncio.gather(*(update_suppression_if_version(directus, candidate, current["version"]) for candidate in candidates))
        assert sum(saved is not None for saved in writes) == 1
        rows = await directus.get_items(COLLECTION, params={"filter[id][_eq]": row_id}, admin_required=True, no_cache=True, raise_on_error=True)
        assert rows[0]["version"] == 3
        # Sender reputation rejection cannot create a permanent recipient block.
        sender = dict(delivered, event="hardBounces", reason="550 sender IP SpamCop", date=NOW.isoformat())
        assert transition(reduced, sender, environment="ci") is None
    finally:
        if row_id is not None:
            await directus.delete_item(COLLECTION, row_id, admin_required=True)
        await directus.close()


@pytest.mark.integration
@pytest.mark.live
@pytest.mark.asyncio
# contract-test: supporting surface=rest_api assertions=notifications.delivery.email-enabled,notifications.delivery.idempotent,newsletter.campaign.eligible-idempotent-delivery
async def test_opt_in_brevo_read_only_event_contract():
    # No sends or provider writes. Isolated CI always skips absent explicit key.
    if os.getenv("CI", "").lower() in {"1", "true"} or os.getenv("OPENMATES_BREVO_FEEDBACK_PROBE") != "1":
        pytest.skip("read-only live Brevo probe requires explicit opt-in")
    key = os.getenv("OPENMATES_BREVO_FEEDBACK_PROBE_KEY")
    if not key:
        pytest.skip("live Brevo probe has no injected secret")
    events = await fetch_brevo_events(key)
    assert isinstance(events, list)
    assert all(isinstance(item.get("date"), str) and isinstance(item.get("event"), str) for item in events)
