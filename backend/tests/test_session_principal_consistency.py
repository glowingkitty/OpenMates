"""Closed optional restriction; no authentication or request effects in this helper."""
import pytest
from fastapi import HTTPException
from starlette.requests import Request
from backend.core.api.app.utils.session_principal_consistency import require_expected_principal
OWNER="11111111-1111-4111-8111-111111111111"
OTHER="22222222-2222-4222-8222-222222222222"
# contract-test: direct surface=rest_api assertions=owner-consistency.header.restriction-only,owner-consistency.http.refuse-before-effect
@pytest.mark.parametrize("values", [[], [OWNER]])
def test_legacy_absence_and_exact_authenticated_owner_pass(values):
    request=Request({"type":"http","headers":[(b"x-openmates-expected-principal",v.encode()) for v in values]})
    require_expected_principal(request,OWNER)
# contract-test: direct surface=rest_api assertions=owner-consistency.header.restriction-only,owner-consistency.http.refuse-before-effect
@pytest.mark.parametrize("values", [[OTHER],["bad"],[OWNER,OWNER],["AAAAAAAA-AAAA-4AAA-8AAA-AAAAAAAAAAAA"],[OWNER+" "]])
def test_assertion_cannot_select_another_owner_or_ambiguous_header(values):
    request=Request({"type":"http","headers":[(b"x-openmates-expected-principal",v.encode()) for v in values]})
    with pytest.raises(HTTPException) as e:
        require_expected_principal(request,OWNER)
    assert e.value.status_code==403 and e.value.detail=={"error":"session_principal_mismatch"}


# contract-test: direct surface=rest_api assertions=owner-consistency.logout.no-cross-owner-clear
@pytest.mark.asyncio
async def test_independent_logout_dependency_never_runs_effect_for_cookie_switched_owner(monkeypatch):
    from types import SimpleNamespace
    from unittest.mock import AsyncMock
    from backend.tests.test_auth_dependencies import _stub_auth_dependency_imports
    _stub_auth_dependency_imports(monkeypatch)
    import importlib
    auth_dependencies = importlib.import_module("backend.core.api.app.routes.auth_routes.auth_dependencies")
    from backend.core.api.app.utils.session_principal_consistency import restrict_expected_cookie_principal
    authenticated = AsyncMock(return_value=SimpleNamespace(id=OTHER))
    monkeypatch.setattr(auth_dependencies, "get_current_user", authenticated)
    request = Request({"type":"http","headers":[(b"x-openmates-expected-principal",OWNER.encode()),(b"cookie",b"auth_refresh_token=cookie-b")],"app":SimpleNamespace(state=SimpleNamespace(directus_service=object(),cache_service=object()))})
    effects=[]
    with pytest.raises(HTTPException) as error:
        await restrict_expected_cookie_principal(request, SimpleNamespace())
        effects.append("revoke-and-clear-cookies")
    assert error.value.status_code==403 and effects==[]
    authenticated.assert_awaited_once()
    assert authenticated.call_args.kwargs["refresh_token"]=="cookie-b"
    # Legacy cookie-clearing path remains unmodified and needs no new auth call.
    authenticated.reset_mock()
    await restrict_expected_cookie_principal(Request({"type":"http","headers":[]}), SimpleNamespace())
    authenticated.assert_not_awaited()
    # A cookie that no longer authenticates names no owner: logout still clears it,
    # while other auth failures (e.g. 503) keep refusing before any effect.
    authenticated.side_effect = HTTPException(401, "expired")
    await restrict_expected_cookie_principal(request, SimpleNamespace())
    authenticated.side_effect = HTTPException(503, "unavailable")
    with pytest.raises(HTTPException) as unavailable:
        await restrict_expected_cookie_principal(request, SimpleNamespace())
    assert unavailable.value.status_code == 503


