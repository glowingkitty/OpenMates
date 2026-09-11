#!/usr/bin/env python3
"""Durable, injectable delivery ledger for deterministic security reporting.

The module intentionally does not resolve credentials or send mail itself. A
caller supplies a sender backed by the existing container EmailTemplateService;
this keeps host scripts out of Vault and makes ambiguous outcomes fail closed.
"""

from __future__ import annotations

import argparse
import asyncio
from contextlib import contextmanager
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
import hashlib
import json
import os
from pathlib import Path
import secrets
import sqlite3
import subprocess
import sys
from typing import Any, Callable, Iterator


MAX_ATTEMPTS = 2
LOCK_TIMEOUT_SECONDS = 2
CLAIM_LEASE_SECONDS = 300
SCHEMA_VERSION = 2


def _now(value: str | None = None) -> datetime:
    if value:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
        return parsed.astimezone(timezone.utc)
    return datetime.now(timezone.utc)


def _timestamp(value: datetime) -> str:
    return value.replace(microsecond=0).isoformat().replace("+00:00", "Z")


def payload_hash(payload: dict[str, Any]) -> str:
    """Hash a canonical rendered payload without storing its content in receipts."""
    encoded = json.dumps(payload, sort_keys=True, separators=(",", ":"), ensure_ascii=True).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def stable_notification_id(kind: str, environment: str, subject_id: str) -> str:
    material = json.dumps([kind, environment, subject_id], separators=(",", ":"), ensure_ascii=True)
    return f"security-report-{hashlib.sha256(material.encode('utf-8')).hexdigest()[:32]}"


def default_delivery_ledger_path() -> Path:
    return Path("logs/security-reporting/delivery.sqlite3")


@dataclass(frozen=True)
class SendResult:
    state: str
    provider_message_id: str | None = None
    reason: str | None = None

    @classmethod
    def accepted(cls, provider_message_id: str | None = None) -> "SendResult":
        return cls("accepted", provider_message_id)

    @classmethod
    def queued(cls, provider_message_id: str | None = None) -> "SendResult":
        return cls("queued", provider_message_id)

    @classmethod
    def failed(cls, reason: str = "provider_rejected") -> "SendResult":
        return cls("failed", reason=reason)

    @classmethod
    def unknown(cls, reason: str = "provider_outcome_unknown") -> "SendResult":
        return cls("unknown", reason=reason)

    @classmethod
    def unavailable(cls, reason: str = "recipient_unavailable") -> "SendResult":
        return cls("unavailable", reason=reason)


@dataclass(frozen=True)
class DeliveryOutcome:
    state: str
    notification_id: str
    reason: str | None = None
    reconciliation_required: bool = False


