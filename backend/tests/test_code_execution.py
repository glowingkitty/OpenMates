# backend/tests/test_code_execution.py
#
# Regression tests for the web-app Code Run collector.
# Code Run must use server-readable Redis/Vault cache for recent chats, while
# Directus remains client-encrypted storage and is never decrypted with Vault.
# Older chats can retry with code decrypted on the authenticated client.

from __future__ import annotations

import hashlib
import base64
import json
from types import SimpleNamespace

import pytest
from fastapi import HTTPException
from toon_format import encode

from backend.apps.code.tasks.run_code_task import RUN_CREDITS_PER_MINUTE as TASK_RUN_CREDITS_PER_MINUTE
from backend.apps.code.tasks.run_code_task import _charge_run_credits
from backend.core.api.app.routes.code_execution import (
    CLIENT_CONTENT_REQUIRED_CODE,
    CodeRunClientAttachment,
    CodeRunDependencyInstall as ApiCodeRunDependencyInstall,
    CodeRunClientFile,
    RUN_CREDITS_PER_MINUTE as ROUTE_RUN_CREDITS_PER_MINUTE,
    _collect_code_files,
    _dependency_installs_from_install_snippets,
    _execution_key,
    _infer_import_packages,
    _looks_like_secret,
    _merge_dependency_installs,
    _safe_filename,
    _validate_dependency_manifest,
    cancel_code_run,
)
from backend.core.api.app.routes.handlers.websocket_handlers.code_run_output_handlers import (
    _impl_upsert,
    code_run_output_cache_key,
)
from backend.core.api.app.services.embed_service import EmbedService


CHAT_ID = "chat-1"
TARGET_EMBED_ID = "embed-target"
USER_ID = "user-1"
USER_HASH = hashlib.sha256(USER_ID.encode()).hexdigest()
CHAT_HASH = hashlib.sha256(CHAT_ID.encode()).hexdigest()
MESSAGE_ID = "message-1"


class FakeRedis:
    def __init__(self, embeds: dict[str, dict]):
        self.embeds = embeds
        self.values: dict[str, bytes] = {}

    async def get(self, key: str):
        if key in self.values:
            return self.values[key]
        embed_id = key.removeprefix("embed:")
        embed = self.embeds.get(embed_id)
        return json.dumps(embed).encode() if embed else None

    async def set(self, key: str, value: str, ex: int | None = None):
        self.values[key] = value.encode()


class FakeCache:
    def __init__(self, embed_ids: list[str], embeds: dict[str, dict]):
        self.embed_ids = embed_ids
        self.embeds = embeds
        self.redis = FakeRedis(embeds)

    @property
    def client(self):
        async def _client():
            return self.redis

        return _client()

    async def get_chat_embed_ids(self, chat_id: str) -> list[str]:
        return self.embed_ids if chat_id == CHAT_ID else []

    async def get_embed_from_cache(self, embed_id: str):
        return self.embeds.get(embed_id)

    async def publish_event(self, channel: str, payload: dict):
        return None


class FakeDirectusEmbed:
    def __init__(self, embeds: dict[str, dict]):
        self.embeds = embeds

    async def get_embed_by_id(self, embed_id: str):
        return self.embeds.get(embed_id)


class FakeDirectus:
    def __init__(self, embeds: dict[str, dict]):
        self.embed = FakeDirectusEmbed(embeds)


class FakeCodeRunDirectusChat:
    async def check_chat_ownership(self, chat_id: str, user_id: str) -> bool:
        return chat_id == CHAT_ID and user_id == USER_ID

    async def get_chat_metadata(self, chat_id: str):
        return {"id": chat_id}


class FakeCodeRunDirectus(FakeDirectus):
    def __init__(self, embeds: dict[str, dict]):
        super().__init__(embeds)
        self.chat = FakeCodeRunDirectusChat()
        self.items: dict[str, dict] = {}

    async def get_items(self, collection: str, params: dict, admin_required: bool = False):
        return []

    async def create_item(self, collection: str, row: dict, admin_required: bool = False):
        self.items[row["id"]] = row
        return row

    async def update_item(self, collection: str, item_id: str, row: dict):
        self.items[item_id] = {**self.items.get(item_id, {}), **row}
        return self.items[item_id]