# contract-test: direct surface=rest_api assertions=owner-consistency.capabilities.advertised-when-live
def test_positive_server_capabilities_are_explicit_success_metadata_and_omitted_when_absent():
    import ast
    from pathlib import Path
    from pydantic import BaseModel, model_serializer
    from typing import Optional, List, Dict, Any
    from backend.core.api.app.utils.session_principal_consistency import OWNER_CONSISTENCY_CAPABILITIES
    root=Path(__file__).resolve().parents[2]
    schema=ast.parse((root/"backend/core/api/app/schemas/auth.py").read_text())
    node=next(n for n in schema.body if isinstance(n,ast.ClassDef) and n.name=="SessionResponse")
    scope={"BaseModel":BaseModel,"model_serializer":model_serializer,"Optional":Optional,"List":List,"Dict":Dict,"Any":Any,"UserResponse":Any,"PersonalMemoriesSnapshot":Any}
    exec(compile(ast.Module(body=[node],type_ignores=[]),"actual_session_response","exec"),scope)
    SessionResponse=scope["SessionResponse"]
    old=SessionResponse(success=False,message="synthetic").model_dump()
    assert "client_security_capabilities" not in old
    current=SessionResponse(success=True,message="synthetic",client_security_capabilities=list(OWNER_CONSISTENCY_CAPABILITIES)).model_dump()
    assert current["client_security_capabilities"]==["expected-principal-v1","ws-dual-principal-v1"]
    root=Path(__file__).resolve().parents[2]
    tree=ast.parse((root/"backend/core/api/app/routes/auth_routes/auth_session.py").read_text())
    calls=[node for node in ast.walk(tree) if isinstance(node,ast.Call) and isinstance(node.func,ast.Name) and node.func.id=="SessionResponse"]
    advertised=[node for node in calls if any(k.arg=="client_security_capabilities" for k in node.keywords)]
    assert len(advertised)==1
    assert any(k.arg=="success" and isinstance(k.value,ast.Constant) and k.value.value is True for k in advertised[0].keywords)

# contract-test: direct surface=rest_api assertions=owner-consistency.http.refuse-before-effect
@pytest.mark.asyncio
@pytest.mark.parametrize("expected,allowed", [(None,True),(OTHER,True),(OWNER,False)])
async def test_independent_sdk_api_key_helper_honors_assertion_without_new_authority(expected,allowed):
    import ast
    from pathlib import Path
    from types import SimpleNamespace
    from typing import Any
    from unittest.mock import AsyncMock
    root=Path(__file__).resolve().parents[2]
    tree=ast.parse((root/"backend/core/api/app/routes/sdk.py").read_text())
    node=next(n for n in tree.body if isinstance(n,ast.AsyncFunctionDef) and n.name=="_authenticate_sdk_request")
    service=SimpleNamespace(authenticate_api_key=AsyncMock(return_value={"user_id":OTHER}))
    scope={"Request":Request,"Any":Any,"HTTPException":HTTPException,"require_expected_principal":require_expected_principal,
           "get_api_key_auth_service":lambda _request:service,
           "DeviceNotApprovedError":type("DeviceNotApprovedError",(Exception,),{}),
           "ApiKeyNotFoundError":type("ApiKeyNotFoundError",(Exception,),{})}
    exec(compile(ast.Module(body=[node],type_ignores=[]),"actual_sdk_auth","exec"),scope)
    headers=[(b"authorization",b"Bearer synthetic-key")]
    if expected:
        headers.append((b"x-openmates-expected-principal",expected.encode()))
    request=Request({"type":"http","headers":headers})
    if allowed:
        assert await scope["_authenticate_sdk_request"](request)=={"user_id":OTHER}
    else:
        with pytest.raises(HTTPException) as error:
            await scope["_authenticate_sdk_request"](request)
        assert error.value.status_code==403
    service.authenticate_api_key.assert_awaited_once()
    # An owner assertion never substitutes for normal Bearer/session authority.
    service.authenticate_api_key.reset_mock()
    with pytest.raises(HTTPException) as error:
        await scope["_authenticate_sdk_request"](Request({"type":"http","headers":[(b"x-openmates-expected-principal",OWNER.encode())]}))
    assert error.value.status_code==401
    service.authenticate_api_key.assert_not_awaited()


def _actual_auth_entry(path, name, scope):
    """Execute the actual authored entry function with mocked IO dependencies."""
    import ast
    import __future__
    from pathlib import Path
    root = Path(__file__).resolve().parents[2]
    node = next(n for n in ast.parse((root / path).read_text()).body if isinstance(n, ast.AsyncFunctionDef) and n.name == name)
    exec(compile(ast.Module(body=[node], type_ignores=[]), "actual_auth_entry", "exec", flags=__future__.annotations.compiler_flag), scope)
    return scope[name]


