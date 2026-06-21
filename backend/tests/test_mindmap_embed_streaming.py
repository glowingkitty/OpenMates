# backend/tests/test_mindmap_embed_streaming.py
#
# Contract tests for first-class Mind Maps direct embeds. These cover the
# backend-only pieces that can be proven before browser rendering: fence
# detection, deterministic validation, and encrypted embed payload shape.

from __future__ import annotations

import json
import sys
import types
from pathlib import Path

import pytest
import yaml


REPO_ROOT = Path(__file__).resolve().parents[2]
MINDMAPS_APP_YML = REPO_ROOT / "backend/apps/mindmaps/app.yml"
STREAM_CONSUMER = REPO_ROOT / "backend/apps/ai/tasks/stream_consumer.py"


def _valid_source() -> str:
    return json.dumps(
        {
            "openmatesType": "mindmap",
            "schemaVersion": 1,
            "title": "Launch Plan",
            "rootId": "root",
            "nodes": [
                {"id": "root", "label": "Launch Plan", "children": ["research"]},
                {"id": "research", "label": "Audience Research"},
            ],
            "edges": [],
            "view": {"layout": "radial-tree", "collapsedNodeIds": []},
        }
    )


def test_mindmap_fence_detection_and_validation() -> None:
    from backend.apps.ai.utils.mindmap_fences import (
        normalize_mindmap_source,
        is_mindmap_fence,
    )

    assert is_mindmap_fence("openmates_mindmap") is True
    assert is_mindmap_fence("ommindmap") is True
    assert is_mindmap_fence("json") is False
    assert is_mindmap_fence("mermaid") is False

    result = normalize_mindmap_source(_valid_source())
    assert result.parse_error is None
    assert result.model["title"] == "Launch Plan"
    assert result.node_count == 2
    assert result.edge_count == 0
    assert result.status == "valid"

    invalid = normalize_mindmap_source('{"openmatesType":"mindmap","schemaVersion":1')
    assert invalid.status == "invalid_source"
    assert invalid.parse_error

    no_valid_nodes = normalize_mindmap_source(
        json.dumps(
            {
                "openmatesType": "mindmap",
                "schemaVersion": 1,
                "title": "Broken",
                "rootId": "root",
                "nodes": [{"label": "Missing id"}],
            }
        )
    )
    assert no_valid_nodes.status == "invalid_source"
    assert no_valid_nodes.model is None


def test_mindmaps_app_definition_registers_direct_embed_type() -> None:
    app = yaml.safe_load(MINDMAPS_APP_YML.read_text())

    assert app["app_id"] == "mindmaps"
    embed = next(item for item in app["embed_types"] if item.get("backend_type") == "mindmap")

    assert embed["category"] == "direct"
    assert embed["frontend_type"] == "mindmaps-mindmap"
    assert embed["preview_component"] == "mindmaps/MindMapEmbedPreview.svelte"
    assert embed["fullscreen_component"] == "mindmaps/MindMapEmbedFullscreen.svelte"
    assert embed["content_catalog"]["content_type_id"] == "mindmap"
    assert "openmates_mindmap" in app["instructions"][0]["instruction"]


def test_streaming_path_handles_mindmap_branches() -> None:
    source = STREAM_CONSUMER.read_text(encoding="utf-8")

    assert "is_mindmap_block" in source
    assert "is_mindmap_block_multi" in source
    assert "create_mindmap_embed_placeholder" in source
    assert "update_mindmap_embed_content" in source


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
github_stub.build_github_repo_embed = lambda *args, **kwargs: None
github_stub.is_github_repo_url = lambda url: False
sys.modules.setdefault("backend.shared.providers.github", github_stub)

e2b_stub = types.ModuleType("backend.shared.providers.e2b_application_preview")
e2b_stub.ApplicationPreviewEntrypoint = object
e2b_stub.ApplicationPreviewFile = object
e2b_stub.ApplicationPreviewPlanningError = Exception
e2b_stub.plan_application_preview_startup = lambda *args, **kwargs: None
sys.modules.setdefault("backend.shared.providers.e2b_application_preview", e2b_stub)

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
async def test_embed_service_creates_and_updates_mindmap_payload() -> None:
    cache = FakeCacheService()
    service = EmbedService(cache, directus_service=object(), encryption_service=FakeEncryptionService())
    service._schedule_embed_persistence_fallback = lambda embed_id: None

    created = await service.create_mindmap_embed_placeholder(
        chat_id="chat-1",
        message_id="message-1",
        user_id="user-1",
        user_id_hash="user-hash",
        user_vault_key_id="vault-1",
        task_id="task-1",
        title="Launch Plan",
        log_prefix="[test]",
    )

    assert created is not None
    assert json.loads(created["embed_reference"]) == {
        "type": "mindmap",
        "embed_id": created["embed_id"],
    }

    ok = await service.update_mindmap_embed_content(
        embed_id=created["embed_id"],
        source_json=_valid_source(),
        chat_id="chat-1",
        user_id="user-1",
        user_id_hash="user-hash",
        user_vault_key_id="vault-1",
        status="finished",
        version_number=2,
        content_hash="content-hash-v2",
        log_prefix="[test]",
    )

    assert ok is True
    cached_after = json.loads(cache._client.values[f"embed:{created['embed_id']}"])
    content = decode(cached_after["encrypted_content"])
    assert cached_after["type"] == "mindmap"
    assert cached_after["version_number"] == 2
    assert cached_after["content_hash"] == "content-hash-v2"
    assert content["type"] == "mindmap"
    assert content["app_id"] == "mindmaps"
    assert content["skill_id"] == "mindmap"
    assert content["title"] == "Launch Plan"
    assert content["node_count"] == 2
    assert content["edge_count"] == 0
    assert content["validation"]["status"] == "valid"
    assert content["model"]["rootId"] == "root"
    assert content["embed_ref"].startswith("launch-plan-")

    final_event = cache._client.published[-1][1]["payload"]
    assert final_event["embed_id"] == created["embed_id"]
    assert final_event["version_number"] == 2
    assert final_event["content_hash"] == "content-hash-v2"
    assert "openmatesType" in final_event["content"]
