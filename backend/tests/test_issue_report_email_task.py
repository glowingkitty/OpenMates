import importlib.util
import sys
import types
from pathlib import Path
from unittest.mock import AsyncMock
from unittest.mock import patch

import pytest


class _BaseServiceTaskStub:
    def __init__(self):
        self._secrets_manager = None
        self._directus_service = None
        self._encryption_service = None
        self._s3_service = None
        self._email_template_service = None
        self._invoice_ninja_service = None
        self._payment_service = None

    async def initialize_core_services(self):
        return None


class _CeleryAppStub:
    def task(self, *_args, **_kwargs):
        return lambda func: func


def _load_issue_report_task_module():
    tasks_stub = types.ModuleType("backend.core.api.app.tasks")
    tasks_stub.__path__ = []
    base_task_stub = types.ModuleType("backend.core.api.app.tasks.base_task")
    base_task_stub.BaseServiceTask = _BaseServiceTaskStub
    celery_config_stub = types.ModuleType("backend.core.api.app.tasks.celery_config")
    celery_config_stub.app = _CeleryAppStub()
    email_template_stub = types.ModuleType(
        "backend.core.api.app.services.email_template"
    )
    email_template_stub.EmailTemplateService = type("EmailTemplateService", (), {})
    s3_service_stub = types.ModuleType(
        "backend.core.api.app.services.s3.service"
    )
    s3_service_stub.S3UploadService = type("S3UploadService", (), {})

    module_path = (
        Path(__file__).parents[1]
        / "core/api/app/tasks/email_tasks/issue_report_email_task.py"
    )
    spec = importlib.util.spec_from_file_location(
        "_issue_report_email_task_under_test",
        module_path,
    )
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    with patch.dict(
        sys.modules,
        {
            "backend.core.api.app.tasks": tasks_stub,
            "backend.core.api.app.tasks.base_task": base_task_stub,
            "backend.core.api.app.tasks.celery_config": celery_config_stub,
            "backend.core.api.app.services.email_template": email_template_stub,
            "backend.core.api.app.services.s3.service": s3_service_stub,
        },
    ):
        spec.loader.exec_module(module)
    return module


report_task = _load_issue_report_task_module()


class _FakeStorage:
    def __init__(self, *, secrets_manager, directus_service):
        self.secrets_manager = secrets_manager
        self.directus_service = directus_service
        self.initialize = AsyncMock()


class _FakeEmailTemplates:
    def __init__(self, *, secrets_manager):
        self.secrets_manager = secrets_manager


# contract-test: supporting surface=rest_api assertions=issue-reporting.submission.confirmed-and-durable,notifications.delivery.email-enabled
@pytest.mark.asyncio
async def test_issue_report_task_initializes_only_required_services(monkeypatch):
    monkeypatch.setattr(report_task, "S3UploadService", _FakeStorage)
    monkeypatch.setattr(report_task, "EmailTemplateService", _FakeEmailTemplates)

    task = report_task.IssueReportServiceTask()
    task.initialize_core_services = AsyncMock()
    task._secrets_manager = object()
    task._directus_service = object()

    await task.initialize_services()
    await task.initialize_services()

    task.initialize_core_services.assert_awaited()
    task._s3_service.initialize.assert_awaited_once_with(configure_buckets=False)
    assert task._email_template_service.secrets_manager is task._secrets_manager
    assert task._invoice_ninja_service is None
    assert task._payment_service is None


# contract-test: supporting surface=rest_api assertions=issue-reporting.submission.confirmed-and-durable,issue-reporting.logs.authenticated-capture,notifications.delivery.email-enabled
@pytest.mark.asyncio
async def test_issue_report_persists_encrypted_yaml_before_sending_email():
    events: list[str] = []

    class _Encryption:
        async def encrypt_issue_report_data(self, value):
            events.append("encrypt")
            return f"encrypted:{len(value)}"

    class _Storage:
        async def upload_file(self, **kwargs):
            assert kwargs["bucket_key"] == "issue_logs"
            assert kwargs["content_type"] == "application/octet-stream"
            events.append("upload")

    class _Directus:
        async def get_user_by_hashed_email(self, _hashed_email):
            return False, None, "not found"

        async def update_item(self, collection, issue_id, data):
            assert collection == "issues"
            assert issue_id == "issue-123"
            if "encrypted_issue_report_yaml_s3_key" in data:
                assert data["encrypted_issue_report_yaml_s3_key"].startswith("encrypted:")
                events.append("update")
            else:
                assert data == {"processed": True}
                events.append("processed")

    class _EmailTemplates:
        async def send_email(self, **kwargs):
            assert kwargs["template"] in {
                "issue_report",
                "issue_report_confirmation",
            }
            events.append(f"email:{kwargs['template']}")
            return True

    class _Task:
        encryption_service = _Encryption()
        s3_service = _Storage()
        directus_service = _Directus()
        email_template_service = _EmailTemplates()
        initialize_services = AsyncMock()
        cleanup_services = AsyncMock()

    task = _Task()
    result = await report_task._async_send_issue_report_email(
        task=task,
        admin_email="support@example.test",
        issue_id="issue-123",
        issue_title="Report test",
        issue_description="A report description",
        timestamp="2026-09-21 12:00:00 UTC",
        console_logs="console marker",
        contact_email="reporter@example.test",
    )

    assert result is True
    task.initialize_services.assert_awaited_once()
    task.cleanup_services.assert_awaited_once()
    assert (
        events.index("upload")
        < events.index("update")
        < events.index("email:issue_report")
    )
    assert events.count("email:issue_report") == 1
    assert events.count("email:issue_report_confirmation") == 1
    assert events[-1] == "processed"


