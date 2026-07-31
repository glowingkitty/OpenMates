# backend/tests/test_code_notebook_artifacts.py
#
# Contract tests for the Code app notebook embed metadata and nbformat
# validation. Notebook source is an encrypted embed artifact; runtime outputs are
# persisted separately by notebook_run_outputs sidecars.

from __future__ import annotations

import json
from pathlib import Path

import pytest
import yaml
from fastapi import HTTPException

from backend.tests.runtime_import_stubs import install_code_route_import_stubs


install_code_route_import_stubs()

from backend.core.api.app.routes.code_notebook_execution import validate_notebook_payload  # noqa: E402
from backend.core.api.app.services import embed_service as embed_service_module  # noqa: E402
from backend.core.api.app.services.embed_service import EmbedService  # noqa: E402


REPO_ROOT = Path(__file__).resolve().parents[2]


def _python_notebook() -> dict:
    return {
        "nbformat": 4,
        "nbformat_minor": 5,
        "metadata": {"kernelspec": {"language": "python", "name": "python3"}},
        "cells": [
            {"cell_type": "markdown", "metadata": {}, "source": "# Weather analysis"},
            {"cell_type": "code", "metadata": {}, "source": "print('ok')", "outputs": []},
        ],
    }


def _python_percent_cell_script() -> str:
    return """# %% [markdown]
# # Berlin Bike Weather
# Check whether the coming week is good for a weekend bike ride.
# %%
import pandas as pd

hourly = pd.DataFrame({"temperature": [20, 22], "rain": [0.0, 0.2]})
hourly["ride_score"] = 100 - hourly["rain"] * 50
# %%
daily = hourly.mean(numeric_only=True)
print(daily)
"""


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
        self.pending_embeds: list[tuple[str, str]] = []

    @property
    async def client(self):
        return self._client

    async def add_pending_embed(self, user_id: str, embed_id: str) -> None:
        self.pending_embeds.append((user_id, embed_id))


class FakeEncryptionService:
    async def encrypt_with_user_key(self, content: str, vault_key_id: str):
        return content, "test-key-version"

    async def decrypt_with_user_key(self, encrypted_content: str, vault_key_id: str):
        return encrypted_content


def test_code_app_declares_notebook_embed_type() -> None:
    app_yml = yaml.safe_load((REPO_ROOT / "backend/apps/code/app.yml").read_text())
    notebook = next((item for item in app_yml["embed_types"] if item.get("id") == "notebook"), None)

    assert notebook is not None
    assert notebook["frontend_type"] == "code-notebook"
    assert notebook["backend_type"] == "notebook"
    assert notebook["preview_component"] == "code/NotebookEmbedPreview.svelte"
    assert notebook["fullscreen_component"] == "code/NotebookEmbedFullscreen.svelte"
    assert notebook["content_catalog"]["diff_editable"] is True


def test_validate_notebook_payload_accepts_python_nbformat() -> None:
    notebook = validate_notebook_payload(_python_notebook())

    assert notebook["filename"] == "notebook.ipynb"
    assert notebook["cell_count"] == 2
    assert notebook["language"] == "python"
    assert notebook["is_python"] is True


def test_validate_notebook_payload_rejects_malformed_notebook() -> None:
    with pytest.raises(HTTPException) as exc:
        validate_notebook_payload({"cells": "not-a-list"})

    assert exc.value.status_code == 422


def test_validate_notebook_payload_rejects_non_python_for_execution() -> None:
    notebook = _python_notebook()
    notebook["metadata"]["kernelspec"] = {"language": "R", "name": "ir"}

    with pytest.raises(HTTPException) as exc:
        validate_notebook_payload(notebook, require_python=True)

    assert exc.value.status_code == 422
    assert "Python notebooks only" in str(exc.value.detail)


def test_normalize_notebook_payload_strips_accidental_fence_tail() -> None:
    normalized = EmbedService._normalize_notebook_payload(
        f"```json\n{json.dumps(_python_notebook())}\n```",
        "weather.ipynb",
    )

    assert normalized["filename"] == "weather.ipynb"
    assert normalized["language"] == "python"
    assert normalized["cell_count"] == 2
    assert normalized["notebook"] == _python_notebook()


def test_normalize_notebook_payload_extracts_leading_json_before_trailing_prose() -> None:
    normalized = EmbedService._normalize_notebook_payload(
        f"{json.dumps(_python_notebook(), indent=2)}\n\nWould you like me to export an HTML report?",
        "weather.ipynb",
    )

    assert normalized["filename"] == "weather.ipynb"
    assert normalized["language"] == "python"
    assert normalized["cell_count"] == 2
    assert normalized["notebook"] == _python_notebook()


