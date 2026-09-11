#!/usr/bin/env python3
"""Durable, no-live-send contracts for security report delivery."""

# contract-test-file: infrastructure

from __future__ import annotations

import importlib.util
import sys
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
import threading
import asyncio
from types import SimpleNamespace


ROOT = Path(__file__).resolve().parents[2]
MODULE_PATH = ROOT / "scripts" / "security_report_delivery.py"


def load_module():
    spec = importlib.util.spec_from_file_location("security_report_delivery", MODULE_PATH)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


def payload() -> dict:
    return {"subject": "Security report", "text": "synthetic", "html": "<p>synthetic</p>"}


# contract-test: infrastructure
def test_missing_configuration_does_not_revoke_inflight_claim(tmp_path):
    delivery = load_module()
    ledger = delivery.DeliveryLedger(tmp_path / "delivery.sqlite3")
    now = delivery._now("2026-09-06T08:30:00Z")
    _, row = ledger.claim("inflight", delivery.payload_hash(payload()), now=now, provider_supports_idempotency=False)
    ledger.mark_unavailable("inflight", delivery.payload_hash(payload()), now=now)
    assert ledger.complete("inflight", row["claim_token"], delivery.SendResult.accepted(), now=now)
    assert ledger.claim("inflight", delivery.payload_hash(payload()), now=now, provider_supports_idempotency=False)[0] == "accepted"


# contract-test: infrastructure
def test_delivery_snapshots_payload_before_claim(tmp_path, monkeypatch):
    delivery = load_module()
    content = payload()
    original = dict(content)
    real_claim = delivery.DeliveryLedger.claim

    def claim(*args, **kwargs):
        content["subject"] = "mutated during claim"
        return real_claim(*args, **kwargs)

    monkeypatch.setattr(delivery.DeliveryLedger, "claim", claim)
    sent = []
    delivery.deliver_notification(ledger_path=tmp_path / "delivery.sqlite3", notification_id="immutable", payload=content,
                                  recipient="owner@example.invalid", sender=lambda request: sent.append(request) or delivery.SendResult.accepted())
    assert sent[0]["subject"] == original["subject"]


# contract-test: infrastructure
def test_container_sender_does_not_require_uninstalled_script():
    delivery = load_module()
    calls = []

    def run(command, **kwargs):
        calls.append(command)
        return SimpleNamespace(returncode=0, stdout='{"state":"accepted"}')

    delivery.container_email_sender(runner=run)({"recipient": "configured_destination", **payload()})
    assert "/app/scripts/security_report_delivery.py" not in calls[0]
    assert "-c" in calls[0]


# contract-test: infrastructure
def test_boolean_transport_failure_is_unknown_and_closes_secrets(tmp_path, monkeypatch):
    delivery = load_module()
    closed = []

    class Secrets:
        async def initialize(self):
            return True

        async def get_secret(self, **kwargs):
            return "synthetic"

        async def close(self):
            closed.append(True)

    class Provider:
        def __init__(self, key):
            pass

        async def send_email(self, **kwargs):
            return False  # The real provider also returns False after timeouts.

    monkeypatch.setenv("SERVER_OWNER_EMAIL", "owner@example.invalid")
    monkeypatch.setitem(sys.modules, "backend.core.api.app.utils.secrets_manager", SimpleNamespace(SecretsManager=Secrets))
    monkeypatch.setitem(sys.modules, "backend.core.api.app.services.email.brevo_provider", SimpleNamespace(BrevoProvider=Provider))
    monkeypatch.setitem(sys.modules, "backend.core.api.app.services.email_template", SimpleNamespace(
        EmailTemplateService=lambda _: SimpleNamespace(default_sender_name="Synthetic", default_sender_email="sender@example.invalid")))
    result = asyncio.run(delivery._container_send(payload()))
    assert result["state"] == "unknown"
    assert closed == [True]


# contract-test: infrastructure
def test_stable_identity_and_concurrent_claim_send_once(tmp_path):
    delivery = load_module()
    database = tmp_path / "delivery.sqlite3"
    sent: list[str] = []

    def sender(request):
        sent.append(request["notification_id"])
        return delivery.SendResult.accepted("provider-message-1")

    notification_id = delivery.stable_notification_id("critical", "development", "incident-1")
    with ThreadPoolExecutor(max_workers=2) as pool:
        outcomes = list(pool.map(lambda _: delivery.deliver_notification(
            ledger_path=database, notification_id=notification_id, payload=payload(), recipient="owner@example.invalid", sender=sender
        ), range(2)))

    assert len(sent) == 1
    assert {outcome.state for outcome in outcomes} <= {"accepted", "pending"}
    assert delivery.stable_notification_id("critical", "development", "incident-1") == notification_id
    assert delivery.payload_hash(payload()) == delivery.payload_hash(dict(payload()))


