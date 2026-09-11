# Focused contracts for managed-server chat failure notifications.
# Real Lua runs in fakeredis; no product server, provider, or email is contacted.
# Tests cover terminal classification, concurrent allowance/deduplication,
# environment exclusion, safe payloads, and transport failures.
# Architecture: docs/architecture/core/chat-failure-notifications.md.
# contract-test-file: supporting

import asyncio
import hashlib
import importlib.util
import sys
from pathlib import Path
from types import ModuleType, SimpleNamespace
from unittest.mock import AsyncMock, Mock

import fakeredis.aioredis
import pytest

from backend.shared.python_utils import chat_failure_notifications as dispatch


def stub(monkeypatch, name, **attrs):
    module = ModuleType(name)
    module.__dict__.update(attrs)
    monkeypatch.setitem(sys.modules, name, module)


@pytest.fixture
async def sender(monkeypatch):
    app = SimpleNamespace(task=lambda **kw: lambda f: f, send_task=Mock())
    stub(monkeypatch, "backend.core.api.app.tasks.celery_config", app=app)
    spec = importlib.util.spec_from_file_location(
        "chat_failure_email_under_test",
        Path(__file__).resolve().parents[1] / "core/api/app/tasks/email_tasks/chat_failure_email_task.py",
    )
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    redis = fakeredis.aioredis.FakeRedis()

    class Cache:
        @property
        async def client(self):
            return redis

        async def close(self):
            pass

    mail = SimpleNamespace(send_email=AsyncMock(return_value=True))
    secrets = SimpleNamespace(initialize=AsyncMock(), aclose=AsyncMock())
    stub(monkeypatch, "backend.core.api.app.services.cache", CacheService=Cache)
    stub(monkeypatch, "backend.core.api.app.services.email_template", EmailTemplateService=lambda **kw: mail)
    stub(monkeypatch, "backend.core.api.app.utils.secrets_manager", SecretsManager=lambda: secrets)
    monkeypatch.setattr(module, "notification_environment", lambda: "development")
    monkeypatch.setenv("SERVER_OWNER_EMAIL", "admin@example.invalid")
    monkeypatch.setenv("BUILD_COMMIT_SHA", "a" * 40)
    yield SimpleNamespace(module=module, redis=redis, mail=mail, app=app)
    await redis.aclose()


def fingerprint(value):
    return hashlib.sha256(str(value).encode()).hexdigest()


# contract-test: supporting surface=rest_api assertions=operational-monitoring.chat-failures.email-trigger
@pytest.mark.parametrize("result,expected", [
    ({"status": "completed", "main_processing_output": "safe ERROR_MARKER text"}, "inference"),
    ({"preprocessing_summary": {"can_proceed": False, "rejection_reason": "internal_error_llm_preprocessing_failed"}}, "preprocessing"),
    ({"interrupted_by_soft_time_limit": True}, "inference"),
    ({"_celery_task_state": "FAILURE"}, "inference"),
    ({"interrupted_by_revocation": True, "_celery_task_state": "FAILURE"}, None),
    ({"preprocessing_summary": {"can_proceed": False, "rejection_reason": "insufficient_team_credits"}}, None),
    ({"preprocessing_summary": {"can_proceed": False, "rejection_reason": "harmful_or_illegal_detected"}}, None),
    ({"preprocessing_summary": {"can_proceed": False, "rejection_reason": "misuse_detected"}}, None),
    ({"status": "completed", "main_processing_output": "A useful answer after fallback"}, None),
])
# contract-test: supporting surface=rest_api assertions=operational-monitoring.chat-failures.email-trigger
def test_terminal_classification(result, expected):
    assert dispatch.failure_stage(result, "ERROR_MARKER") == expected


# contract-test: supporting surface=rest_api assertions=operational-monitoring.chat-failures.daily-cap
@pytest.mark.asyncio
async def test_concurrent_failures_share_five_slots_and_deduplicate(sender):
    results = await asyncio.gather(*[
        sender.module.deliver_chat_failure(fingerprint(i), "inference", "processing_error")
        for i in list(range(12)) + list(range(12))
    ])
    assert results.count("accepted") == 5
    assert results.count("suppressed") == 7
    assert results.count("duplicate") == 12
    assert sender.mail.send_email.await_count == 5
    assert sender.mail.send_email.call_args.kwargs["context"]["cap_reached"] is True
    # A fresh Cache instance is created for every call, modeling worker restart.
    assert await sender.module.deliver_chat_failure(fingerprint(20), "inference", "processing_error") == "suppressed"


