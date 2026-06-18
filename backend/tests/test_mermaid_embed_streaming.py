# backend/tests/test_mermaid_embed_streaming.py
#
# Dormant contract tests for disabled Diagrams-owned Mermaid embeds. These guard
# that Mermaid fences fall through to the generic Code path while preserving the
# parked service helpers for a future refinement pass.

from __future__ import annotations

import json
import re
import sys
import types
from pathlib import Path

import pytest
import yaml


REPO_ROOT = Path(__file__).resolve().parents[2]
DIAGRAMS_APP_YML = REPO_ROOT / "backend/apps/diagrams/app.yml"
DIAGRAMS_DISABLED_APP_YML = REPO_ROOT / "backend/apps/diagrams/app.disabled.yml"
STREAM_CONSUMER = REPO_ROOT / "backend/apps/ai/tasks/stream_consumer.py"


def test_mermaid_fence_detection_is_disabled() -> None:
    from backend.apps.ai.utils.mermaid_fences import (
        _extract_mermaid_metadata,
        _is_mermaid_fence,
    )

    source = """sequenceDiagram
    participant User
    participant API
    User->>API: Submit email
    API-->>User: Send verification code
"""

    assert _is_mermaid_fence("mermaid") is False
    assert _is_mermaid_fence("mmd") is False
    assert _is_mermaid_fence("diagram") is False
    assert _is_mermaid_fence("python") is False

    metadata = _extract_mermaid_metadata("mermaid", None, source)

    assert metadata == {
        "language": "mermaid",
        "title": "Sequence Diagram",
        "diagram_kind": "sequenceDiagram",
        "line_count": 6,
    }


def test_diagrams_app_definition_is_dormant() -> None:
    assert not DIAGRAMS_APP_YML.exists()
    app = yaml.safe_load(DIAGRAMS_DISABLED_APP_YML.read_text())

    assert app["app_id"] == "diagrams"
    embed = next(item for item in app["embed_types"] if item.get("backend_type") == "mermaid")

    assert embed["category"] == "direct"
    assert embed["frontend_type"] == "diagrams-mermaid"
    assert embed["preview_component"] == "diagrams/MermaidDiagramEmbedPreview.svelte"
    assert embed["fullscreen_component"] == "diagrams/MermaidDiagramEmbedFullscreen.svelte"
    assert embed["content_catalog"]["content_type_id"] == "mermaid"
    assert app["instructions"] == []


def test_streaming_path_keeps_mermaid_branch_dormant() -> None:
    source = STREAM_CONSUMER.read_text(encoding="utf-8")
    multi_chunk_branch = source[source.index("is_mermaid_block_multi = _is_mermaid_fence(current_code_language)") :]
    finalization_branch = source[source.index("if in_plot_block:", source.index("# Finalize embed")) :]

    assert "is_mermaid_block_multi = _is_mermaid_fence(current_code_language)" in source
    assert "elif is_mermaid_block_multi:" in source
    assert "create_mermaid_embed_placeholder" in source
    assert "update_mermaid_embed_content" in source
    assert multi_chunk_branch.index("elif is_mermaid_block_multi:") < multi_chunk_branch.index("create_code_embed_placeholder(")
    assert finalization_branch.index("elif in_mermaid_block:") < finalization_branch.index("Finalized code embed")


redis_stub = types.ModuleType("redis")
redis_asyncio_stub = types.ModuleType("redis.asyncio")
redis_exceptions_stub = types.SimpleNamespace(RedisError=Exception, ConnectionError=Exception)
redis_asyncio_stub.Redis = object
redis_stub.asyncio = redis_asyncio_stub
redis_stub.exceptions = redis_exceptions_stub
sys.modules.setdefault("redis", redis_stub)
sys.modules.setdefault("redis.asyncio", redis_asyncio_stub)

cache_module_stub = types.ModuleType("backend.core.api.app.services.cache")
cache_module_stub.CacheService = object
sys.modules.setdefault("backend.core.api.app.services.cache", cache_module_stub)

directus_module_stub = types.ModuleType("backend.core.api.app.services.directus")
directus_module_stub.DirectusService = object
sys.modules.setdefault("backend.core.api.app.services.directus", directus_module_stub)

toon_stub = types.ModuleType("toon_format")
toon_stub.encode = lambda value: json.dumps(value)
toon_stub.decode = lambda value: json.loads(value)
sys.modules.setdefault("toon_format", toon_stub)

