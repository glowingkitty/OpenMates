"""Events newsletter broadcast safety tests.

These tests cover the registry-backed OpenMates Events newsletter path that does
not publish a separate announcement page. The sender must still reuse the normal
newsletter subscriber filtering, delivery guard, simulation, and audit flow
before any real production broadcast can be approved.
"""

from __future__ import annotations

import sys
from types import ModuleType
from types import SimpleNamespace

import pytest

from backend.scripts import send_newsletter


RUN_AT = "2026-08-20T12:00:00+02:00"


def _events_args(**overrides: object) -> SimpleNamespace:
    defaults = {
        "admin_email": "admin@openmates.org",
        "base_url": "https://openmates.org",
        "dry_run": False,
        "events_preview": True,
        "lang": None,
        "limit": None,
        "render_to": None,
        "resend_confirm": False,
        "resume": False,
        "run_at": RUN_AT,
        "send": True,
        "simulate": True,
        "slug": None,
        "test_to": None,
    }
    defaults.update(overrides)
    return SimpleNamespace(**defaults)


# contract-test: direct surface=cli assertions=newsletter.campaign.deterministic-event-window,newsletter.campaign.accessible-event-layout
def test_events_broadcast_manifest_is_email_only_without_issue_slug() -> None:
    manifest = send_newsletter.load_broadcast_manifest(_events_args(send=False, simulate=False))

    assert manifest["slug"] == "openmates-events-2026-08-20"
    assert manifest["category"] == "openmates_events"
    assert manifest["mode"] == "email_only"
    assert manifest.get("chat_id") is None
    assert manifest["body_markdown"]["en"]
    assert manifest["metadata"]["campaign_type"] == "openmates_events"


