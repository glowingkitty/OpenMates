# Focused REST replay authorization regressions, with no external execution.
# contract-test-file: infrastructure
# Tests use synthetic server profiles and an ephemeral signing secret only.
# They retain scope/worker boundaries while covering cache-miss profile lookup,
# foreign/stale signatures and all non-replay modes. No app assertions change.
# Architecture: docs/architecture/live-mock-testing.md.

import asyncio
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

from backend.shared.python_utils.rest_test_replay import prepare_rest_replay_messages
from backend.shared.testing.mock_context import detect_live_marker, sign_live_marker


@pytest.fixture
def boundary(monkeypatch):
    monkeypatch.setenv('SERVER_ENVIRONMENT', 'development')
    monkeypatch.setenv('MOCK_EXTERNAL_APIS', 'true')
    monkeypatch.setenv('DAILY_AI_TEST_CONTEXT_SECRET', 'offline-test-secret')
    monkeypatch.setenv('OPENMATES_TEST_ACCOUNT_EMAIL', 'runner@example.test')
    return SimpleNamespace(get_user_by_id=AsyncMock(return_value={'email': 'runner@example.test'}))


def prepare(cache, text='hello <<<TEST_LIVE_MOCK:web_search_cli>>>', **kwargs):
    return asyncio.run(prepare_rest_replay_messages([{'role': 'user', 'content': text}], 'owner', cache, **kwargs))


def test_signed_replay_is_worker_verifiable_and_input_unchanged(boundary):
    result=prepare(boundary)
    marker=detect_live_marker(result[0]['content'], 'owner')
    assert marker.mode=='mock' and marker.group_id=='web_search_cli'
    assert detect_live_marker(result[0]['content'], 'foreign') is None
    boundary.get_user_by_id.assert_awaited_once_with('owner')


@pytest.mark.parametrize('setting,value', [('SERVER_ENVIRONMENT','production'),('MOCK_EXTERNAL_APIS','false')])
def test_disabled_rejected_before_profile_lookup(boundary, monkeypatch, setting, value):
    monkeypatch.setenv(setting,value)
    with pytest.raises(ValueError,match='disabled'):prepare(boundary)
    boundary.get_user_by_id.assert_not_awaited()


def test_ordinary_account_rejected(boundary):
    boundary.get_user_by_id.return_value={'email':'ordinary@example.test'}
    with pytest.raises(ValueError,match='configured'):prepare(boundary)


@pytest.mark.parametrize('marker', ['<<<TEST_LIVE_REAL:daily_canary_20260908>>>','<<<TEST_LIVE_RECORD:web_search_cli:run>>>','<<<TEST_LIVE_MOCK:web_search_cli:run>>>','<<<TEST_LIVE_MOCK:bad group>>>'])
def test_other_modes_and_malformed_markers_rejected(boundary,marker):
    with pytest.raises(ValueError):prepare(boundary,'hello '+marker)


@pytest.mark.parametrize('owner,ttl', [('foreign',600),('owner',-10)])
def test_foreign_or_expired_signature_is_not_resigned(boundary,owner,ttl):
    signed=sign_live_marker('<<<TEST_LIVE_MOCK:web_search_cli>>>',owner,is_allowlisted_test_account=True,ttl_seconds=ttl)
    with pytest.raises(ValueError,match='signature'):prepare(boundary,'hello '+signed)


def test_cold_profile_comes_from_authenticated_user_lookup(boundary):
    boundary.get_user_by_id.return_value=None
    cms=SimpleNamespace(get_user_profile=AsyncMock(return_value=(True,{'email':'runner@example.test'},None)))
    assert detect_live_marker(prepare(boundary,directus_service=cms)[0]['content'],'owner')
    cms.get_user_profile.assert_awaited_once_with('owner')


def test_plain_request_never_reads_profile(boundary):
    assert prepare(boundary,'hello')==[{'role':'user','content':'hello'}]
    boundary.get_user_by_id.assert_not_awaited()


def test_history_and_assistant_markers_cannot_activate_replay(boundary):
    for messages in [ [{'role':'assistant','content':'<<<TEST_LIVE_MOCK:web_search_cli>>>'}], [{'role':'user','content':'<<<TEST_LIVE_MOCK:web_search_cli>>>'},{'role':'user','content':'next'}] ]:
        with pytest.raises(ValueError):asyncio.run(prepare_rest_replay_messages(messages,'owner',boundary))


@pytest.mark.parametrize('route', ['sdk', 'apps'])
@pytest.mark.asyncio
async def test_actual_rest_submission_signs_before_dispatch(boundary, monkeypatch, route):
    from backend.core.api.app.routes import sdk, apps_api
    from backend.core.api.app.services import skill_registry
    from backend.shared.python_utils.app_skill_output_safety import is_central_app_skill_dispatch

    captured=[]
    class Registry:
        async def dispatch_skill(self, app, skill, payload):
            captured.append(payload)
            if route=='apps':assert is_central_app_skill_dispatch()
            return {'content':'fixture result'}
        def get_metadata(self, app):return SimpleNamespace(skills=[])
    monkeypatch.setattr(skill_registry,'get_global_registry',lambda:Registry())
    identity={'user_id':'owner','api_key_hash':'key-hash','api_key_metadata':{'full_access':True}}
    text='hello <<<TEST_LIVE_MOCK:web_search_cli>>>'
    if route=='sdk':
        monkeypatch.setattr(sdk,'_authenticate_sdk_request',AsyncMock(return_value=identity))
        request=SimpleNamespace(app=SimpleNamespace(state=SimpleNamespace(cache_service=boundary,directus_service=None)))
        await sdk.create_sdk_chat(request,sdk.SdkChatCreateRequest(message=text,save_to_account=False))
    else:
        # Exposure configuration and output safety have dedicated route tests;
        # observe their execution here rather than exercising external services.
        exposure=[]
        monkeypatch.setattr(apps_api,'assert_rest_skill_execution_allowed',lambda *args:exposure.append(args))
        safety=AsyncMock(return_value={'content':'fixture result'})
        monkeypatch.setattr(apps_api,'sanitize_app_skill_output',safety)
        await apps_api.call_app_skill('ai','ask',{'messages':[{'role':'user','content':text}]},{},identity,cache_service=boundary)
        assert exposure and safety.await_count==1
    assert len(captured)==1
    assert captured[0]['_user_id']=='owner'
    assert detect_live_marker(captured[0]['messages'][-1]['content'],'owner').mode=='mock'