# contract-test: direct surface=rest_api assertions=owner-consistency.http.refuse-before-effect
@pytest.mark.asyncio
@pytest.mark.parametrize("entry", ["apps", "sdk-bootstrap"])
async def test_independent_entries_use_central_key_restriction_before_business_effect(monkeypatch, entry):
    from types import SimpleNamespace
    from unittest.mock import AsyncMock
    from backend.core.api.app.utils import api_key_auth
    from backend.core.api.app.utils.session_principal_consistency import is_expected_principal_mismatch
    directus = SimpleNamespace(
        get_api_key_by_hash=AsyncMock(return_value={"id": "synthetic", "user_id": OTHER, "credential_version": 2, "full_access": True}),
        update_api_key_last_used=AsyncMock(return_value=True),
        get_encryption_key=AsyncMock(), get_user_profile=AsyncMock(),
    )
    service = api_key_auth.ApiKeyAuthService(directus, SimpleNamespace())
    service._check_and_register_device = AsyncMock()
    monkeypatch.setattr(api_key_auth, "get_api_key_auth_service", lambda _request: service)
    request = Request({"type": "http", "headers": [(b"authorization", b"Bearer sk-api-synthetic"), (b"x-openmates-expected-principal", OWNER.encode())]})
    common = {"HTTPException": HTTPException, "DeviceNotApprovedError": api_key_auth.DeviceNotApprovedError, "ApiKeyNotFoundError": api_key_auth.ApiKeyNotFoundError}
    if entry == "apps":
        common.update({"Depends": lambda *_: None, "Cookie": lambda *_args, **_kwargs: None, "get_cache_service": object(), "get_directus_service": object(), "is_expected_principal_mismatch": is_expected_principal_mismatch})
        function = _actual_auth_entry("backend/core/api/app/routes/apps_api.py", "get_session_or_api_key_info", common)
        call = function(request=request, response=SimpleNamespace(), cache_service=SimpleNamespace(), directus_service=directus, refresh_token=None)
    else:
        function = _actual_auth_entry("backend/core/api/app/routes/sdk.py", "create_sdk_session_for_api_key", common)
        call = function(request=request, sdk_name="rust", device_identity="synthetic", auth_service=service, directus_service=directus)
    with pytest.raises(HTTPException) as error:
        await call
    assert error.value.status_code == 403 and error.value.detail == {"error": "session_principal_mismatch"}
    service._check_and_register_device.assert_not_awaited()
    directus.update_api_key_last_used.assert_not_awaited()
    directus.get_encryption_key.assert_not_awaited()
    directus.get_user_profile.assert_not_awaited()


# contract-test: direct surface=rest_api assertions=owner-consistency.http.refuse-before-effect
@pytest.mark.asyncio
@pytest.mark.parametrize("terminal", [True, False])
async def test_apps_session_fallback_preserves_exact_mismatch_but_legacy_denial_still_falls_back(monkeypatch, terminal):
    from types import SimpleNamespace
    from unittest.mock import AsyncMock
    from backend.core.api.app.utils import api_key_auth
    from backend.core.api.app.utils.session_principal_consistency import is_expected_principal_mismatch
    service = SimpleNamespace(authenticate_api_key=AsyncMock(return_value={"user_id": OWNER}))
    monkeypatch.setattr(api_key_auth, "get_api_key_auth_service", lambda _request: service)
    failure = HTTPException(403, {"error": "session_principal_mismatch"}) if terminal else HTTPException(401, "Legacy invalid session")
    scope = {"Depends": lambda *_: None, "Cookie": lambda *_args, **_kwargs: None, "get_cache_service": object(), "get_directus_service": object(), "HTTPException": HTTPException, "get_current_user": AsyncMock(side_effect=failure), "is_expected_principal_mismatch": is_expected_principal_mismatch, "DeviceNotApprovedError": api_key_auth.DeviceNotApprovedError, "ApiKeyNotFoundError": api_key_auth.ApiKeyNotFoundError}
    function = _actual_auth_entry("backend/core/api/app/routes/apps_api.py", "get_session_or_api_key_info", scope)
    request = Request({"type": "http", "headers": [(b"authorization", b"Bearer sk-api-synthetic")]})
    call = function(request=request, response=SimpleNamespace(), cache_service=SimpleNamespace(), directus_service=SimpleNamespace(), refresh_token="synthetic-cookie")
    if terminal:
        with pytest.raises(HTTPException) as error:
            await call
        assert error.value is failure
        service.authenticate_api_key.assert_not_awaited()
    else:
        assert await call == {"user_id": OWNER}
        service.authenticate_api_key.assert_awaited_once()