class FakeManager:
    def __init__(self):
        self.personal_messages: list[dict] = []
        self.broadcasts: list[dict] = []

    async def send_personal_message(self, message: dict, user_id: str, device_fingerprint_hash: str):
        self.personal_messages.append(message)

    async def broadcast_to_user(self, message: dict, user_id: str, exclude_device_hash: str | None = None):
        self.broadcasts.append(message)


class FakeEncryption:
    async def encrypt_with_user_key(self, plaintext: str, key_id: str):
        return f"vault:{plaintext}", None

    async def decrypt_with_user_key(self, ciphertext: str, key_id: str):
        if ciphertext.startswith("vault:"):
            return ciphertext.removeprefix("vault:")
        raise AssertionError("Code Run must not try to Vault-decrypt Directus client ciphertext")


def _user():
    return SimpleNamespace(id=USER_ID, vault_key_id="vault-key")


def _metadata(encrypted_content: str = "client-ciphertext") -> dict:
    return {
        "embed_id": TARGET_EMBED_ID,
        "hashed_user_id": USER_HASH,
        "hashed_chat_id": CHAT_HASH,
        "encrypted_content": encrypted_content,
        "encryption_mode": "client",
        "message_id": MESSAGE_ID,
        "status": "finished",
    }


@pytest.mark.anyio
async def test_collect_code_files_uses_vault_encrypted_recent_cache() -> None:
    toon = encode({"type": "code", "code": "print('ok')", "language": "python", "filename": "main.py"})
    cached = _metadata(encrypted_content=f"vault:{toon}")

    files, target_path = await _collect_code_files(
        CHAT_ID,
        TARGET_EMBED_ID,
        [],
        [],
        None,
        _user(),
        FakeCache([TARGET_EMBED_ID], {TARGET_EMBED_ID: cached}),
        FakeDirectus({}),
        FakeEncryption(),
    )

    assert target_path == "main.py"
    assert files == [{"path": "main.py", "content": "print('ok')", "language": "python", "is_target": True}]


@pytest.mark.anyio
async def test_code_run_output_upsert_caches_vault_encrypted_inference_payload() -> None:
    cache = FakeCache([TARGET_EMBED_ID], {})
    manager = FakeManager()

    await _impl_upsert(
        manager,
        cache,
        FakeCodeRunDirectus({}),
        FakeEncryption(),
        USER_ID,
        "vault-key",
        "device-1",
        {
            "chat_id": CHAT_ID,
            "embed_id": TARGET_EMBED_ID,
            "id": "output-1",
            "key_version": 1,
            "encrypted_payload": "client-ciphertext",
            "inference_payload": {
                "output": "hello from code\n",
                "status": "exited",
                "files": ["main.py"],
                "saved_at": 123,
                "created_at": 120,
                "updated_at": 123,
            },
            "created_at": 120,
            "updated_at": 123,
        },
    )

    client = await cache.client
    cached = json.loads((await client.get(code_run_output_cache_key(USER_HASH, CHAT_HASH, TARGET_EMBED_ID))).decode())
    decrypted = await FakeEncryption().decrypt_with_user_key(cached["encrypted_content"], "vault-key")

    assert "type: code_run_output" in decrypted
    assert "hello from code" in decrypted
    assert manager.broadcasts[0]["type"] == "code_run_output_synced"


@pytest.mark.anyio
async def test_code_run_output_upsert_rejects_unknown_embed() -> None:
    cache = FakeCache([], {})
    manager = FakeManager()

    await _impl_upsert(
        manager,
        cache,
        FakeCodeRunDirectus({}),
        FakeEncryption(),
        USER_ID,
        "vault-key",
        "device-1",
        {
            "chat_id": CHAT_ID,
            "embed_id": TARGET_EMBED_ID,
            "id": "output-1",
            "encrypted_payload": "client-ciphertext",
            "created_at": 120,
            "updated_at": 123,
        },
    )

    assert manager.broadcasts == []
    assert manager.personal_messages[0]["payload"]["message"] == "Code Run output does not belong to this chat."