youtube_stub = types.ModuleType("backend.shared.providers.youtube.youtube_metadata")
youtube_stub.extract_youtube_id_from_url = lambda url: None
sys.modules.setdefault("backend.shared.providers.youtube.youtube_metadata", youtube_stub)

github_stub = types.ModuleType("backend.shared.providers.github")


async def _build_github_repo_embed_stub(_url: str):
    return None


def _is_github_repo_url_stub(url: str) -> bool:
    return bool(re.match(r"^https://github\.com/[^/]+/[^/]+/?$", url or ""))


github_stub.build_github_repo_embed = _build_github_repo_embed_stub
github_stub.is_github_repo_url = _is_github_repo_url_stub
sys.modules.setdefault("backend.shared.providers.github", github_stub)

e2b_preview_stub = types.ModuleType("backend.shared.providers.e2b_application_preview")
e2b_preview_stub.ApplicationPreviewEntrypoint = object
e2b_preview_stub.ApplicationPreviewFile = object
e2b_preview_stub.ApplicationPreviewPlanningError = Exception
e2b_preview_stub.plan_application_preview_startup = lambda *args, **kwargs: None
sys.modules.setdefault("backend.shared.providers.e2b_application_preview", e2b_preview_stub)

from backend.core.api.app.services.embed_service import EmbedService  # noqa: E402

decode = toon_stub.decode


class FakeRedisClient:
    def __init__(self) -> None:
        self.values: dict[str, str] = {}
        self.published: list[tuple[str, dict]] = []

    async def get(self, key: str):
        return self.values.get(key)

    async def set(self, key: str, value: str, ex: int | None = None):
        self.values[key] = value

    async def sadd(self, key: str, value: str):
        return 1

    async def expire(self, key: str, ttl: int):
        return True

    async def publish(self, channel: str, message: str):
        self.published.append((channel, json.loads(message)))
        return 1


class FakeCacheService:
    def __init__(self) -> None:
        self._client = FakeRedisClient()

    @property
    async def client(self):
        return self._client


class FakeEncryptionService:
    async def encrypt_with_user_key(self, content: str, vault_key_id: str):
        return content, "test-key-version"

    async def decrypt_with_user_key(self, encrypted_content: str, vault_key_id: str):
        return encrypted_content


@pytest.mark.asyncio
async def test_embed_service_creates_and_updates_mermaid_payload() -> None:
    cache = FakeCacheService()
    service = EmbedService(cache, directus_service=object(), encryption_service=FakeEncryptionService())
    service._schedule_embed_persistence_fallback = lambda embed_id: None

    created = await service.create_mermaid_embed_placeholder(
        chat_id="chat-1",
        message_id="message-1",
        user_id="user-1",
        user_id_hash="user-hash",
        user_vault_key_id="vault-1",
        task_id="task-1",
        title="Signup Flow",
        diagram_kind="sequenceDiagram",
        log_prefix="[test]",
    )

    assert created is not None
    assert json.loads(created["embed_reference"]) == {
        "type": "mermaid",
        "embed_id": created["embed_id"],
    }

    ok = await service.update_mermaid_embed_content(
        embed_id=created["embed_id"],
        diagram_code="sequenceDiagram\n    User->>API: Submit email",
        chat_id="chat-1",
        user_id="user-1",
        user_id_hash="user-hash",
        user_vault_key_id="vault-1",
        status="finished",
        title="Signup Flow",
        diagram_kind="sequenceDiagram",
        version_number=2,
        content_hash="content-hash-v2",
        version_history_rows=[{"version_number": 1, "snapshot": "old"}],
        log_prefix="[test]",
    )

    assert ok is True
    cached_after = json.loads(cache._client.values[f"embed:{created['embed_id']}"])
    content = decode(cached_after["encrypted_content"])
    assert cached_after["type"] == "mermaid"
    assert cached_after["version_number"] == 2
    assert cached_after["content_hash"] == "content-hash-v2"
    assert content["type"] == "mermaid"
    assert content["app_id"] == "diagrams"
    assert content["skill_id"] == "mermaid"
    assert content["title"] == "Signup Flow"
    assert content["diagram_kind"] == "sequenceDiagram"
    assert content["diagram_code"].startswith("sequenceDiagram")
    assert content["status"] == "finished"
    assert content["version_number"] == 2
    assert content["embed_ref"].startswith("signup-flow-")

    final_event = cache._client.published[-1][1]["payload"]
    assert final_event["embed_id"] == created["embed_id"]
    assert final_event["version_number"] == 2
    assert final_event["content_hash"] == "content-hash-v2"
    assert "sequenceDiagram" in final_event["content"]
