"""Code Run bundles retain trusted context across the real assistant dispatcher."""

from __future__ import annotations

import sys
from types import ModuleType, SimpleNamespace

import pytest

from backend.tests.runtime_import_stubs import install_code_route_import_stubs

install_code_route_import_stubs()

from backend.apps.ai.processing import skill_executor  # noqa: E402
from backend.apps.code.skills import run_code_skill  # noqa: E402
from backend.tests.test_base_app_dispatch_context import BaseApp  # noqa: E402


class Cache:
    def __init__(self):
        self.values = {}

    async def get(self, key):
        return self.values.get(key)

    async def set(self, key, value, ttl=None):
        self.values[key] = value
        return True

    async def get_user_by_id(self, user_id):
        assert user_id == "owner"
        return {"credits": 25}


@pytest.mark.parametrize(
    ("entry", "files"),
    [
        ("main.py", [
            {"path": "main.py", "code": "import sympy; import numpy; import matplotlib; import IPython"},
            {"path": "requirements.txt", "code": "sympy\nnumpy\nmatplotlib\nIPython\n"},
        ]),
        ("main.rs", [
            {"path": "main.rs", "code": 'mod numbers; fn main() { println!("{}", numbers::sum()); }'},
            {"path": "numbers.rs", "code": "pub fn sum() -> u32 { (1..=10).sum() }"},
        ]),
    ],
)
@pytest.mark.anyio
# contract-test: direct surface=rest_api assertions=code-run.assistant.auto-debug-bounded,code-run.execution.e2b-only,code-run.surface-parity
async def test_executor_preserves_code_run_bundle_and_server_context(monkeypatch, entry, files):
    cache, encryption, secrets, directus = Cache(), object(), object(), object()
    created, dispatched, requests = [], [], []
    definition = SimpleNamespace(
        id="run", name_translation_key="run", description_translation_key="run",
        full_model_reference=None, pricing=None, default_config={},
    )
    app = BaseApp.__new__(BaseApp)
    app.app_id = "code"
    app.celery_producer = None
    app.skill_classes = {"run": run_code_skill.RunCodeSkill}
    app._resolve_translation_key = lambda key: key
    app.get_skill_by_id = lambda skill_id: definition if skill_id == "run" else None

    class Registry:
        def has_app(self, app_id):
            return app_id == "code"

        def is_skill_available(self, app_id, skill_id):
            return (app_id, skill_id) == ("code", "run")

        def get_metadata(self, _app_id):
            return None

        async def dispatch_skill(self, app_id, skill_id, body):
            requests.append(body)
            return await app.dispatch_skill(skill_id, body)

    registry_module = ModuleType("backend.core.api.app.services.skill_registry")
    registry_module.get_global_registry = Registry
    monkeypatch.setitem(sys.modules, registry_module.__name__, registry_module)

    class EmbedService:
        def __init__(self, **kwargs):
            assert kwargs == {"cache_service": cache, "directus_service": directus, "encryption_service": encryption}

        async def create_code_embed_placeholder(self, **kwargs):
            assert kwargs["chat_id"] == "chat"
            assert kwargs["message_id"] == "message"
            assert kwargs["user_id"] == "owner"
            assert kwargs["user_vault_key_id"] == "trusted-vault-key"
            created.append(kwargs)
            return {"embed_id": f"embed-{kwargs['filename']}"}

        async def update_code_embed_content(self, **kwargs):
            assert kwargs["user_vault_key_id"] == "trusted-vault-key"
            assert kwargs["status"] == "finished"
            return True

    embed_module = ModuleType("backend.core.api.app.services.embed_service")
    embed_module.EmbedService = EmbedService
    monkeypatch.setitem(sys.modules, embed_module.__name__, embed_module)
    monkeypatch.setattr(run_code_skill, "create_directus_service", lambda **_kwargs: directus)

    async def start(**kwargs):
        dispatched.append(kwargs)
        assert kwargs["current_user"].id == "owner"
        assert kwargs["current_user"].vault_key_id == "trusted-vault-key"
        assert kwargs["current_user"].credits == 25
        assert kwargs["cache_service"] is cache
        assert kwargs["assistant_async_task"] is True
        assert kwargs["chat_id"] == "chat"
        assert kwargs["message_id"] == "message"
        assert kwargs["target_embed_id"] == f"embed-{entry}"
        assert kwargs["api_key_hash"] == "key-hash"
        assert kwargs["device_hash"] == "device-hash"
        assert kwargs["target_path"] == entry
        assert [file["path"] for file in kwargs["files"]] == [file["path"] for file in files]
        assert [file["content"] for file in kwargs["files"]] == [file["code"] for file in files]
        return SimpleNamespace(execution_id="execution", target_filename=entry,
                               files=[file["path"] for file in files], credits_per_minute=5)

    async def sanitize(result, _context):
        return result

    monkeypatch.setattr(run_code_skill, "start_code_run_for_assistant", start)
    monkeypatch.setattr(skill_executor, "sanitize_app_skill_output", sanitize)
    arguments = {
        "entry_path": entry, "files": files, "_user_vault_key_id": "trusted-vault-key",
        "_api_key_hash": "key-hash", "_device_hash": "device-hash",
        "_placeholder_embed_ids": ["placeholder-a", "placeholder-b"],
        "team_id": "forged-team", "_team_id": "forged-team",
    }
    results = await skill_executor.execute_skill_with_multiple_requests(
        "code", "run", arguments, chat_id="chat", message_id="message", user_id="owner",
        cache_service=cache, encryption_service=encryption, secrets_manager=secrets,
        team_id="trusted-team", max_retries=0,
    )
    assert len(requests) == len(dispatched) == 1
    assert "requests" not in requests[0]
    assert requests[0]["files"] == files
    assert requests[0]["_user_vault_key_id"] == "trusted-vault-key"
    assert requests[0]["_encryption_service"] is encryption
    assert requests[0]["_secrets_manager"] is secrets
    assert requests[0]["_team_id"] == "trusted-team"
    assert "team_id" not in requests[0]
    assert len(created) == len(files)
    assert results[0]["status"] == "processing"
    assert results[0]["execution_id"] == "execution"
    assert results[0]["created_embed_ids"] == [f"embed-{file['path']}" for file in files]
    assert arguments["_team_id"] == "forged-team"  # Caller's input stays unchanged.


@pytest.mark.anyio
# contract-test: supporting surface=rest_api assertions=app-skills.execution.registered-validated
async def test_code_bundle_fix_preserves_existing_legacy_search_batching(monkeypatch):
    captured = []

    async def execute(app_id, skill_id, arguments, *_args, **_kwargs):
        captured.append((app_id, skill_id, arguments))
        return {"status": "ok"}

    monkeypatch.setattr(skill_executor, "execute_skill", execute)
    result = await skill_executor.execute_skill_with_multiple_requests(
        "weather", "search", {"query": ["Berlin", "Hamburg"]}, max_retries=0,
    )
    assert result == [{"status": "ok"}]
    assert captured == [("weather", "search", {"requests": [{"query": "Berlin"}, {"query": "Hamburg"}]})]
