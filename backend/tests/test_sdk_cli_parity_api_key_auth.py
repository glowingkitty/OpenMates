"""SDK CLI parity API-key authorization contracts.

Purpose: verify SDK parity route shells enforce API-key scope metadata.
Architecture: docs/specs/sdk-cli-parity-v1/spec.yml.
Security: API-key routes must deny missing scopes before product work runs.
Scope: focused authorization tests; product route wiring is tested per surface.
"""

import sys
from types import SimpleNamespace

import pytest
from fastapi import HTTPException

from backend.core.api.app.routes import sdk as sdk_routes
from backend.core.api.app.routes.sdk import _dispatch_sdk_surface, _require_sdk_scope_for_surface


class _FakeDirectusService:
    def __init__(self):
        self.chat = SimpleNamespace(
            get_new_chat_suggestions_for_user=self.get_new_chat_suggestions_for_user,
            check_chat_ownership=self.check_chat_ownership,
            get_chat_metadata=self.get_chat_metadata,
            get_all_messages_for_chat=self.get_all_messages_for_chat,
        )
        self.embed = SimpleNamespace(
            get_embeds_by_hashed_chat_id=self.get_embeds_by_hashed_chat_id,
            get_embed_keys_by_hashed_chat_id=self.get_embed_keys_by_hashed_chat_id,
        )
        self.suggestion_queries = []
        self.ownership_allowed = True

    async def get_user_profile(self, user_id):
        return True, {
            "id": user_id,
            "user_id": user_id,
            "username": "sdk-user",
            "vault_key_id": "vault-key-1",
            "credits": 25,
            "language": "en",
            "darkmode": False,
        }, "ok"

    async def get_new_chat_suggestions_for_user(self, hashed_user_id, limit=50):
        self.suggestion_queries.append((hashed_user_id, limit))
        return [{"id": "suggestion-1"}, {"id": "suggestion-2"}]

    async def check_chat_ownership(self, chat_id, user_id):
        return self.ownership_allowed and chat_id == "chat-1" and user_id == "user-1"

    async def get_chat_metadata(self, chat_id):
        if chat_id != "chat-1":
            return None
        return {"id": "chat-1", "encrypted_title": "cipher-title", "encrypted_chat_key": "cipher-key"}

    async def get_all_messages_for_chat(self, chat_id, decrypt_content=False):
        assert decrypt_content is False
        return [{"id": "message-1", "encrypted_content": "cipher-content"}]

    async def get_embeds_by_hashed_chat_id(self, hashed_chat_id):
        assert len(hashed_chat_id) == 64
        return [{"embed_id": "embed-1", "encrypted_content": "cipher-embed"}]

    async def get_embed_keys_by_hashed_chat_id(self, hashed_chat_id):
        assert len(hashed_chat_id) == 64
        return [{"hashed_embed_id": "hash-embed-1", "key_type": "master", "encrypted_embed_key": "cipher-key"}]


class _FakeCacheService:
    def __init__(self):
        self.suggestions = None
        self.cached_suggestions = None

    async def get_new_chat_suggestions(self, hashed_user_id):
        return self.suggestions

    async def set_new_chat_suggestions(self, hashed_user_id, suggestions, ttl=600):
        self.cached_suggestions = (hashed_user_id, suggestions, ttl)
        return True


class _FakeRequest:
    def __init__(self, method="GET", query_params=None):
        directus_service = _FakeDirectusService()
        cache_service = _FakeCacheService()
        self.method = method
        self.query_params = query_params or {}
        self.app = SimpleNamespace(
            state=SimpleNamespace(
                directus_service=directus_service,
                cache_service=cache_service,
                encryption_service=SimpleNamespace(),
            )
        )


def _api_key_info(metadata):
    return {"api_key_metadata": metadata}


def test_full_access_allows_sdk_parity_surfaces():
    required_scope = _require_sdk_scope_for_surface(
        _api_key_info({"full_access": True}),
        "billing",
        "GET",
    )

    assert required_scope == "billing:read"


def test_selected_scope_allows_matching_sdk_surface():
    required_scope = _require_sdk_scope_for_surface(
        _api_key_info(
            {
                "full_access": False,
                "scopes": {"notifications": ["notification:write"]},
            }
        ),
        "notifications",
        "POST",
    )

    assert required_scope == "notification:write"


def test_missing_scope_returns_typed_error_detail():
    with pytest.raises(HTTPException) as exc:
        _require_sdk_scope_for_surface(
            _api_key_info(
                {
                    "full_access": False,
                    "scopes": {"billing": ["billing:read"]},
                }
            ),
            "billing",
            "POST",
        )

    assert exc.value.status_code == 403
    assert exc.value.detail == {
        "error": "missing_scope",
        "missing_scope": "billing:write",
    }


