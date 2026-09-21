"""Regression coverage for durable reports when email notifications are disabled."""

import pytest

import importlib.util
from pathlib import Path
import sys
import types


class _FakeCeleryApp:
    def task(self, *args, **kwargs):
        return lambda function: function

    def send_task(self, *args, **kwargs):
        return None


celery_config = types.ModuleType("backend.core.api.app.tasks.celery_config")
celery_config.app = _FakeCeleryApp()
base_task = types.ModuleType("backend.core.api.app.tasks.base_task")
base_task.BaseServiceTask = object
sys.modules[celery_config.__name__] = celery_config
sys.modules[base_task.__name__] = base_task
module_path = Path(__file__).resolve().parents[1] / "core/api/app/tasks/email_tasks/issue_report_email_task.py"
spec = importlib.util.spec_from_file_location("issue_report_email_task_under_test", module_path)
assert spec and spec.loader
issue_report_email_task = importlib.util.module_from_spec(spec)
spec.loader.exec_module(issue_report_email_task)


class FakeEncryptionService:
    async def encrypt_issue_report_data(self, value: str) -> str:
        return f"encrypted:{value}"


class FakeS3Service:
    def __init__(self) -> None:
        self.uploads: list[dict] = []

    async def upload_file(self, **kwargs) -> None:
        self.uploads.append(kwargs)


class FakeDirectusService:
    def __init__(self) -> None:
        self.updates: list[tuple[str, str, dict]] = []

    async def update_item(self, collection: str, item_id: str, data: dict) -> None:
        self.updates.append((collection, item_id, data))


class FakeTask:
    def __init__(self) -> None:
        self.encryption_service = FakeEncryptionService()
        self.s3_service = FakeS3Service()
        self.directus_service = FakeDirectusService()
        self.email_template_service = None
        self.cleaned_up = False

    async def initialize_services(self) -> None:
        return None

    async def cleanup_services(self) -> None:
        self.cleaned_up = True


# contract-test: direct surface=rest_api assertions=issue-reporting.submission.confirmed-and-durable
@pytest.mark.asyncio
async def test_report_is_archived_when_email_notification_is_disabled(monkeypatch):
    task = FakeTask()
    monkeypatch.setattr(
        issue_report_email_task,
        "_async_get_issue_report_user_stats",
        lambda *_args, **_kwargs: _resolved_stats(),
    )

    result = await issue_report_email_task._async_send_issue_report_email(
        task=task,
        admin_email="admin@example.invalid",
        issue_id="issue-123",
        issue_title="Audio send failed",
        console_logs="processing failed",
        timestamp="2026-09-20 13:52:40 UTC",
        send_email_notification=False,
    )

    assert result is True
    assert len(task.s3_service.uploads) == 1
    assert task.s3_service.uploads[0]["bucket_key"] == "issue_logs"
    assert task.directus_service.updates[0][0:2] == ("issues", "issue-123")
    assert "encrypted_issue_report_yaml_s3_key" in task.directus_service.updates[0][2]
    assert task.cleaned_up is True


async def _resolved_stats():
    return {
        "matched_user": False,
        "error": None,
        "chat_count": None,
        "user_messages_sent": None,
        "credits_purchased_total": None,
        "last_purchase_date": None,
        "last_purchase_credits": None,
    }