class DeliveryLedger:
    """SQLite receipt store with short write transactions for concurrent workers."""

    def __init__(self, path: str | Path):
        self.path = Path(path)

    def _connect(self) -> sqlite3.Connection:
        self.path.parent.mkdir(parents=True, mode=0o700, exist_ok=True)
        os.chmod(self.path.parent, 0o700)
        # Create the database with private permissions before SQLite opens it.
        descriptor = os.open(self.path, os.O_CREAT | os.O_APPEND, 0o600)
        os.close(descriptor)
        os.chmod(self.path, 0o600)
        connection = sqlite3.connect(self.path, timeout=LOCK_TIMEOUT_SECONDS, isolation_level=None)
        connection.row_factory = sqlite3.Row
        connection.execute("PRAGMA busy_timeout=2000")
        version = int(connection.execute("PRAGMA user_version").fetchone()[0])
        if version > SCHEMA_VERSION:
            raise RuntimeError("delivery ledger schema is newer than this script")
        connection.execute(
            """CREATE TABLE IF NOT EXISTS delivery_receipts (
                notification_id TEXT PRIMARY KEY,
                payload_hash TEXT NOT NULL,
                state TEXT NOT NULL,
                request_key TEXT NOT NULL,
                attempt_count INTEGER NOT NULL DEFAULT 0,
                next_attempt_at TEXT,
                claim_until TEXT,
                claim_token TEXT,
                provider_message_id TEXT,
                reason_code TEXT,
                updated_at TEXT NOT NULL
            )"""
        )
        columns = {row[1] for row in connection.execute("PRAGMA table_info(delivery_receipts)")}
        if "claim_token" not in columns:
            connection.execute("ALTER TABLE delivery_receipts ADD COLUMN claim_token TEXT")
        if version < SCHEMA_VERSION:
            connection.execute(f"PRAGMA user_version={SCHEMA_VERSION}")
        return connection

    @contextmanager
    def _connection(self) -> Iterator[sqlite3.Connection]:
        connection = self._connect()
        try:
            yield connection
        finally:
            connection.close()

    def mark_unavailable(self, notification_id: str, body_hash: str, *, now: datetime) -> None:
        with self._connection() as connection:
            connection.execute(
                """INSERT INTO delivery_receipts (notification_id, payload_hash, state, request_key, reason_code, updated_at)
                   VALUES (?, ?, 'unavailable', ?, 'recipient_unavailable', ?)
                   ON CONFLICT(notification_id) DO UPDATE SET
                     state = 'unavailable', claim_until = NULL, claim_token = NULL,
                     reason_code = 'recipient_unavailable', updated_at = excluded.updated_at
                    WHERE delivery_receipts.state IN ('failed', 'unavailable')
                      AND delivery_receipts.payload_hash = excluded.payload_hash""",
                (notification_id, body_hash, f"security-report:{notification_id}", _timestamp(now)),
            )

    def claim(self, notification_id: str, body_hash: str, *, now: datetime, provider_supports_idempotency: bool) -> tuple[str, sqlite3.Row | None]:
        """Atomically reserve a due delivery without replaying unsafe outcomes."""
        with self._connection() as connection:
            connection.execute("BEGIN IMMEDIATE")
            row = connection.execute("SELECT * FROM delivery_receipts WHERE notification_id = ?", (notification_id,)).fetchone()
            if row is None:
                request_key = f"security-report:{notification_id}"
                connection.execute(
                    "INSERT INTO delivery_receipts (notification_id, payload_hash, state, request_key, updated_at) VALUES (?, ?, 'pending', ?, ?)",
                    (notification_id, body_hash, request_key, _timestamp(now)),
                )
                row = connection.execute("SELECT * FROM delivery_receipts WHERE notification_id = ?", (notification_id,)).fetchone()
            if row["payload_hash"] != body_hash:
                connection.execute("COMMIT")
                return "payload_mismatch", row
            if row["state"] in {"accepted", "queued"}:
                connection.execute("COMMIT")
                return row["state"], row
            if row["state"] == "unknown" and (row["reason_code"] == "claim_expired" or not provider_supports_idempotency):
                connection.execute("COMMIT")
                return "unknown", row
            if row["state"] == "unavailable":
                connection.execute(
                    "UPDATE delivery_receipts SET state = 'pending', reason_code = NULL, updated_at = ? WHERE notification_id = ?",
                    (_timestamp(now), notification_id),
                )
                row = connection.execute("SELECT * FROM delivery_receipts WHERE notification_id = ?", (notification_id,)).fetchone()
            if row["attempt_count"] >= MAX_ATTEMPTS:
                connection.execute("COMMIT")
                return row["state"], row
            if row["state"] == "pending" and row["claim_until"]:
                if _now(row["claim_until"]) > now:
                    connection.execute("COMMIT")
                    return "pending", row
                # A process may have sent immediately before crashing. It is not safe
                # to reclaim the lease without an explicit provider reconciliation.
                connection.execute(
                    "UPDATE delivery_receipts SET state = 'unknown', claim_until = NULL, claim_token = NULL, reason_code = 'claim_expired', updated_at = ? WHERE notification_id = ?",
                    (_timestamp(now), notification_id),
                )
                row = connection.execute("SELECT * FROM delivery_receipts WHERE notification_id = ?", (notification_id,)).fetchone()
                connection.execute("COMMIT")
                return "unknown", row
            due_at = row["next_attempt_at"]
            if due_at and _now(due_at) > now:
                connection.execute("COMMIT")
                return row["state"], row
            claim_token = secrets.token_urlsafe(24)
            connection.execute(
                "UPDATE delivery_receipts SET state = 'pending', claim_until = ?, claim_token = ?, updated_at = ? WHERE notification_id = ?",
                (_timestamp(now + timedelta(seconds=CLAIM_LEASE_SECONDS)), claim_token, _timestamp(now), notification_id),
            )
            row = connection.execute("SELECT * FROM delivery_receipts WHERE notification_id = ?", (notification_id,)).fetchone()
            connection.execute("COMMIT")
            return "claimed", row

    def complete(self, notification_id: str, claim_token: str, result: SendResult, *, now: datetime) -> bool:
        if result.state not in {"accepted", "queued", "failed", "unknown", "unavailable"}:
            raise ValueError("unsupported sender result")
        with self._connection() as connection:
            row = connection.execute("SELECT * FROM delivery_receipts WHERE notification_id = ?", (notification_id,)).fetchone()
            if row is None or row["state"] != "pending" or row["claim_token"] != claim_token:
                return False
            if row["claim_until"] and _now(row["claim_until"]) <= now:
                connection.execute(
                    "UPDATE delivery_receipts SET state = 'unknown', claim_until = NULL, claim_token = NULL, reason_code = 'claim_expired', updated_at = ? WHERE notification_id = ? AND claim_token = ?",
                    (_timestamp(now), notification_id, claim_token),
                )
                return False
            attempts = int(row["attempt_count"]) + (0 if result.state == "unavailable" else 1)
            next_attempt = None
            if result.state == "failed" and attempts < MAX_ATTEMPTS:
                next_attempt = _timestamp(now + timedelta(seconds=2 ** (attempts - 1)))
            # Store stable error categories only, not provider response bodies.
            reason = "provider_rejected" if result.state == "failed" else ("provider_outcome_unknown" if result.state == "unknown" else ("recipient_unavailable" if result.state == "unavailable" else None))
            updated = connection.execute(
                "UPDATE delivery_receipts SET state = ?, attempt_count = ?, next_attempt_at = ?, claim_until = NULL, claim_token = NULL, provider_message_id = ?, reason_code = ?, updated_at = ? WHERE notification_id = ? AND claim_token = ?",
                (result.state, attempts, next_attempt, result.provider_message_id, reason, _timestamp(now), notification_id, claim_token),
            )
            return updated.rowcount == 1