def test_chat_parity_surface_uses_existing_chat_scope_names():
    assert (
        _require_sdk_scope_for_surface(
            _api_key_info(
                {
                    "full_access": False,
                    "scopes": {"chat": ["chat:read_existing", "chat:create_saved"]},
                }
            ),
            "chats",
            "GET",
        )
        == "chat:read_existing"
    )
    assert (
        _require_sdk_scope_for_surface(
            _api_key_info(
                {
                    "full_access": False,
                    "scopes": {"chat": ["chat:read_existing", "chat:create_saved"]},
                }
            ),
            "chats",
            "DELETE",
        )
        == "chat:create_saved"
    )


@pytest.mark.asyncio
async def test_sdk_dispatch_docs_search_uses_existing_docs_route(monkeypatch):
    async def fake_search_docs(query):
        return [{"slug": "sdk", "title": query}]

    fake_docs_routes = SimpleNamespace(search_docs=fake_search_docs)
    monkeypatch.setitem(sys.modules, "backend.core.api.app.routes.docs_routes", fake_docs_routes)

    result = await _dispatch_sdk_surface(
        _FakeRequest(query_params={"q": "sdk parity"}),
        {"user_id": "user-1"},
        "docs",
        "search",
        None,
    )

    assert result == {"results": [{"slug": "sdk", "title": "sdk parity"}]}


@pytest.mark.asyncio
async def test_sdk_dispatch_docs_search_rejects_overlong_query():
    with pytest.raises(HTTPException) as exc:
        await _dispatch_sdk_surface(
            _FakeRequest(query_params={"q": "x" * 201}),
            {"user_id": "user-1"},
            "docs",
            "search",
            None,
        )

    assert exc.value.status_code == 400
    assert exc.value.detail == "Docs search query must be 200 characters or fewer"


@pytest.mark.asyncio
async def test_sdk_dispatch_settings_language_reuses_settings_route(monkeypatch):
    async def fake_update_language(request, request_data, current_user, directus_service, cache_service):
        assert current_user.id == "user-1"
        assert request_data.language == "de"
        return {"success": True}

    fake_settings_routes = SimpleNamespace(update_user_language=fake_update_language)
    monkeypatch.setitem(sys.modules, "backend.core.api.app.routes.settings", fake_settings_routes)

    result = await _dispatch_sdk_surface(
        _FakeRequest(method="POST"),
        {"user_id": "user-1"},
        "settings",
        "language",
        {"language": "de"},
    )

    assert result == {"success": True}


@pytest.mark.asyncio
async def test_sdk_dispatch_learning_mode_accepts_sdk_enable_alias(monkeypatch):
    class LearningModeActivateRequest:
        def __init__(self, passcode, age_group):
            self.passcode = passcode
            self.age_group = age_group

    class LearningModeDeactivateRequest:
        def __init__(self, passcode):
            self.passcode = passcode

    async def fake_activate(request, request_data, current_user, cache_service, directus_service):
        assert request_data.age_group == "teen"
        assert request_data.passcode == "1234"
        return SimpleNamespace(model_dump=lambda: {"enabled": True, "age_group": "teen"})

    fake_learning_mode = SimpleNamespace(
        LearningModeActivateRequest=LearningModeActivateRequest,
        LearningModeDeactivateRequest=LearningModeDeactivateRequest,
        activate_learning_mode=fake_activate,
        deactivate_learning_mode=None,
        get_learning_mode_status=None,
    )
    monkeypatch.setitem(sys.modules, "backend.core.api.app.routes.learning_mode", fake_learning_mode)

    result = await _dispatch_sdk_surface(
        _FakeRequest(method="POST"),
        {"user_id": "user-1"},
        "learning-mode",
        "enable",
        {"age_group": "teen", "passcode": "1234"},
    )

    assert result == {"enabled": True, "age_group": "teen"}


@pytest.mark.asyncio
async def test_sdk_dispatch_new_chat_suggestions_falls_back_to_database():
    request = _FakeRequest(query_params={"limit": "1"})

    result = await _dispatch_sdk_surface(
        request,
        {"user_id": "user-1"},
        "new-chat-suggestions",
        "",
        None,
    )

    assert result == {"suggestions": [{"id": "suggestion-1"}], "limit": 1}
    assert request.app.state.directus_service.suggestion_queries
    assert request.app.state.cache_service.cached_suggestions is not None


@pytest.mark.asyncio
async def test_sdk_dispatch_rejects_unbounded_new_chat_suggestions_limit():
    with pytest.raises(HTTPException) as exc:
        await _dispatch_sdk_surface(
            _FakeRequest(query_params={"limit": "100000"}),
            {"user_id": "user-1"},
            "new-chat-suggestions",
            "",
            None,
        )

    assert exc.value.status_code == 400
    assert exc.value.detail == "limit must be between 1 and 50"