# contract-test: infrastructure
def test_unknown_without_provider_idempotency_never_retries_and_is_visible(tmp_path):
    delivery = load_module()
    calls = []

    def sender(request):
        calls.append(request)
        return delivery.SendResult.unknown("timeout")

    first = delivery.deliver_notification(ledger_path=tmp_path / "delivery.sqlite3", notification_id="digest-1", payload=payload(), recipient="owner@example.invalid", sender=sender)
    second = delivery.deliver_notification(ledger_path=tmp_path / "delivery.sqlite3", notification_id="digest-1", payload=payload(), recipient="owner@example.invalid", sender=sender)

    assert first.state == "unknown"
    assert second.state == "unknown"
    assert second.reconciliation_required is True
    assert len(calls) == 1


# contract-test: infrastructure
def test_failed_retries_are_bounded_and_supported_idempotency_reuses_request_key(tmp_path):
    delivery = load_module()
    database = tmp_path / "delivery.sqlite3"
    calls = []

    def rejected(_request):
        calls.append("rejected")
        return delivery.SendResult.failed("temporary rejection")

    assert delivery.deliver_notification(ledger_path=database, notification_id="digest-2", payload=payload(), recipient="owner@example.invalid", sender=rejected, now="2026-09-06T08:30:00Z").state == "failed"
    assert delivery.deliver_notification(ledger_path=database, notification_id="digest-2", payload=payload(), recipient="owner@example.invalid", sender=rejected, now="2026-09-06T08:30:01Z").state == "failed"
    assert delivery.deliver_notification(ledger_path=database, notification_id="digest-2", payload=payload(), recipient="owner@example.invalid", sender=rejected, now="2026-09-06T08:30:03Z").state == "failed"
    assert len(calls) == 2

    requests = []
    def unknown_then_accepted(request):
        requests.append(request)
        return delivery.SendResult.unknown("timeout") if len(requests) == 1 else delivery.SendResult.accepted("provider-message-2")

    first = delivery.deliver_notification(ledger_path=tmp_path / "idempotent.sqlite3", notification_id="digest-3", payload=payload(), recipient="owner@example.invalid", sender=unknown_then_accepted, provider_supports_idempotency=True)
    second = delivery.deliver_notification(ledger_path=tmp_path / "idempotent.sqlite3", notification_id="digest-3", payload=payload(), recipient="owner@example.invalid", sender=unknown_then_accepted, provider_supports_idempotency=True)
    assert first.state == "unknown"
    assert second.state == "accepted"
    assert requests[0]["request_key"] == requests[1]["request_key"]


# contract-test: infrastructure
def test_missing_recipient_is_durably_unavailable_without_sender(tmp_path):
    delivery = load_module()
    result = delivery.deliver_notification(ledger_path=tmp_path / "delivery.sqlite3", notification_id="digest-4", payload=payload(), recipient=None, sender=lambda _: (_ for _ in ()).throw(AssertionError("must not send")))
    assert result.state == "unavailable"
    assert "SERVER_OWNER_EMAIL" in result.reason
    assert (tmp_path / "delivery.sqlite3").exists()
    assert delivery.resolve_recipient({"SERVER_OWNER_EMAIL": "owner@example.invalid", "ADMIN_NOTIFY_EMAIL": "admin@example.invalid"}) == "owner@example.invalid"


# contract-test: infrastructure
def test_dry_run_and_queue_acceptance_do_not_send_or_claim_provider_acceptance(tmp_path):
    delivery = load_module()
    database = tmp_path / "delivery.sqlite3"
    dry_run = delivery.deliver_notification(
        ledger_path=database, notification_id="digest-dry", payload=payload(), recipient="owner@example.invalid",
        sender=lambda _: (_ for _ in ()).throw(AssertionError("dry run must not send")), dry_run=True,
    )
    assert dry_run.state == "pending"
    assert not database.exists()

    calls = []
    def queued(request):
        calls.append(request)
        return delivery.SendResult.queued("queue-receipt-1")

    first = delivery.deliver_notification(ledger_path=database, notification_id="digest-queued", payload=payload(), recipient="owner@example.invalid", sender=queued)
    second = delivery.deliver_notification(ledger_path=database, notification_id="digest-queued", payload=payload(), recipient="owner@example.invalid", sender=queued)
    assert first.state == second.state == "queued"
    assert len(calls) == 1