@pytest.mark.asyncio
async def test_ipynb_code_artifact_creates_notebook_embed(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(embed_service_module, "encode", lambda value: json.dumps(value))
    monkeypatch.setattr(embed_service_module, "decode", lambda value: json.loads(value))

    cache = FakeCacheService()
    service = EmbedService(cache, directus_service=object(), encryption_service=FakeEncryptionService())
    service._schedule_embed_persistence_fallback = lambda embed_id: None

    created = await service.create_code_embed_placeholder(
        language="python",
        chat_id="chat-1",
        message_id="message-1",
        user_id="user-1",
        user_id_hash="user-hash",
        user_vault_key_id="vault-1",
        filename="weather.ipynb",
        log_prefix="[test]",
    )

    assert created is not None
    assert json.loads(created["embed_reference"]) == {
        "type": "notebook",
        "embed_id": created["embed_id"],
    }

    cached_placeholder = json.loads(cache._client.values[f"embed:{created['embed_id']}"])
    assert cached_placeholder["type"] == "notebook"
    placeholder_content = json.loads(cached_placeholder["encrypted_content"])
    assert placeholder_content["type"] == "notebook"
    assert placeholder_content["filename"] == "weather.ipynb"
    assert placeholder_content["status"] == "processing"

    ok = await service.update_code_embed_content(
        embed_id=created["embed_id"],
        code_content=json.dumps(_python_notebook()),
        chat_id="chat-1",
        user_id="user-1",
        user_id_hash="user-hash",
        user_vault_key_id="vault-1",
        status="finished",
        version_number=2,
        content_hash="notebook-source-v2",
        log_prefix="[test]",
    )

    assert ok is True
    cached_final = json.loads(cache._client.values[f"embed:{created['embed_id']}"])
    final_content = json.loads(cached_final["encrypted_content"])
    assert cached_final["type"] == "notebook"
    assert cached_final["version_number"] == 2
    assert cached_final["content_hash"] == "notebook-source-v2"
    assert final_content["type"] == "notebook"
    assert final_content["skill_id"] == "notebook"
    assert final_content["language"] == "python"
    assert final_content["filename"] == "weather.ipynb"
    assert final_content["cell_count"] == 2
    assert final_content["notebook"] == _python_notebook()
    assert "code" not in final_content

    final_event = cache._client.published[-1][1]["payload"]
    assert final_event["type"] == "notebook"
    assert final_event["version_number"] == 2
    assert '"type": "notebook"' in final_event["content"]


@pytest.mark.asyncio
async def test_python_percent_cell_script_creates_notebook_embed(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(embed_service_module, "encode", lambda value: json.dumps(value))
    monkeypatch.setattr(embed_service_module, "decode", lambda value: json.loads(value))

    cache = FakeCacheService()
    service = EmbedService(cache, directus_service=object(), encryption_service=FakeEncryptionService())
    service._schedule_embed_persistence_fallback = lambda embed_id: None
    source = _python_percent_cell_script()

    created = await service.create_code_embed_placeholder(
        language="python",
        chat_id="chat-1",
        message_id="message-1",
        user_id="user-1",
        user_id_hash="user-hash",
        user_vault_key_id="vault-1",
        filename="berlin_bike_weather.py",
        code_content=source,
        log_prefix="[test]",
    )

    assert created is not None
    assert json.loads(created["embed_reference"]) == {
        "type": "notebook",
        "embed_id": created["embed_id"],
    }

    ok = await service.update_code_embed_content(
        embed_id=created["embed_id"],
        code_content=source,
        chat_id="chat-1",
        user_id="user-1",
        user_id_hash="user-hash",
        user_vault_key_id="vault-1",
        status="finished",
        log_prefix="[test]",
    )

    assert ok is True
    cached_final = json.loads(cache._client.values[f"embed:{created['embed_id']}"])
    final_content = json.loads(cached_final["encrypted_content"])
    assert cached_final["type"] == "notebook"
    assert final_content["type"] == "notebook"
    assert final_content["filename"] == "berlin_bike_weather.ipynb"
    assert final_content["language"] == "python"
    assert final_content["cell_count"] == 3
    notebook = final_content["notebook"]
    assert notebook["nbformat"] == 4
    assert [cell["cell_type"] for cell in notebook["cells"]] == ["markdown", "code", "code"]
    assert "# Berlin Bike Weather" in notebook["cells"][0]["source"]
    assert "pd.DataFrame" in notebook["cells"][1]["source"]


@pytest.mark.asyncio
async def test_python_percent_cell_update_promotes_existing_code_embed(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(embed_service_module, "encode", lambda value: json.dumps(value))
    monkeypatch.setattr(embed_service_module, "decode", lambda value: json.loads(value))

    cache = FakeCacheService()
    service = EmbedService(cache, directus_service=object(), encryption_service=FakeEncryptionService())
    service._schedule_embed_persistence_fallback = lambda embed_id: None

    created = await service.create_code_embed_placeholder(
        language="python",
        chat_id="chat-1",
        message_id="message-1",
        user_id="user-1",
        user_id_hash="user-hash",
        user_vault_key_id="vault-1",
        filename="weather_cells.py",
        log_prefix="[test]",
    )

    assert created is not None
    assert json.loads(created["embed_reference"])["type"] == "code"

    ok = await service.update_code_embed_content(
        embed_id=created["embed_id"],
        code_content=_python_percent_cell_script(),
        chat_id="chat-1",
        user_id="user-1",
        user_id_hash="user-hash",
        user_vault_key_id="vault-1",
        status="finished",
        log_prefix="[test]",
    )

    assert ok is True
    cached_final = json.loads(cache._client.values[f"embed:{created['embed_id']}"])
    final_content = json.loads(cached_final["encrypted_content"])
    assert cached_final["type"] == "notebook"
    assert final_content["type"] == "notebook"
    assert final_content["filename"] == "weather_cells.ipynb"
    assert final_content["cell_count"] == 3
    final_event = cache._client.published[-1][1]["payload"]
    assert final_event["type"] == "notebook"
    assert '"type": "notebook"' in final_event["content"]
