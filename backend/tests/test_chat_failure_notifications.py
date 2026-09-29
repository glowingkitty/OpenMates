# Focused contracts for managed-server chat failure notifications.
# Real Lua runs in fakeredis; no product server, provider, or email is contacted.
# Tests cover terminal classification, complete coverage/deduplication,
# environment exclusion, safe payloads, and transport failures.
# Architecture: docs/architecture/core/chat-failure-notifications.md.
# contract-test-file: supporting

import asyncio
import hashlib
import importlib.util
import sys
import threading
from pathlib import Path
from types import ModuleType, SimpleNamespace
from unittest.mock import ANY, AsyncMock, Mock

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
    ({"failure_reason": "recovery_claim_failed"}, "inference"),
    ({"failure_category": "dispatch_failed", "_celery_task_state": "FAILURE"}, "dispatch"),
    ({"failure_category": "future_unknown", "_celery_task_state": "FAILURE"}, "inference"),
    ({"failure_category": "user_cancelled", "_celery_task_state": "FAILURE"}, None),
    ({"interrupted_by_revocation": True, "_celery_task_state": "FAILURE"}, None),
    ({"preprocessing_summary": {"can_proceed": False, "rejection_reason": "insufficient_team_credits"}}, None),
    ({"preprocessing_summary": {"can_proceed": False, "rejection_reason": "harmful_or_illegal_detected"}}, None),
    ({"preprocessing_summary": {"can_proceed": False, "rejection_reason": "misuse_detected"}}, None),
    ({"status": "completed", "main_processing_output": "A useful answer after fallback"}, None),
])
# contract-test: supporting surface=rest_api assertions=operational-monitoring.chat-failures.email-trigger
def test_terminal_classification(result, expected):
    assert dispatch.failure_stage(result, "ERROR_MARKER") == expected


@pytest.mark.parametrize(
    "result,expected",
    [
        (
            {
                "status": "completed",
                "preprocessing_summary": {
                    "can_proceed": False,
                    "rejection_reason": "internal_error_llm_preprocessing_failed",
                },
            },
            "failed_before_main",
        ),
        (
            {"status": "completed", "main_processing_output": "ERROR_MARKER"},
            "failed_during_main",
        ),
        (
            {"status": "completed", "main_processing_output": "Useful answer"},
            "completed",
        ),
        (
            {"interrupted_by_soft_time_limit": True},
            "soft_limited",
        ),
        (
            {"interrupted_by_revocation": True},
            "revoked",
        ),
    ],
)
# contract-test: supporting surface=rest_api assertions=chats.completion.recovery-takeover
def test_observability_terminal_classification(result, expected):
    assert dispatch.terminal_class(result, "ERROR_MARKER") == expected


# contract-test: supporting surface=rest_api assertions=operational-monitoring.chat-failures.daily-cap
@pytest.mark.asyncio
async def test_concurrent_distinct_failures_all_send_and_duplicates_are_excluded(sender):
    results = await asyncio.gather(*[
        sender.module.deliver_chat_failure(fingerprint(i), "inference", "processing_error")
        for i in list(range(12)) + list(range(12))
    ])
    assert results.count("accepted") == 12
    assert results.count("duplicate") == 12
    assert sender.mail.send_email.await_count == 12
    failure_numbers = sorted(
        call.kwargs["context"]["failures"]
        for call in sender.mail.send_email.await_args_list
    )
    assert failure_numbers == list(range(1, 13))
    # A fresh Cache instance is created for every call, modeling worker restart;
    # later distinct failures remain eligible without a daily drop threshold.
    assert await sender.module.deliver_chat_failure(fingerprint(20), "inference", "processing_error") == "accepted"


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
    assert set(context) == {"darkmode", "environment", "stage", "category", "revision", "failures"}
    assert fingerprint(2) not in str(context)


# contract-test: supporting surface=rest_api assertions=operational-monitoring.chat-failures.safe-delivery
@pytest.mark.asyncio
async def test_missing_recipient_dedupe_and_rejected_transport_visible(sender, monkeypatch):
    monkeypatch.delenv("SERVER_OWNER_EMAIL")
    monkeypatch.delenv("ADMIN_NOTIFY_EMAIL", raising=False)
    assert await sender.module.deliver_chat_failure(fingerprint(1), "dispatch", "processing_error") == "missing_admin_email"
    monkeypatch.setenv("SERVER_OWNER_EMAIL", "admin@example.invalid")
    sender.mail.send_email.return_value = False
    assert await sender.module.deliver_chat_failure(fingerprint(2), "dispatch", "processing_error") == "rejected"
    monkeypatch.setattr(sender.redis, "eval", AsyncMock(side_effect=RuntimeError("private")))
    assert await sender.module.deliver_chat_failure(fingerprint(3), "dispatch", "processing_error") == "dedupe_unavailable"


