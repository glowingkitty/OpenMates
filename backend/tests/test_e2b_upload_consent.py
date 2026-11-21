"""E2B upload consent gates: nothing is queued without the account's allowed decision."""

from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest
from fastapi import HTTPException

from backend.tests.runtime_import_stubs import install_code_route_import_stubs

install_code_route_import_stubs()

from backend.core.api.app.routes import code_execution  # noqa: E402
from backend.core.api.app.routes import e2b_upload_consent as consent_routes  # noqa: E402
from backend.core.api.app.routes.application_preview import (  # noqa: E402
    ApplicationPreviewStartRequest,
    create_application_preview_session_and_dispatch,
)
from backend.core.api.app.services import e2b_upload_consent as consent  # noqa: E402
from backend.tests.test_application_preview_config import FakeCache, _user  # noqa: E402

FIELD, AT = consent.CONSENT_FIELD, consent.CONSENT_AT_FIELD


class FakeDirectus:
    def __init__(self, fields=None):
        self.fields = dict(fields or {})
        self.writes = []

    async def get_user_fields_direct(self, user_id, fields, *, no_cache=False):
        assert no_cache is True
        return {name: self.fields.get(name) for name in fields}

    async def update_user(self, user_id, data):
        self.writes.append(data)
        self.fields.update(data)
        return True


def _code_run_kwargs(directus):
    return dict(
        current_user=SimpleNamespace(id="owner", credits=25),
        cache_service=SimpleNamespace(client=AsyncMock(return_value=object())()),
        files=[{"path": "main.py", "content": "print(1)", "language": "python", "is_target": True}],
        target_path="main.py", enable_internet=False, chat_id=None, target_embed_id=None,
        message_id=None, dependency_installs=[], directus_service=directus,
    )


def _wire_code_run(monkeypatch):
    queued = []
    monkeypatch.setattr(code_execution, "_try_add_active_run", AsyncMock(return_value=True))
    monkeypatch.setattr(code_execution, "_try_reserve_provider_run", AsyncMock(return_value=None))
    monkeypatch.setattr(code_execution, "_create_execution_record", AsyncMock())
    # Own stand-in: other suites may replace code_execution.celery_app with a fake lacking send_task.
    monkeypatch.setattr(code_execution, "celery_app", SimpleNamespace(send_task=lambda *a, **k: queued.append(a)))
    return queued


@pytest.mark.parametrize(
    ("fields", "code"),
    [({}, "e2b_consent_required"), ({FIELD: "declined", AT: 5}, "e2b_consent_declined")],
)
@pytest.mark.anyio
# contract-test: direct surface=rest_api assertions=code-run.e2b.upload-consent
async def test_code_run_refused_without_allowed_decision_and_nothing_queued(monkeypatch, fields, code):
    queued = _wire_code_run(monkeypatch)
    with pytest.raises(HTTPException) as err:
        await code_execution.start_code_run_execution(**_code_run_kwargs(FakeDirectus(fields)))
    assert err.value.status_code == 403
    assert err.value.detail == {"code": code}
    assert queued == []
    code_execution._try_add_active_run.assert_not_called()


@pytest.mark.anyio
# contract-test: direct surface=rest_api assertions=code-run.e2b.upload-consent
async def test_code_run_proceeds_after_allowed(monkeypatch):
    queued = _wire_code_run(monkeypatch)
    result = await code_execution.start_code_run_execution(
        **_code_run_kwargs(FakeDirectus({FIELD: "allowed", AT: 5}))
    )
    assert result.status == "queued"
    assert len(queued) == 1


@pytest.mark.anyio
# contract-test: direct surface=rest_api assertions=code-run.e2b.upload-consent
async def test_older_version_decision_does_not_carry_over():
    directus = FakeDirectus({"e2b_upload_consent_v0": "allowed", "e2b_upload_consent_v0_at": 5})
    assert consent.CONSENT_FIELD != "e2b_upload_consent_v0"
    with pytest.raises(HTTPException) as err:
        await consent.require_e2b_upload_consent("owner", directus)
    assert err.value.detail == {"code": "e2b_consent_required"}


@pytest.mark.anyio
# contract-test: direct surface=rest_api assertions=code-run.e2b.upload-consent
async def test_consent_endpoints_get_and_put_are_owner_scoped():
    directus = FakeDirectus()
    user = SimpleNamespace(id="owner")
    unset = await consent_routes.get_e2b_upload_consent.__wrapped__(None, user, directus)
    assert unset == {"decision": None, "decided_at": None, "version": 1}
    body = consent_routes.E2bUploadConsentBody(decision="declined")
    stored = await consent_routes.put_e2b_upload_consent.__wrapped__(None, body, user, directus)
    assert stored["decision"] == "declined" and type(stored["decided_at"]) is int
    assert stored["version"] == consent.E2B_UPLOAD_CONSENT_VERSION
    assert set(directus.writes[0]) == {FIELD, AT}
    with pytest.raises(ValueError):
        consent_routes.E2bUploadConsentBody(decision="maybe")


@pytest.mark.anyio
# contract-test: direct surface=rest_api assertions=code-run.e2b.upload-consent
async def test_allow_flag_records_allowed_only_when_no_decision_exists():
    fresh = FakeDirectus()
    assert (await consent.record_allowed_if_unset("owner", fresh))["decision"] == "allowed"
    declined = FakeDirectus({FIELD: "declined", AT: 5})
    assert (await consent.record_allowed_if_unset("owner", declined))["decision"] == "declined"
    assert declined.writes == []


@pytest.mark.anyio
# contract-test: direct surface=rest_api assertions=code-run.e2b.upload-consent
async def test_skill_route_flag_is_accepted_and_defaults_off():
    assert code_execution.CodeRunAppSkillRequest(requests=[{"mode": "direct"}]).allow_e2b_upload is False
    assert code_execution.CodeRunAppSkillRequest(requests=[{}], allow_e2b_upload=True).allow_e2b_upload is True


@pytest.mark.parametrize(
    ("fields", "code"),
    [({}, "e2b_consent_required"), ({FIELD: "declined", AT: 5}, "e2b_consent_declined")],
)
@pytest.mark.anyio
# contract-test: direct surface=rest_api assertions=code-run.e2b.upload-consent
async def test_application_preview_start_gated_before_any_task(fields, code):
    cache, sent = FakeCache(), []
    kwargs = dict(
        cache_service=cache, session_id="session-1", application_embed_id="app-embed-1",
        body=ApplicationPreviewStartRequest(chat_id="chat-1"), current_user=_user("alice-user"),
        preview_origin="https://openmatesusercontent.org", worker_payload={},
        task_sender=lambda *a, **k: sent.append(a), now=2_000.0,
    )
    with pytest.raises(HTTPException) as err:
        await create_application_preview_session_and_dispatch(**kwargs, directus_service=FakeDirectus(fields))
    assert err.value.status_code == 403 and err.value.detail == {"code": code}
    assert sent == []
    response = await create_application_preview_session_and_dispatch(
        **kwargs, directus_service=FakeDirectus({FIELD: "allowed", AT: 5})
    )
    assert response.status == "queued" and len(sent) == 1