@pytest.mark.anyio
async def test_code_run_output_upsert_rejects_unowned_chat() -> None:
    cache = FakeCache([TARGET_EMBED_ID], {})
    manager = FakeManager()

    await _impl_upsert(
        manager,
        cache,
        FakeCodeRunDirectus({}),
        FakeEncryption(),
        USER_ID,
        "vault-key",
        "device-1",
        {
            "chat_id": "missing-chat",
            "embed_id": TARGET_EMBED_ID,
            "id": "output-1",
            "encrypted_payload": "client-ciphertext",
            "created_at": 120,
            "updated_at": 123,
        },
    )

    assert manager.broadcasts == []
    assert manager.personal_messages[0]["payload"]["message"] == "You do not have permission to sync this Code Run output."


@pytest.mark.anyio
async def test_resolve_code_embed_references_appends_cached_code_run_output() -> None:
    code_toon = encode({"type": "code", "code": "print('ok')", "language": "python", "filename": "main.py"})
    output_toon = encode({"type": "code_run_output", "status": "exited", "output": "ok\n", "files": ["main.py"], "saved_at": 123})
    cache = FakeCache([TARGET_EMBED_ID], {TARGET_EMBED_ID: _metadata(encrypted_content=f"vault:{code_toon}")})
    client = await cache.client
    await client.set(
        code_run_output_cache_key(USER_HASH, CHAT_HASH, TARGET_EMBED_ID),
        json.dumps({"encrypted_content": f"vault:{output_toon}", "chat_id": CHAT_ID, "embed_id": TARGET_EMBED_ID}),
    )
    service = EmbedService(cache, FakeDirectus({}), FakeEncryption())

    resolved, _ = await service.resolve_embed_references_in_content(
        f'```json\n{{"type":"code","embed_id":"{TARGET_EMBED_ID}"}}\n```',
        "vault-key",
    )

    assert "type: code" in resolved
    assert "type: code_run_output" in resolved
    assert "ok" in resolved


@pytest.mark.anyio
async def test_collect_code_files_requests_client_content_for_directus_only_embed() -> None:
    with pytest.raises(HTTPException) as exc_info:
        await _collect_code_files(
            CHAT_ID,
            TARGET_EMBED_ID,
            [],
            [],
            None,
            _user(),
            FakeCache([], {}),
            FakeDirectus({TARGET_EMBED_ID: _metadata()}),
            FakeEncryption(),
        )

    assert exc_info.value.status_code == 409
    assert exc_info.value.detail["code"] == CLIENT_CONTENT_REQUIRED_CODE


@pytest.mark.anyio
async def test_collect_code_files_accepts_validated_client_fallback() -> None:
    files, target_path = await _collect_code_files(
        CHAT_ID,
        TARGET_EMBED_ID,
        [CodeRunClientFile(embed_id=TARGET_EMBED_ID, code="print('client')", language="python", filename="client.py", is_target=True)],
        [],
        None,
        _user(),
        FakeCache([], {}),
        FakeDirectus({TARGET_EMBED_ID: _metadata()}),
        FakeEncryption(),
    )

    assert target_path == "client.py"
    assert files == [{"path": "client.py", "content": "print('client')", "language": "python", "is_target": True}]


@pytest.mark.anyio
async def test_collect_code_files_accepts_compiled_language_client_fallback() -> None:
    files, target_path = await _collect_code_files(
        CHAT_ID,
        TARGET_EMBED_ID,
        [CodeRunClientFile(embed_id=TARGET_EMBED_ID, code="fn main() {}", language="rust", is_target=True)],
        [],
        None,
        _user(),
        FakeCache([], {}),
        FakeDirectus({TARGET_EMBED_ID: _metadata()}),
        FakeEncryption(),
    )

    assert target_path == "snippet-embed-ta.rs"
    assert files == [{"path": "snippet-embed-ta.rs", "content": "fn main() {}", "language": "rust", "is_target": True}]