# contract-test: supporting surface=rest_api assertions=operational-monitoring.chat-failures.daily-cap
@pytest.mark.asyncio
async def test_independent_environment_and_next_utc_day(sender, monkeypatch):
    for i in range(5):
        await sender.module.deliver_chat_failure(fingerprint(i), "inference", "processing_error")
    monkeypatch.setattr(sender.module, "notification_environment", lambda: "production")
    assert await sender.module.deliver_chat_failure(fingerprint(0), "inference", "processing_error") == "accepted"
    monkeypatch.setattr(sender.module, "notification_environment", lambda: "development")
    monkeypatch.setattr(sender.module, "datetime", SimpleNamespace(now=lambda tz: SimpleNamespace(date=lambda: SimpleNamespace(isoformat=lambda: "2099-01-01"))))
    assert await sender.module.deliver_chat_failure(fingerprint(0), "inference", "processing_error") == "duplicate"
    assert await sender.module.deliver_chat_failure(fingerprint(99), "inference", "processing_error") == "accepted"


# contract-test: supporting surface=rest_api assertions=operational-monitoring.chat-failures.email-trigger
@pytest.mark.asyncio
async def test_self_host_never_uses_limiter_or_mail(sender, monkeypatch):
    monkeypatch.setattr(sender.module, "notification_environment", lambda: "self_hosted")
    assert await sender.module.deliver_chat_failure(fingerprint(1), "inference", "processing_error") == "self_hosted_disabled"
    assert await sender.redis.dbsize() == 0
    sender.mail.send_email.assert_not_called()


# contract-test: supporting surface=rest_api assertions=operational-monitoring.chat-failures.safe-delivery
@pytest.mark.asyncio
async def test_private_data_cannot_enter_mail_and_unknown_delivery_never_retries(sender, monkeypatch, caplog):
    assert await sender.module.deliver_chat_failure(fingerprint(1), "private prompt", "processing_error") == "invalid_metadata"
    sender.mail.send_email.side_effect = RuntimeError("PRIVATE PROVIDER PAYLOAD")
    assert await sender.module.deliver_chat_failure(fingerprint(2), "inference", "processing_error") == "delivery_unknown"
    assert await sender.module.deliver_chat_failure(fingerprint(2), "inference", "processing_error") == "duplicate"
    assert sender.mail.send_email.await_count == 1
    assert "PRIVATE PROVIDER PAYLOAD" not in caplog.text
    context = sender.mail.send_email.call_args.kwargs["context"]
    assert set(context) == {"darkmode", "environment", "stage", "category", "revision", "failures", "suppressed", "slot", "daily_limit", "cap_reached"}
    assert fingerprint(2) not in str(context)


# contract-test: supporting surface=rest_api assertions=operational-monitoring.chat-failures.safe-delivery
@pytest.mark.asyncio
async def test_missing_recipient_limiter_and_rejected_transport_visible(sender, monkeypatch):
    monkeypatch.delenv("SERVER_OWNER_EMAIL")
    monkeypatch.delenv("ADMIN_NOTIFY_EMAIL", raising=False)
    assert await sender.module.deliver_chat_failure(fingerprint(1), "dispatch", "processing_error") == "missing_admin_email"
    monkeypatch.setenv("SERVER_OWNER_EMAIL", "admin@example.invalid")
    sender.mail.send_email.return_value = False
    assert await sender.module.deliver_chat_failure(fingerprint(2), "dispatch", "processing_error") == "rejected"
    monkeypatch.setattr(sender.redis, "eval", AsyncMock(side_effect=RuntimeError("private")))
    assert await sender.module.deliver_chat_failure(fingerprint(3), "dispatch", "processing_error") == "limiter_unavailable"


# contract-test: supporting surface=rest_api assertions=operational-monitoring.chat-failures.safe-delivery
@pytest.mark.asyncio
async def test_dispatch_redacts_identity_and_handles_broker_failure(sender, monkeypatch, caplog):
    monkeypatch.setattr(dispatch, "notification_environment", lambda: "development")
    await dispatch.notify_chat_failure("private-request-id", stage="dispatch")
    kwargs = sender.app.send_task.call_args.kwargs
    assert kwargs["retry"] is False
    assert kwargs["kwargs"] == {"failure_fingerprint": fingerprint("private-request-id"), "stage": "dispatch", "category": "processing_error"}
    sender.app.send_task.side_effect = RuntimeError("private-request-id")
    await dispatch.notify_chat_failure("private-request-id", stage="dispatch")
    assert "queue_unavailable" in caplog.text
    assert "private-request-id" not in caplog.text


# contract-test: supporting surface=rest_api assertions=operational-monitoring.chat-failures.safe-delivery
@pytest.mark.parametrize("failure", [RuntimeError("missing policy"), SystemExit("missing policy")])
def test_cold_worker_policy_failure_cannot_terminate_chat(monkeypatch, failure):
    stub(monkeypatch, "backend.core.api.app.utils.server_mode", get_allowed_domain=lambda: None, get_server_edition=lambda: "development")
    stub(monkeypatch, "backend.core.api.app.services.domain_security", DomainSecurityService=lambda: SimpleNamespace(load_security_config=Mock(side_effect=failure)))
    assert dispatch.notification_environment() == "unavailable"