# contract-test: infrastructure
def test_failed_row_has_one_concurrent_retry_claim_and_sender_exceptions_are_unknown(tmp_path):
    delivery = load_module()
    database = tmp_path / "delivery.sqlite3"
    started = threading.Event()
    release = threading.Event()
    calls = []

    assert delivery.deliver_notification(
        ledger_path=database, notification_id="failed-concurrent", payload=payload(), recipient="owner@example.invalid",
        sender=lambda _: delivery.SendResult.failed(), now="2026-09-06T08:30:00Z",
    ).state == "failed"

    def retry_sender(_request):
        calls.append("retry")
        started.set()
        assert release.wait(timeout=2)
        return delivery.SendResult.accepted()

    with ThreadPoolExecutor(max_workers=2) as pool:
        first = pool.submit(delivery.deliver_notification, ledger_path=database, notification_id="failed-concurrent", payload=payload(), recipient="owner@example.invalid", sender=retry_sender, now="2026-09-06T08:30:01Z")
        assert started.wait(timeout=2)
        second = pool.submit(delivery.deliver_notification, ledger_path=database, notification_id="failed-concurrent", payload=payload(), recipient="owner@example.invalid", sender=retry_sender, now="2026-09-06T08:30:01Z")
        assert second.result(timeout=1).state == "pending"
        release.set()
        assert first.result().state == "accepted"
    assert calls == ["retry"]

    unknown = delivery.deliver_notification(
        ledger_path=tmp_path / "exception.sqlite3", notification_id="sender-exception", payload=payload(), recipient="owner@example.invalid",
        sender=lambda _: (_ for _ in ()).throw(RuntimeError("transport disconnected")),
    )
    assert unknown.state == "unknown"
    assert unknown.reconciliation_required is True


# contract-test: infrastructure
def test_expired_claim_becomes_unknown_without_late_completion_or_resend(tmp_path):
    delivery = load_module()
    database = tmp_path / "delivery.sqlite3"
    ledger = delivery.DeliveryLedger(database)
    notification_id = "crashed-after-send"
    body_hash = delivery.payload_hash(payload())
    claim, row = ledger.claim(notification_id, body_hash, now=delivery._now("2026-09-06T08:30:00Z"), provider_supports_idempotency=False)
    assert claim == "claimed"

    outcome = delivery.deliver_notification(
        ledger_path=database, notification_id=notification_id, payload=payload(), recipient="owner@example.invalid",
        sender=lambda _: (_ for _ in ()).throw(AssertionError("expired claim must not resend")), now="2026-09-06T08:36:00Z",
    )
    assert outcome.state == "unknown"
    assert outcome.reconciliation_required is True
    assert ledger.complete(notification_id, row["claim_token"], delivery.SendResult.accepted(), now=delivery._now("2026-09-06T08:36:00Z")) is False


# contract-test: infrastructure
def test_unavailable_delivery_recovers_with_configured_recipient_and_container_sender_is_injectable(tmp_path):
    delivery = load_module()
    database = tmp_path / "delivery.sqlite3"
    assert delivery.deliver_notification(ledger_path=database, notification_id="recoverable", payload=payload(), recipient=None, sender=lambda _: None).state == "unavailable"
    assert delivery.deliver_notification(
        ledger_path=database, notification_id="recoverable", payload=payload(), recipient="owner@example.invalid",
        sender=lambda _: delivery.SendResult.accepted("accepted-by-provider"),
    ).state == "accepted"

    calls = []
    def runner(command, input, capture_output, text, check, timeout):
        calls.append((command, input))
        return type("Result", (), {"returncode": 0, "stdout": '{"state":"accepted","provider_message_id":null}', "stderr": ""})()

    sender = delivery.container_email_sender(runner=runner)
    result = sender({"notification_id": "opaque", "request_key": "stable", "recipient": "configured_destination", **payload()})
    assert result.state == "accepted"
    assert calls[0][0][-1] == "--container-send"
    assert "configured_destination" in calls[0][1]

    unavailable_sender = delivery.container_email_sender(
        runner=lambda *_args, **_kwargs: type("Result", (), {"returncode": 0, "stdout": '{"state":"unavailable","provider_message_id":null}', "stderr": ""})(),
    )
    assert delivery.deliver_notification(
        ledger_path=tmp_path / "container-unavailable.sqlite3", notification_id="container-unavailable", payload=payload(),
        recipient="owner@example.invalid", sender=unavailable_sender,
    ).state == "unavailable"