@pytest.mark.anyio
async def test_collect_code_files_rejects_atopile_client_fallback() -> None:
    with pytest.raises(HTTPException) as exc_info:
        await _collect_code_files(
            CHAT_ID,
            TARGET_EMBED_ID,
            [CodeRunClientFile(embed_id=TARGET_EMBED_ID, code="module Board:", language="atopile", filename="board.ato", is_target=True)],
            [],
            None,
            _user(),
            FakeCache([], {}),
            FakeDirectus({TARGET_EMBED_ID: _metadata()}),
            FakeEncryption(),
        )

    assert exc_info.value.status_code == 400


@pytest.mark.parametrize(
    ("language", "expected_filename"),
    [
        ("c", "snippet-embed-ta.c"),
        ("cpp", "snippet-embed-ta.cpp"),
        ("rust", "snippet-embed-ta.rs"),
        ("go", "snippet-embed-ta.go"),
        ("atopile", "snippet-embed-ta.txt"),
    ],
)
def test_safe_filename_defaults_match_code_run_support(language: str, expected_filename: str) -> None:
    assert _safe_filename(None, TARGET_EMBED_ID, language) == expected_filename


@pytest.mark.anyio
async def test_collect_code_files_filters_cached_files_to_selected_embeds() -> None:
    target_toon = encode({"type": "code", "code": "print('target')", "language": "python", "filename": "main.py"})
    helper_toon = encode({"type": "code", "code": "print('helper')", "language": "python", "filename": "helper.py"})
    skipped_toon = encode({"type": "code", "code": "print('skip')", "language": "python", "filename": "skip.py"})
    embeds = {
        TARGET_EMBED_ID: _metadata(encrypted_content=f"vault:{target_toon}"),
        "embed-helper": {**_metadata(encrypted_content=f"vault:{helper_toon}"), "embed_id": "embed-helper"},
        "embed-skip": {**_metadata(encrypted_content=f"vault:{skipped_toon}"), "embed_id": "embed-skip"},
    }

    files, target_path = await _collect_code_files(
        CHAT_ID,
        TARGET_EMBED_ID,
        [],
        [],
        [TARGET_EMBED_ID, "embed-helper"],
        _user(),
        FakeCache([TARGET_EMBED_ID, "embed-helper", "embed-skip"], embeds),
        FakeDirectus({}),
        FakeEncryption(),
    )

    assert target_path == "main.py"
    assert [file["path"] for file in files] == ["main.py", "helper.py"]


@pytest.mark.anyio
async def test_collect_code_files_accepts_selected_client_attachment_fallback() -> None:
    target_toon = encode({"type": "code", "code": "print('target')", "language": "python", "filename": "main.py"})
    attachment_id = "embed-attachment"
    attachment_metadata = {**_metadata(), "embed_id": attachment_id}

    files, target_path = await _collect_code_files(
        CHAT_ID,
        TARGET_EMBED_ID,
        [],
        [
            CodeRunClientAttachment(
                embed_id=attachment_id,
                path="data/input.txt",
                content_base64=base64.b64encode(b"hello").decode("ascii"),
                mime_type="text/plain",
            )
        ],
        [TARGET_EMBED_ID, attachment_id],
        _user(),
        FakeCache([TARGET_EMBED_ID], {TARGET_EMBED_ID: _metadata(encrypted_content=f"vault:{target_toon}")}),
        FakeDirectus({attachment_id: attachment_metadata}),
        FakeEncryption(),
    )

    assert target_path == "main.py"
    assert files[0]["path"] == "main.py"
    assert files[1]["path"] == "inputs/data/input.txt"
    assert base64.b64decode(files[1]["content_base64"]) == b"hello"


def test_code_run_cost_is_five_credits_per_minute() -> None:
    assert ROUTE_RUN_CREDITS_PER_MINUTE == 5
    assert TASK_RUN_CREDITS_PER_MINUTE == 5


def test_dependency_install_request_rejects_shell_values() -> None:
    with pytest.raises(ValueError):
        ApiCodeRunDependencyInstall(ecosystem="python", packages=["requests;curl"])