# contract-test: direct surface=rest_api assertions=issue-reporting.submission.confirmed-and-durable,issue-reporting.logs.authenticated-capture
@pytest.mark.asyncio
async def test_issue_report_persists_diagnostics_when_email_is_disabled():
    events: list[str] = []
    retained_yaml: list[str] = []

    class _Encryption:
        async def encrypt_issue_report_data(self, value):
            if "issue_report:" in value:
                retained_yaml.append(value)
            return f"encrypted:{len(value)}"

    class _Storage:
        async def upload_file(self, **kwargs):
            assert kwargs["bucket_key"] == "issue_logs"
            events.append("upload")

    class _Directus:
        async def get_user_by_hashed_email(self, _hashed_email):
            return False, None, "not found"

        async def update_item(self, collection, issue_id, data):
            assert collection == "issues"
            assert issue_id == "issue-no-email"
            if "encrypted_issue_report_yaml_s3_key" in data:
                events.append("yaml-key")
            else:
                assert data == {"processed": True}
                events.append("processed")

    class _EmailTemplates:
        async def send_email(self, **_kwargs):
            raise AssertionError("email must not be sent when notifications are disabled")

    class _Task:
        encryption_service = _Encryption()
        s3_service = _Storage()
        directus_service = _Directus()
        email_template_service = _EmailTemplates()
        initialize_services = AsyncMock()
        cleanup_services = AsyncMock()

    task = _Task()
    result = await report_task._async_send_issue_report_email(
        task=task,
        admin_email="support@example.test",
        issue_id="issue-no-email",
        issue_title="Admin report",
        timestamp="2026-09-21 13:00:00 UTC",
        console_logs="redacted console marker",
        indexeddb_report="encrypted metadata only",
        last_messages_html="<div>consented message context</div>",
        active_chat_sidebar_html="<div>active chat state</div>",
        runtime_debug_state='{"websocket_status":"connected"}',
        action_history="clicked report submit",
        picked_element_html="<button data-testid=broken />",
        trace_ids=["trace-123"],
        send_email_notification=False,
    )

    assert result is True
    assert events == ["upload", "yaml-key", "processed"]
    assert len(retained_yaml) == 1
    for marker in (
        "redacted console marker",
        "encrypted metadata only",
        "consented message context",
        "active chat state",
        "websocket_status",
        "clicked report submit",
        "data-testid=broken",
        "trace-123",
    ):
        assert marker in retained_yaml[0]


# contract-test: direct surface=rest_api assertions=issue-reporting.submission.confirmed-and-durable
@pytest.mark.asyncio
async def test_issue_report_retry_marks_processed_only_after_yaml_is_retained():
    events: list[str] = []

    class _Encryption:
        async def encrypt_issue_report_data(self, value):
            events.append("encrypt")
            return f"encrypted:{len(value)}"

    class _Storage:
        async def upload_file(self, **kwargs):
            assert kwargs["bucket_key"] == "issue_logs"
            events.append("upload")

    class _Directus:
        async def update_item(self, collection, issue_id, data):
            assert collection == "issues"
            assert issue_id == "issue-retry"
            if "encrypted_issue_report_yaml_s3_key" in data:
                events.append("yaml-key")
            else:
                assert data == {"processed": True}
                events.append("processed")

    class _Task:
        encryption_service = _Encryption()
        s3_service = _Storage()
        directus_service = _Directus()
        initialize_services = AsyncMock()
        cleanup_services = AsyncMock()

    task = _Task()
    result = await report_task._async_upload_issue_yaml_to_s3(
        task,
        "issue-retry",
        "issue_report:\n  title: retained after retry\n",
    )

    assert result is True
    assert events == ["encrypt", "upload", "encrypt", "yaml-key", "processed"]
    task.cleanup_services.assert_awaited_once()
