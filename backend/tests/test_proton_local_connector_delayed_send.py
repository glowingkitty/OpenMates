# backend/tests/test_proton_local_connector_delayed_send.py
#
# Contract tests for Proton local connector delayed-send semantics.
# The backend owns approval and undo-window metadata, while SMTP credentials and
# delivery stay inside the active CLI connector process.
#
# Spec: docs/specs/proton-bridge-cli-connector/spec.yml

from __future__ import annotations

import pytest


def test_proton_send_requires_write_capability_and_user_approval() -> None:
    from backend.core.api.app.services.connected_accounts_service import build_proton_local_delayed_send_job

    with pytest.raises(PermissionError, match="write capability"):
        build_proton_local_delayed_send_job(
            row=local_connector_row(capabilities=["read"]),
            payload=send_payload(),
            approved=True,
            now=1_000,
        )

    with pytest.raises(PermissionError, match="approval"):
        build_proton_local_delayed_send_job(
            row=local_connector_row(capabilities=["read", "write"]),
            payload=send_payload(),
            approved=False,
            now=1_000,
        )


def test_approved_send_creates_fixed_thirty_second_pending_job() -> None:
    from backend.core.api.app.services.connected_accounts_service import build_proton_local_delayed_send_job

    job = build_proton_local_delayed_send_job(
        row=local_connector_row(capabilities=["read", "write"]),
        payload=send_payload(),
        approved=True,
        now=1_000,
    )

    assert job["status"] == "pending_send"
    assert job["delay_seconds"] == 30
    assert job["deliver_after"] == 1_030
    assert job["undo_available"] is True
    assert_no_secret_text(job)


def test_undo_before_deadline_cancels_send_job() -> None:
    from backend.core.api.app.services.connected_accounts_service import cancel_proton_local_delayed_send_job

    job = {
        "status": "pending_send",
        "deliver_after": 1_030,
        "undo_available": True,
    }

    cancelled = cancel_proton_local_delayed_send_job(job, now=1_010)

    assert cancelled["status"] == "cancelled"
    assert cancelled["payload"] is None
    assert cancelled["undo_available"] is False
    assert cancelled["decision"] == "user_cancelled"


def test_after_deadline_undo_is_disabled_and_receipt_has_no_credentials() -> None:
    from backend.core.api.app.services.connected_accounts_service import (
        cancel_proton_local_delayed_send_job,
        complete_proton_local_delayed_send_job,
    )

    job = {
        "status": "pending_send",
        "deliver_after": 1_030,
        "undo_available": True,
        "payload": send_payload(),
    }
    undo = cancel_proton_local_delayed_send_job(job, now=1_031)
    assert undo["status"] == "pending_send"
    assert undo["payload"] is None
    assert undo["undo_available"] is False
    assert "cannot recall" in undo["undo_disabled_reason"]

    receipt = complete_proton_local_delayed_send_job(job, delivery_result={"message_id": "smtp-1"}, now=1_031)
    assert receipt["status"] == "delivered"
    assert receipt["payload"] is None
    assert receipt["undo_available"] is False
    assert receipt["receipt"]["message_id"] == "smtp-1"
    assert_no_secret_text(receipt)


def test_send_payloads_with_smtp_credentials_are_rejected() -> None:
    from backend.core.api.app.services.connected_accounts_service import build_proton_local_delayed_send_job

    with pytest.raises(ValueError, match="plaintext"):
        build_proton_local_delayed_send_job(
            row=local_connector_row(capabilities=["read", "write"]),
            payload=send_payload() | {"smtp_password": "secret"},
            approved=True,
            now=1_000,
        )


def local_connector_row(*, capabilities: list[str]) -> dict:
    return {
        "id": "acct-local-1",
        "execution_mode": "local_connector",
        "connector_provider_id": "protonmail_bridge",
        "connector_status": "online",
        "local_connector_session_id": "lcs_1",
        "connector_public_metadata": {"capabilities": capabilities},
    }


def send_payload() -> dict:
    return {
        "to": ["recipient@example.test"],
        "subject": "Hello",
        "body_text": "A non-secret test email body.",
    }


def assert_no_secret_text(value: object) -> None:
    serialized = str(value).lower()
    for forbidden in ["smtp_password", "imap_password", "bridge_password", "proton_password", "smtp-secret", "bridge-secret"]:
        assert forbidden not in serialized