def test_requirements_manifest_rejects_external_urls() -> None:
    with pytest.raises(HTTPException) as exc_info:
        _validate_dependency_manifest("requirements.txt", "requests\nhttps://example.com/pkg.tar.gz\n")

    assert exc_info.value.status_code == 400


def test_package_json_manifest_rejects_scripts_and_file_deps() -> None:
    with pytest.raises(HTTPException) as exc_info:
        _validate_dependency_manifest(
            "package.json",
            json.dumps({"scripts": {"postinstall": "curl example.com"}, "dependencies": {"left-pad": "^1.3.0"}}),
        )
    assert exc_info.value.status_code == 400

    with pytest.raises(HTTPException) as file_dep_exc:
        _validate_dependency_manifest("package.json", json.dumps({"dependencies": {"left-pad": "file:../left-pad"}}))
    assert file_dep_exc.value.status_code == 400


def test_dependency_manifests_accept_plain_registry_packages() -> None:
    _validate_dependency_manifest("requirements.txt", "requests==2.32.0\npandas>=2.2\n")
    _validate_dependency_manifest("package.json", json.dumps({"dependencies": {"@sveltejs/kit": "^2.0.0", "vite": "latest"}}))


def test_code_run_secret_detection_allows_environment_variable_placeholders() -> None:
    code = """
import os
import requests

api_key = os.getenv("OPENWEATHER_API_KEY")
params = {"q": "Berlin", "appid": api_key, "units": "metric"}
response = requests.get("https://api.openweathermap.org/data/2.5/weather", params=params)
print(response.status_code)
"""

    assert not _looks_like_secret(code)


def test_code_run_secret_detection_blocks_high_confidence_tokens() -> None:
    assert _looks_like_secret("OPENAI_API_KEY='sk-abcdefghijklmnopqrstuvwxyz123456'")
    assert _looks_like_secret("GITHUB_TOKEN='ghp_abcdefghijklmnopqrstuvwxyz123456'")
    assert _looks_like_secret("AWS_ACCESS_KEY_ID='AKIAABCDEFGHIJKLMNOP'")


def test_dependency_installs_from_selected_install_snippets() -> None:
    installs = _dependency_installs_from_install_snippets([
        {"path": "install.sh", "language": "bash", "content": "# deps\npip install requests pandas==2.2.3\n"},
        {"path": "main.py", "language": "python", "content": "import requests\n"},
    ])

    assert [install.model_dump() for install in installs] == [
        {"ecosystem": "python", "packages": ["requests", "pandas==2.2.3"]}
    ]


def test_dependency_installs_ignore_complex_shell_snippets() -> None:
    installs = _dependency_installs_from_install_snippets([
        {"path": "install.sh", "language": "bash", "content": "pip install requests && python main.py\n"},
    ])

    assert installs == []


def test_infer_import_packages_maps_python_imports_and_ignores_stdlib() -> None:
    inferred = _infer_import_packages([
        {
            "path": "main.py",
            "language": "python",
            "content": "import os, json\nimport requests\nfrom sklearn.model_selection import train_test_split\nfrom PIL import Image\n",
        }
    ])

    assert inferred == [
        ("python", "requests", "requests", "main.py"),
        ("python", "sklearn", "scikit-learn", "main.py"),
        ("python", "PIL", "Pillow", "main.py"),
    ]


def test_infer_import_packages_normalizes_javascript_packages() -> None:
    inferred = _infer_import_packages([
        {
            "path": "main.ts",
            "language": "typescript",
            "content": "import axios from 'axios';\nconst _ = require('lodash/fp');\nimport fs from 'node:fs';\nimport timers from 'timers/promises';\nimport local from './local';\nimport { createClient } from '@supabase/supabase-js';\n",
        }
    ])

    assert inferred == [
        ("npm", "axios", "axios", "main.ts"),
        ("npm", "lodash/fp", "lodash", "main.ts"),
        ("npm", "@supabase/supabase-js", "@supabase/supabase-js", "main.ts"),
    ]