Sender = Callable[[dict[str, str]], SendResult]


def resolve_recipient(environment: dict[str, str] | None = None) -> str | None:
    """Resolve only owner configuration, never report-derived recipient content."""
    values = environment or {}
    return values.get("SERVER_OWNER_EMAIL") or values.get("ADMIN_NOTIFY_EMAIL") or None


def deliver_notification(*, ledger_path: str | Path, notification_id: str, payload: dict[str, Any], recipient: str | None, sender: Sender, provider_supports_idempotency: bool = False, now: str | None = None, dry_run: bool = False) -> DeliveryOutcome:
    """Send one notification if safely claimable; never send in unavailable mode."""
    current = _now(now)
    if dry_run:
        return DeliveryOutcome("pending", notification_id, "dry run: not sent or persisted")
    payload = dict(payload)
    if any(not isinstance(payload.get(key), str) for key in ("subject", "text", "html")):
        raise ValueError("rendered subject, text and html must be strings")
    ledger = DeliveryLedger(ledger_path)
    if not recipient or not recipient.strip():
        ledger.mark_unavailable(notification_id, payload_hash(payload), now=current)
        return DeliveryOutcome("unavailable", notification_id, "SERVER_OWNER_EMAIL/ADMIN_NOTIFY_EMAIL is not configured")
    claim, row = ledger.claim(notification_id, payload_hash(payload), now=current, provider_supports_idempotency=provider_supports_idempotency)
    if claim == "claimed":
        request = {
            "notification_id": notification_id,
            "request_key": row["request_key"],
            "recipient": recipient.strip(),
            "subject": str(payload.get("subject", "")),
            "text": str(payload.get("text", "")),
            "html": str(payload.get("html", "")),
        }
        try:
            result = sender(request)
        except Exception:
            # A local transport failure can occur after a provider received mail.
            result = SendResult.unknown("sender_exception")
        completed_at = _now(now) if now else _now()
        if not ledger.complete(notification_id, row["claim_token"], result, now=completed_at):
            return DeliveryOutcome("unknown", notification_id, "claim completion requires reconciliation", True)
        return DeliveryOutcome(result.state, notification_id, reconciliation_required=result.state == "unknown")
    if claim == "unknown":
        return DeliveryOutcome("unknown", notification_id, "provider outcome requires reconciliation", True)
    if claim == "payload_mismatch":
        return DeliveryOutcome("failed", notification_id, "stable notification payload changed")
    return DeliveryOutcome(claim, notification_id, reconciliation_required=claim == "unknown")