# contract-test: direct surface=cli assertions=newsletter.campaign.eligible-idempotent-delivery,newsletter.campaign.accessible-event-layout
async def test_events_broadcast_simulation_reuses_subscriber_flow_without_sending(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    class FakeSecretsManager:
        async def initialize(self) -> None:
            return None

    class FakeDirectus:
        async def close(self) -> None:
            return None

    class FakeCache:
        async def close(self) -> None:
            return None

    class FakeEncryption:
        def __init__(self, cache_service: FakeCache) -> None:
            self.cache_service = cache_service

        async def initialize(self) -> None:
            return None

        async def decrypt_newsletter_email(self, _encrypted_email: str) -> str:
            return "subscriber@example.test"

        async def close(self) -> None:
            return None

    class FakeEmailTemplateService:
        def __init__(self, secrets_manager: FakeSecretsManager) -> None:
            self.secrets_manager = secrets_manager

    async def fake_fetch_subscribers(_directus: FakeDirectus) -> list[dict[str, object]]:
        return [
            {
                "id": "sub-1",
                "encrypted_email_address": "encrypted",
                "hashed_email": "hash-1",
                "language": "en",
                "darkmode": False,
                "unsubscribe_token": "token-1",
                "user_registration_status": "signup_complete",
                "categories": {"openmates_events": True},
            },
            {
                "id": "sub-2",
                "encrypted_email_address": "encrypted",
                "hashed_email": "hash-2",
                "language": "de",
                "darkmode": False,
                "unsubscribe_token": "token-2",
                "user_registration_status": "email_only",
                "categories": {"openmates_events": False},
            },
        ]

    async def fake_fetch_delivered(_slug: str, _directus: FakeDirectus) -> set[str]:
        return set()

    async def fake_check_ignored(_hashed_email: str, _directus: FakeDirectus) -> bool:
        return False

    async def fail_send_one(**_kwargs: object) -> bool:
        raise AssertionError("simulate mode must not send emails")

    def fail_load_manifest(_slug: str) -> dict[str, object]:
        raise AssertionError("events newsletters must not require issue YAML")

    def fail_write_sent_at(_slug: str, _sent_at: str) -> None:
        raise AssertionError("simulate mode must not persist sent_at")

    fake_cache_module = ModuleType("backend.core.api.app.services.cache")
    fake_cache_module.CacheService = FakeCache
    fake_directus_module = ModuleType("backend.core.api.app.services.directus.directus")
    fake_directus_module.DirectusService = FakeDirectus
    fake_email_template_module = ModuleType("backend.core.api.app.services.email_template")
    fake_email_template_module.EmailTemplateService = FakeEmailTemplateService
    fake_encryption_module = ModuleType("backend.core.api.app.utils.encryption")
    fake_encryption_module.EncryptionService = FakeEncryption
    fake_secrets_module = ModuleType("backend.core.api.app.utils.secrets_manager")
    fake_secrets_module.SecretsManager = FakeSecretsManager

    monkeypatch.setitem(sys.modules, "backend.core.api.app.services.cache", fake_cache_module)
    monkeypatch.setitem(sys.modules, "backend.core.api.app.services.directus.directus", fake_directus_module)
    monkeypatch.setitem(sys.modules, "backend.core.api.app.services.email_template", fake_email_template_module)
    monkeypatch.setitem(sys.modules, "backend.core.api.app.utils.encryption", fake_encryption_module)
    monkeypatch.setitem(sys.modules, "backend.core.api.app.utils.secrets_manager", fake_secrets_module)
    monkeypatch.setattr(send_newsletter, "AUDIT_LOG_DIR", tmp_path)
    monkeypatch.setattr(send_newsletter, "check_ignored_email", fake_check_ignored)
    monkeypatch.setattr(send_newsletter, "fetch_delivered_subscriber_ids", fake_fetch_delivered)
    monkeypatch.setattr(send_newsletter, "fetch_subscribers", fake_fetch_subscribers)
    monkeypatch.setattr(send_newsletter, "load_manifest", fail_load_manifest)
    monkeypatch.setattr(send_newsletter, "send_one", fail_send_one)
    monkeypatch.setattr(send_newsletter, "write_sent_at", fail_write_sent_at)

    result = await send_newsletter.run(_events_args())

    output = capsys.readouterr().out
    assert result == 0
    assert "Newsletter: openmates-events-2026-08-20" in output
    assert "Category:   openmates_events" in output
    assert "Total eligible: 1" in output
    assert "Skipping 1 who opted out of 'openmates_events'" in output
    assert "[SIMULATE" in output


# contract-test: direct surface=cli assertions=newsletter.campaign.eligible-idempotent-delivery,newsletter.campaign.accessible-event-layout
async def test_events_send_one_falls_back_to_english_for_unsupported_subscriber_language(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    captured: dict[str, object] = {}

    async def fake_send_email_once(**kwargs: object) -> tuple[bool, str]:
        captured.update(kwargs)
        return True, "sent"

    fake_delivery_guard = ModuleType("backend.core.api.app.services.email_delivery_guard")
    fake_delivery_guard.send_email_once = fake_send_email_once
    monkeypatch.setitem(sys.modules, "backend.core.api.app.services.email_delivery_guard", fake_delivery_guard)

    manifest = send_newsletter.load_broadcast_manifest(_events_args(send=True, simulate=False))

    ok = await send_newsletter.send_one(
        directus=object(),  # type: ignore[arg-type]
        email_template_service=object(),  # type: ignore[arg-type]
        manifest=manifest,
        subscriber_id="subscriber-fr",
        recipient_email="subscriber@example.test",
        recipient_lang="fr",
        darkmode=False,
        base_url="https://openmates.org",
        unsubscribe_url="https://openmates.org/#settings/newsletter/unsubscribe/token",
        is_registered=False,
    )

    assert ok is True
    assert captured["lang"] == "en"
    assert captured["subject"] == "Upcoming OpenMates events"
    assert "Upcoming events" in captured["context"]["newsletter_content"]  # type: ignore[index]


# contract-test: direct surface=cli assertions=newsletter.campaign.eligible-idempotent-delivery
async def test_events_send_one_reports_already_reserved_as_resume_skip(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    async def fake_send_email_once(**_kwargs: object) -> tuple[bool, str]:
        return False, "already_reserved"

    fake_delivery_guard = ModuleType("backend.core.api.app.services.email_delivery_guard")
    fake_delivery_guard.send_email_once = fake_send_email_once
    monkeypatch.setitem(sys.modules, "backend.core.api.app.services.email_delivery_guard", fake_delivery_guard)

    manifest = send_newsletter.load_broadcast_manifest(_events_args(send=True, simulate=False))

    result = await send_newsletter.send_one(
        directus=object(),  # type: ignore[arg-type]
        email_template_service=object(),  # type: ignore[arg-type]
        manifest=manifest,
        subscriber_id="subscriber-existing",
        recipient_email="subscriber@example.test",
        recipient_lang="en",
        darkmode=False,
        base_url="https://openmates.org",
        unsubscribe_url="https://openmates.org/#settings/newsletter/unsubscribe/token",
        is_registered=False,
    )

    assert result is None
