# contract-test-file: infrastructure
"""Focused privacy and classification coverage for Celery chat failure boundaries."""

from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import Mock

import pytest
from celery import Celery
from celery.exceptions import Ignore, Retry, SoftTimeLimitExceeded

from backend.core.api.app.tasks import base_task, celery_config


AI_TASK = base_task.AI_CHAT_TASK_NAME
PRIVATE_CONTENT = "private user text that must not enter notification metadata"


def _request_data() -> dict[str, object]:
    return {
        "chat_id": "chat-1",
        "message_id": "message-1",
        "current_user_content": PRIVATE_CONTENT,
        "message_history": [{"role": "user", "content": PRIVATE_CONTENT}],
    }


def _sender(name: str) -> SimpleNamespace:
    return SimpleNamespace(
        name=name,
        request=SimpleNamespace(
            delivery_info={"routing_key": "app_ai"},
            hostname="worker-test",
        ),
    )


def _message(
    *,
    name: str = AI_TASK,
    task_id: str = "task-1",
    request_data: object | None = None,
) -> SimpleNamespace:
    request_payload = _request_data() if request_data is None else request_data
    return SimpleNamespace(
        headers={"task": name, "id": task_id},
        payload=([request_payload, {"config": "safe"}], {}, None),
    )


# contract-test: supporting surface=rest_api assertions=operational-monitoring.chat-failures.email-trigger
def test_ai_dedup_store_failure_alerts_before_ignore_without_private_content(
    monkeypatch,
    caplog,
) -> None:
    notify = Mock(return_value=True)
    monkeypatch.setattr(base_task, "notify_chat_failure_sync", notify)
    monkeypatch.setattr(
        base_task,
        "acquire_celery_task_dedup_lock",
        Mock(side_effect=RuntimeError(PRIVATE_CONTENT)),
    )

    task = base_task.DedupedTask()
    task.name = AI_TASK
    task.bind(Celery("chat-failure-boundary"))
    task.push_request(id="dedup-task-1")
    monkeypatch.setattr(task, "update_state", Mock())
    try:
        with pytest.raises(Ignore):
            task(_request_data(), {"config": "safe"})
    finally:
        task.pop_request()

    notify.assert_called_once_with(
        "chat-1:message-1",
        stage="dispatch",
        category="unexpected_error",
    )
    assert PRIVATE_CONTENT not in caplog.text
    task.update_state.assert_called_once_with(
        state="FAILURE",
        meta={
            "exc_type": "DedupLockUnavailable",
            "exc_message": "Celery dedup lock unavailable",
        },
    )


# contract-test: supporting surface=rest_api assertions=operational-monitoring.chat-failures.email-trigger
def test_ordinary_duplicate_delivery_remains_silent(monkeypatch) -> None:
    notify = Mock(return_value=True)
    monkeypatch.setattr(base_task, "notify_chat_failure_sync", notify)
    monkeypatch.setattr(
        base_task,
        "acquire_celery_task_dedup_lock",
        Mock(return_value=False),
    )

    task = base_task.DedupedTask()
    task.name = AI_TASK
    task.bind(Celery("chat-failure-duplicate"))
    task.push_request(id="duplicate-task-1")
    try:
        with pytest.raises(Ignore):
            task(_request_data(), {})
    finally:
        task.pop_request()

    notify.assert_not_called()


# contract-test: supporting surface=rest_api assertions=operational-monitoring.chat-failures.email-trigger
@pytest.mark.parametrize(
    ("exception", "category"),
    [
        (RuntimeError(PRIVATE_CONTENT), "unexpected_error"),
        (SoftTimeLimitExceeded(PRIVATE_CONTENT), "timeout"),
    ],
)
def test_terminal_ai_task_failure_uses_canonical_identity_and_safe_category(
    monkeypatch,
    caplog,
    exception,
    category,
) -> None:
    notify = Mock(return_value=True)
    monkeypatch.setattr(celery_config, "notify_chat_failure_sync", notify)

    celery_config.task_failure_handler(
        "terminal-task-1",
        exception,
        [],
        {"request_data_dict": _request_data()},
        None,
        None,
        sender=_sender(AI_TASK),
    )

    notify.assert_called_once_with(
        "chat-1:message-1",
        stage="inference",
        category=category,
    )
    assert PRIVATE_CONTENT not in caplog.text


# contract-test: supporting surface=rest_api assertions=operational-monitoring.chat-failures.email-trigger
def test_rejected_and_unknown_ai_messages_alert_from_decoded_metadata_only(
    monkeypatch,
    caplog,
) -> None:
    notify = Mock(return_value=True)
    monkeypatch.setattr(celery_config, "notify_chat_failure_sync", notify)
    message = _message()

    celery_config.task_rejected_handler(message, RuntimeError(PRIVATE_CONTENT))
    notify.assert_called_once_with(
        "chat-1:message-1",
        stage="dispatch",
        category="unexpected_error",
    )

    notify.reset_mock()
    celery_config.task_unknown_handler(
        message,
        RuntimeError(PRIVATE_CONTENT),
        AI_TASK,
        "task-1",
    )
    notify.assert_called_once_with(
        "chat-1:message-1",
        stage="dispatch",
        category="unexpected_error",
    )
    assert PRIVATE_CONTENT not in caplog.text


# contract-test: supporting surface=rest_api assertions=operational-monitoring.chat-failures.email-trigger
def test_invalid_ai_identity_falls_back_to_task_id(monkeypatch) -> None:
    notify = Mock(return_value=True)
    monkeypatch.setattr(celery_config, "notify_chat_failure_sync", notify)
    message = _message(request_data={"chat_id": 42, "message_id": PRIVATE_CONTENT})

    celery_config.task_unknown_handler(
        message,
        RuntimeError("registration failure"),
        AI_TASK,
        "fallback-task-id",
    )

    notify.assert_called_once_with(
        "fallback-task-id",
        stage="dispatch",
        category="unexpected_error",
    )


# contract-test: supporting surface=rest_api assertions=operational-monitoring.chat-failures.email-trigger
def test_retry_cancel_and_non_ai_boundaries_do_not_alert(monkeypatch) -> None:
    notify = Mock(return_value=True)
    monkeypatch.setattr(celery_config, "notify_chat_failure_sync", notify)

    celery_config.task_failure_handler(
        "retry-task-1",
        Retry(),
        [_request_data(), {}],
        {},
        None,
        None,
        sender=_sender(AI_TASK),
    )
    celery_config.task_retry_handler(
        SimpleNamespace(id="retry-task-1", name=AI_TASK),
        RuntimeError(PRIVATE_CONTENT),
        None,
        sender=_sender(AI_TASK),
    )
    celery_config.task_revoked_handler(
        SimpleNamespace(id="revoked-task-1", name=AI_TASK),
        True,
        "SIGTERM",
        False,
    )
    celery_config.task_failure_handler(
        "ordinary-task-1",
        RuntimeError("ordinary failure"),
        [],
        {},
        None,
        None,
        sender=_sender("app.tasks.ordinary"),
    )
    celery_config.task_rejected_handler(
        _message(name="app.tasks.ordinary"),
        RuntimeError("ordinary rejection"),
    )
    celery_config.task_unknown_handler(
        _message(name="app.tasks.ordinary"),
        RuntimeError("ordinary unknown"),
        "app.tasks.ordinary",
        "ordinary-task-1",
    )

    notify.assert_not_called()