# contract-test: supporting surface=rest_api assertions=operational-monitoring.chat-failures.safe-delivery
@pytest.mark.asyncio
async def test_dispatch_redacts_identity_and_handles_broker_failure(sender, monkeypatch, caplog):
    monkeypatch.setattr(dispatch, "notification_environment", lambda: "development")
    assert await dispatch.notify_chat_failure("private-request-id", stage="dispatch") is True
    kwargs = sender.app.send_task.call_args.kwargs
    assert kwargs["retry"] is True
    assert kwargs["retry_policy"] == dispatch.QUEUE_RETRY_POLICY
    assert kwargs["kwargs"] == {"failure_fingerprint": fingerprint("private-request-id"), "stage": "dispatch", "category": "processing_error"}
    sender.app.send_task.side_effect = RuntimeError("private-request-id")
    assert await dispatch.notify_chat_failure("private-request-id", stage="dispatch") is False
    assert "queue_unavailable" in caplog.text
    assert "private-request-id" not in caplog.text

    sender.app.send_task.side_effect = None
    assert await dispatch.notify_chat_failure("private-request-id", stage="not-allowed") is False
    monkeypatch.setattr(dispatch, "notification_environment", lambda: "self_hosted")
    assert await dispatch.notify_chat_failure("private-request-id", stage="dispatch") is False


# contract-test: supporting surface=rest_api assertions=operational-monitoring.chat-failures.safe-delivery
@pytest.mark.asyncio
async def test_sync_dispatch_is_event_loop_safe_and_timeout_bounded(sender, monkeypatch, caplog):
    monkeypatch.setattr(dispatch, "notification_environment", lambda: "development")

    # This synchronous helper is intentionally called while an asyncio loop runs.
    assert dispatch.notify_chat_failure_sync("request-1", stage="inference") is True

    release = threading.Event()
    sender.app.send_task.side_effect = lambda *args, **kwargs: release.wait(0.1)
    monkeypatch.setattr(dispatch, "QUEUE_TIMEOUT_SECONDS", 0.01)
    assert dispatch.notify_chat_failure_sync("request-2", stage="inference") is False
    release.set()
    assert "queue_delivery_unknown" in caplog.text


# contract-test: supporting surface=rest_api assertions=operational-monitoring.chat-failures.safe-delivery
@pytest.mark.parametrize("failure", [RuntimeError("missing policy"), SystemExit("missing policy")])
def test_cold_worker_policy_failure_cannot_terminate_chat(monkeypatch, failure):
    stub(monkeypatch, "backend.core.api.app.utils.server_mode", get_allowed_domain=lambda: None, get_server_edition=lambda: "development")
    stub(monkeypatch, "backend.core.api.app.services.domain_security", DomainSecurityService=lambda: SimpleNamespace(load_security_config=Mock(side_effect=failure)))
    assert dispatch.notification_environment() == "unavailable"


def _wrapper_request() -> dict:
    return {
        "chat_id": "chat-1",
        "message_id": "message-1",
        "user_id": "user-1",
        "user_id_hash": "hash-1",
        "message_history": [],
        "is_incognito": True,
    }


def _stub_wrapper_terminal_cleanup(monkeypatch, ask_skill_task, *, state: str = "STARTED") -> None:
    monkeypatch.setattr(
        ask_skill_task.celery_config.app,
        "AsyncResult",
        lambda _task_id: SimpleNamespace(state=state),
    )
    monkeypatch.setattr(ask_skill_task, "_cleanup_on_task_failure", AsyncMock())
    monkeypatch.setattr(ask_skill_task, "_mark_sub_chat_terminal_failure", AsyncMock())
    monkeypatch.setattr(ask_skill_task, "_mark_recovery_inference_failed", AsyncMock())
    monkeypatch.setattr(
        ask_skill_task,
        "_update_user_task_execution_state_with_new_directus",
        AsyncMock(),
    )
    monkeypatch.setattr(ask_skill_task.process_ai_skill_ask_task, "update_state", Mock())


@pytest.mark.parametrize(
    "raw_request,expected_identity",
    [
        ({"chat_id": "chat-1", "message_id": "message-1"}, "chat-1:message-1"),
        ({"chat_id": 42}, "validation-task-1"),
    ],
)
# contract-test: supporting surface=rest_api assertions=operational-monitoring.chat-failures.email-trigger
def test_task_wrapper_validation_failure_queues_sanitized_identity(
    monkeypatch,
    raw_request,
    expected_identity,
):
    from celery.exceptions import Ignore

    from backend.apps.ai.tasks import ask_skill_task

    notify = Mock(return_value=True)
    monkeypatch.setattr(ask_skill_task, "notify_chat_failure_sync", notify)
    monkeypatch.setattr(ask_skill_task.process_ai_skill_ask_task, "update_state", Mock())

    task = ask_skill_task.process_ai_skill_ask_task
    task.push_request(id="validation-task-1")
    try:
        with pytest.raises(Ignore):
            task.run(raw_request, {})
    finally:
        task.pop_request()

    notify.assert_called_once_with(
        expected_identity,
        stage="preprocessing",
        category="unexpected_error",
    )