def container_email_sender(*, runner: Callable[..., Any] = subprocess.run, timeout: int = 30) -> Sender:
    """Return a sender that runs the authenticated transport only in the API container."""
    # The API image contains the email service, not host reporting scripts.
    # Execute this trusted module's source while keeping request data on stdin.
    source = Path(__file__).read_text(encoding="utf-8")
    def send(request: dict[str, str]) -> SendResult:
        body = {key: request.get(key, "") for key in ("notification_id", "request_key", "subject", "text", "html", "recipient")}
        try:
            result = runner(
                ["docker", "exec", "-i", "api", "python", "-c", source, "--container-send"],
                input=json.dumps(body, separators=(",", ":")), capture_output=True, text=True, check=False, timeout=timeout,
            )
            if result.returncode != 0:
                return SendResult.unknown("container_transport_unknown")
            response = json.loads(result.stdout)
            state = response.get("state")
            if state in {"accepted", "queued", "failed", "unknown"}:
                return SendResult(state, response.get("provider_message_id"))
            if state == "unavailable":
                return SendResult.unavailable()
        except Exception:
            pass
        return SendResult.unknown("container_transport_unknown")
    return send


async def _container_send(request: dict[str, Any]) -> dict[str, str | None]:
    """Use the API container's Vault-backed transport without exposing secrets."""
    recipient = resolve_recipient(os.environ)
    if not recipient:
        return {"state": "unavailable", "provider_message_id": None}
    requested = request.get("recipient", "configured_destination")
    if requested not in {"configured_destination", recipient}:
        return {"state": "unavailable", "provider_message_id": None}
    subject, text, html = (str(request.get(key, "")) for key in ("subject", "text", "html"))
    if not subject or len(subject) > 240 or len(text) > 20000 or len(html) > 50000:
        return {"state": "failed", "provider_message_id": None}
    secrets_manager = None
    try:
        from backend.core.api.app.services.email.brevo_provider import BrevoProvider
        from backend.core.api.app.services.email_template import EmailTemplateService
        from backend.core.api.app.utils.secrets_manager import SecretsManager

        secrets_manager = SecretsManager()
        if not await secrets_manager.initialize():
            return {"state": "unavailable", "provider_message_id": None}
        email_service = EmailTemplateService(secrets_manager)
        api_key = await secrets_manager.get_secret(secret_path="kv/data/providers/brevo", secret_key="api_key")
        if not api_key:
            return {"state": "unavailable", "provider_message_id": None}
        accepted = await BrevoProvider(api_key).send_email(
            sender_name=email_service.default_sender_name,
            sender_email=email_service.default_sender_email,
            recipient_email=recipient,
            recipient_name="",
            subject=subject,
            html_content=html,
            plain_text_content=text,
            email_headers={"Precedence": "bulk", "Auto-Submitted": "auto-generated", "X-OpenMates-Request-Key": str(request.get("request_key", ""))},
            attachments=None,
        )
        # This provider collapses rejections and network ambiguity into False.
        # Only an explicit acceptance is safe to classify without reconciliation.
        return {"state": "accepted" if accepted else "unknown", "provider_message_id": None}
    except Exception:
        return {"state": "unknown", "provider_message_id": None}
    finally:
        if secrets_manager is not None:
            try:
                await secrets_manager.close()
            except Exception:
                # Cleanup cannot change an already observed provider outcome.
                pass


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--container-send", action="store_true")
    args = parser.parse_args()
    if not args.container_send:
        parser.error("--container-send is required")
    try:
        request = json.load(sys.stdin)
        if not isinstance(request, dict):
            raise ValueError("request must be an object")
    except Exception:
        print(json.dumps({"state": "failed", "provider_message_id": None}))
        return 2
    print(json.dumps(asyncio.run(_container_send(request)), separators=(",", ":")))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