@pytest.mark.asyncio
async def test_sdk_account_export_requires_chat_and_billing_scopes():
    with pytest.raises(HTTPException) as exc:
        await _dispatch_sdk_surface(
            _FakeRequest(),
            {
                "user_id": "user-1",
                "api_key_metadata": {
                    "full_access": False,
                    "scopes": {"account": ["account:read"]},
                },
            },
            "account",
            "export/data",
            None,
        )

    assert exc.value.status_code == 403
    assert exc.value.detail == {"error": "missing_scope", "missing_scope": "chat:read_existing"}


@pytest.mark.asyncio
async def test_sdk_dispatch_reminders_list_reuses_settings_route(monkeypatch):
    async def fake_get_reminders(
        request,
        include_recent_fired,
        upcoming_hours,
        recent_hours,
        current_user,
        cache_service,
        encryption_service,
    ):
        assert include_recent_fired is True
        assert upcoming_hours == 24
        assert recent_hours == 6
        assert current_user.id == "user-1"
        return {"success": True, "reminders": []}

    fake_settings_routes = SimpleNamespace(get_active_reminders=fake_get_reminders)
    monkeypatch.setitem(sys.modules, "backend.core.api.app.routes.settings", fake_settings_routes)

    result = await _dispatch_sdk_surface(
        _FakeRequest(method="GET", query_params={"include_recent_fired": "true", "upcoming_hours": "24", "recent_hours": "6"}),
        {"user_id": "user-1"},
        "reminders",
        "",
        None,
    )

    assert result == {"success": True, "reminders": []}


@pytest.mark.asyncio
async def test_sdk_dispatch_billing_invoices_reuses_billing_overview(monkeypatch):
    async def fake_get_billing_overview(request, current_user, directus_service, cache_service, encryption_service):
        assert current_user.id == "user-1"
        return SimpleNamespace(invoices=[SimpleNamespace(model_dump=lambda: {"id": "invoice-1", "amount": "10.00"})])

    fake_settings_routes = SimpleNamespace(get_billing_overview=fake_get_billing_overview)
    monkeypatch.setitem(sys.modules, "backend.core.api.app.routes.settings", fake_settings_routes)

    result = await _dispatch_sdk_surface(
        _FakeRequest(method="GET"),
        {"user_id": "user-1"},
        "billing",
        "invoices",
        None,
    )

    assert result == {"invoices": [{"id": "invoice-1", "amount": "10.00"}]}


@pytest.mark.asyncio
@pytest.mark.parametrize("path,method", [("usage/daily", "GET"), ("usage/summaries", "GET"), ("auto-topup/low-balance", "POST")])
async def test_sdk_billing_unaudited_payment_routes_stay_unimplemented(monkeypatch, path, method):
    async def fake_authenticate(request):
        return {"user_id": "user-1", "api_key_metadata": {"full_access": True}}

    monkeypatch.setattr(sdk_routes, "_authenticate_sdk_request", fake_authenticate)

    with pytest.raises(HTTPException) as exc:
        await sdk_routes._sdk_parity_placeholder(
            _FakeRequest(method=method),
            "billing",
            path,
            {} if method == "POST" else None,
        )

    assert exc.value.status_code == 501
    assert exc.value.detail["error"] == "sdk_surface_not_implemented"
    assert exc.value.detail["surface"] == "billing"
    assert exc.value.detail["path"] == path


@pytest.mark.asyncio
async def test_sdk_load_chat_returns_encrypted_chat_and_messages_after_ownership(monkeypatch):
    async def fake_authenticate(request):
        return {"user_id": "user-1", "api_key_metadata": {"full_access": True}}

    monkeypatch.setattr(sdk_routes, "_authenticate_sdk_request", fake_authenticate)
    request = _FakeRequest(method="GET")

    result = await sdk_routes.load_sdk_chat(request, "chat-1")

    assert result == {
        "chat": {"id": "chat-1", "encrypted_title": "cipher-title", "encrypted_chat_key": "cipher-key"},
        "messages": [{"id": "message-1", "encrypted_content": "cipher-content"}],
        "embeds": [{"embed_id": "embed-1", "encrypted_content": "cipher-embed"}],
        "embed_keys": [{"hashed_embed_id": "hash-embed-1", "key_type": "master", "encrypted_embed_key": "cipher-key"}],
    }


@pytest.mark.asyncio
async def test_sdk_load_chat_hides_chats_owned_by_other_users(monkeypatch):
    async def fake_authenticate(request):
        return {"user_id": "user-2", "api_key_metadata": {"full_access": True}}

    monkeypatch.setattr(sdk_routes, "_authenticate_sdk_request", fake_authenticate)

    with pytest.raises(HTTPException) as exc:
        await sdk_routes.load_sdk_chat(_FakeRequest(method="GET"), "chat-1")

    assert exc.value.status_code == 404