@pytest.mark.parametrize(
    "claim_state,failure_category,expected_task_state,expected_alert_stage,expected_reason,expected_revoked",
    [
        ("FAILED", "claim_expired", "FAILURE", "inference", "recovery_claim_failed", False),
        ("FAILED", "user_cancelled", "FAILURE", None, "recovery_claim_cancelled", True),
        ("FAILED", "insufficient_credits", "FAILURE", None, "recovery_claim_excluded", False),
        ("FAILED", "future_unknown", "FAILURE", "inference", "recovery_claim_failed", False),
        ("FAILED", None, "FAILURE", "inference", "recovery_claim_failed", False),
        ("RUNNING", None, "SUCCESS", None, None, False),
        ("TERMINAL", None, "SUCCESS", None, None, False),
    ],
)
# contract-test: supporting surface=rest_api assertions=operational-monitoring.chat-failures.email-trigger
def test_recovery_unclaimed_result_only_fails_for_failed_claim(
    claim_state,
    failure_category,
    expected_task_state,
    expected_alert_stage,
    expected_reason,
    expected_revoked,
):
    from backend.apps.ai.tasks import ask_skill_task

    result = ask_skill_task._recovery_unclaimed_result(
        {
            "claimed": False,
            "state": claim_state,
            "failure_category": failure_category,
        }
    )

    assert result["_celery_task_state"] == expected_task_state
    assert dispatch.failure_stage(result, "ERROR_MARKER") == expected_alert_stage
    assert result["interrupted_by_revocation"] is expected_revoked
    if expected_reason:
        assert result["failure_reason"] == expected_reason
        assert result["failure_category"] == (failure_category or "unclassified")
    else:
        assert "failure_reason" not in result


# contract-test: supporting surface=rest_api assertions=operational-monitoring.chat-failures.email-trigger
def test_task_wrapper_runtime_failure_queues_one_notification(monkeypatch):
    from celery.exceptions import Ignore

    from backend.apps.ai.tasks import ask_skill_task

    notify = AsyncMock()
    monkeypatch.setattr(
        ask_skill_task,
        "_async_process_ai_skill_ask_task",
        AsyncMock(side_effect=RuntimeError("terminal runtime failure")),
    )
    monkeypatch.setattr(ask_skill_task, "notify_chat_failure", notify)
    _stub_wrapper_terminal_cleanup(monkeypatch, ask_skill_task)

    with pytest.raises(Ignore):
        ask_skill_task.process_ai_skill_ask_task.run(_wrapper_request(), {})

    notify.assert_awaited_once_with(
        "chat-1:message-1",
        stage="preprocessing",
        category="unexpected_error",
    )


# contract-test: supporting surface=rest_api assertions=operational-monitoring.chat-failures.email-trigger
def test_task_wrapper_revoked_runtime_failure_does_not_notify(monkeypatch):
    from celery.exceptions import Ignore

    from backend.apps.ai.tasks import ask_skill_task

    notify = AsyncMock()
    monkeypatch.setattr(
        ask_skill_task,
        "_async_process_ai_skill_ask_task",
        AsyncMock(side_effect=RuntimeError("cancelled runtime")),
    )
    monkeypatch.setattr(ask_skill_task, "notify_chat_failure", notify)
    _stub_wrapper_terminal_cleanup(
        monkeypatch,
        ask_skill_task,
        state=ask_skill_task.TASK_STATE_REVOKED,
    )

    task = ask_skill_task.process_ai_skill_ask_task
    task.push_request(id="task-1")
    try:
        with pytest.raises(Ignore):
            task.run(_wrapper_request(), {})
    finally:
        task.pop_request()

    notify.assert_not_awaited()
    ask_skill_task._mark_recovery_inference_failed.assert_awaited_once_with(
        ANY,
        "task-1",
        "user_cancelled",
    )


# contract-test: supporting surface=rest_api assertions=operational-monitoring.chat-failures.email-trigger
def test_task_wrapper_completed_envelope_with_terminal_error_queues_once(monkeypatch):
    from backend.apps.ai.tasks import ask_skill_task
    from backend.apps.ai.utils.preprocessing_history import STANDARDIZED_USER_ERROR_MESSAGE

    terminal_result = {
        "task_id": "task-1",
        "status": "completed",
        "preprocessing_summary": {"can_proceed": True},
        "main_processing_output": (
            "Useful partial app output.\n\n" + STANDARDIZED_USER_ERROR_MESSAGE
        ),
        "postprocessing_summary": {},
        "interrupted_by_soft_time_limit": False,
        "interrupted_by_revocation": False,
        "_celery_task_state": "SUCCESS",
    }
    notify = AsyncMock()
    monkeypatch.setattr(
        ask_skill_task,
        "_async_process_ai_skill_ask_task",
        AsyncMock(return_value=terminal_result),
    )
    monkeypatch.setattr(ask_skill_task, "notify_chat_failure", notify)
    monkeypatch.setattr(ask_skill_task.process_ai_skill_ask_task, "update_state", Mock())

    result = ask_skill_task.process_ai_skill_ask_task.run(_wrapper_request(), {})

    assert result == terminal_result
    notify.assert_awaited_once_with("chat-1:message-1", stage="inference")
