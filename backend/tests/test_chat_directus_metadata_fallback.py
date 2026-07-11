# backend/tests/test_chat_directus_metadata_fallback.py
#
# Directus roles can temporarily lag newly added chat metadata fields.
# These tests ensure a denied optional version field does not discard encrypted
# shared-chat header metadata required by public share clients.

from __future__ import annotations

import importlib.util
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest


def _load_chat_methods_module():
    module_path = Path(__file__).resolve().parents[1] / "core" / "api" / "app" / "services" / "directus" / "chat_methods.py"
    spec = importlib.util.spec_from_file_location("chat_methods_fallback_under_test", module_path)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


@pytest.mark.asyncio
async def test_metadata_version_permission_fallback_preserves_shared_header_fields() -> None:
    module = _load_chat_methods_module()
    shared_metadata = {
        "id": "12345678-1234-1234-1234-123456789abc",
        "is_shared": True,
        "shared_encrypted_title": "encrypted-title",
        "shared_encrypted_summary": "encrypted-summary",
        "shared_encrypted_category": "encrypted-category",
        "shared_encrypted_icon": "encrypted-icon",
    }
    directus = SimpleNamespace(get_items=AsyncMock(side_effect=[None, [shared_metadata]]))

    result = await module.ChatMethods(directus).get_chat_metadata(shared_metadata["id"])

    assert result == shared_metadata
    attempted_fields = directus.get_items.await_args_list[1].kwargs["params"]["fields"]
    assert "metadata_v" not in attempted_fields.split(",")
    assert "is_shared" in attempted_fields.split(",")
    assert "shared_encrypted_title" in attempted_fields.split(",")
    assert "shared_encrypted_summary" in attempted_fields.split(",")
    assert "shared_encrypted_category" in attempted_fields.split(",")
    assert "shared_encrypted_icon" in attempted_fields.split(",")