def test_merge_dependency_installs_deduplicates_client_and_snippet_packages() -> None:
    installs = _merge_dependency_installs(
        [ApiCodeRunDependencyInstall(ecosystem="python", packages=["requests"])],
        [ApiCodeRunDependencyInstall(ecosystem="python", packages=["requests", "pandas"])]
    )

    assert [install.model_dump() for install in installs] == [
        {"ecosystem": "python", "packages": ["requests", "pandas"]}
    ]


@pytest.mark.anyio
async def test_cancel_code_run_marks_execution_cancelling() -> None:
    cache = FakeCache([], {})
    client = await cache.client
    execution_id = "execution-1"
    await client.set(
        _execution_key(execution_id),
        json.dumps({"execution_id": execution_id, "user_id_hash": USER_HASH, "status": "running"}),
    )

    response = await cancel_code_run(execution_id, _user(), cache)
    stored = json.loads((await client.get(_execution_key(execution_id))).decode())

    assert response.status == "cancelling"
    assert stored["status"] == "cancelling"
    assert stored["cancel_requested"] is True


@pytest.mark.anyio
async def test_charge_run_credits_links_usage_to_chat(monkeypatch: pytest.MonkeyPatch) -> None:
    requests: list[dict] = []

    class FakeResponse:
        def raise_for_status(self) -> None:
            return None

    class FakeAsyncClient:
        def __init__(self, timeout: int):
            self.timeout = timeout

        async def __aenter__(self):
            return self

        async def __aexit__(self, exc_type, exc, tb):
            return None

        async def post(self, url: str, json: dict, headers: dict):
            requests.append({"url": url, "json": json, "headers": headers})
            return FakeResponse()

    monkeypatch.setattr("backend.apps.code.tasks.run_code_task.httpx.AsyncClient", FakeAsyncClient)

    charged = await _charge_run_credits(
        {
            "user_id": USER_ID,
            "user_id_hash": USER_HASH,
            "chat_id": CHAT_ID,
            "message_id": MESSAGE_ID,
            "target_embed_id": TARGET_EMBED_ID,
            "target_path": "main.py",
            "files": [{"path": "main.py"}],
        },
        5,
        "execution-1",
        {"billing_phase": "initial_minute", "charged_minutes": 1},
    )

    assert charged == 5
    assert requests[0]["json"]["credits"] == 5
    assert requests[0]["json"]["app_id"] == "code"
    assert requests[0]["json"]["skill_id"] == "run"
    assert requests[0]["json"]["usage_details"]["chat_id"] == CHAT_ID
    assert requests[0]["json"]["usage_details"]["message_id"] == MESSAGE_ID
    usage_details = requests[0]["json"]["usage_details"]
    assert usage_details["credits_per_minute"] == 5
    assert usage_details["code_run_filenames"] == ["main.py"]


@pytest.mark.anyio
async def test_charge_run_credits_includes_code_run_runtime(monkeypatch: pytest.MonkeyPatch) -> None:
    requests: list[dict] = []

    class FakeResponse:
        def raise_for_status(self) -> None:
            return None

    class FakeAsyncClient:
        def __init__(self, timeout: int):
            self.timeout = timeout

        async def __aenter__(self):
            return self

        async def __aexit__(self, exc_type, exc, tb):
            return None

        async def post(self, url: str, json: dict, headers: dict):
            requests.append({"url": url, "json": json, "headers": headers})
            return FakeResponse()

    monkeypatch.setattr("backend.apps.code.tasks.run_code_task.httpx.AsyncClient", FakeAsyncClient)

    await _charge_run_credits(
        {
            "user_id": USER_ID,
            "user_id_hash": USER_HASH,
            "chat_id": CHAT_ID,
            "message_id": MESSAGE_ID,
            "target_embed_id": TARGET_EMBED_ID,
            "target_path": "main.py",
            "files": [{"path": "main.py"}, {"path": "helper.py"}],
        },
        10,
        "execution-1",
        {"billing_phase": "completed", "duration_seconds": 61.234, "charged_minutes": 2},
    )

    usage_details = requests[0]["json"]["usage_details"]
    assert usage_details["code_run_filenames"] == ["main.py", "helper.py"]
    assert usage_details["duration_seconds"] == 61.234
