# backend/tests/test_code_quality_embed_encryption_guard.py
#
# Regression coverage for the commit-time embed encryption boundary audit.
# Chat embed content in Directus must be produced by client-side encryption only;
# server Vault ciphertext is permitted only in explicit inference/runtime caches.
# These tests keep the guard deterministic without needing a staged git diff.

from __future__ import annotations

import importlib.util
import sys
from pathlib import Path


def _load_guard_module():
    module_path = Path(__file__).resolve().parents[2] / "scripts" / "code_quality_guard.py"
    scripts_path = str(module_path.parent)
    if scripts_path not in sys.path:
        sys.path.insert(0, scripts_path)
    spec = importlib.util.spec_from_file_location("code_quality_guard_under_test", module_path)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_embed_vault_guard_blocks_directus_embed_content_write(monkeypatch) -> None:
    guard = _load_guard_module()
    source = '''
async def bad_writer(directus_service, encryption_service):
    encrypted_updated, _ = await encryption_service.encrypt_with_user_key("toon", "vault-key")
    await directus_service.embed.update_embed("embed-1", {"encrypted_content": encrypted_updated})
'''
    monkeypatch.setattr(guard, "_staged_file_text", lambda _path: source)

    issues = guard._audit_backend_embed_vault_boundaries(["backend/apps/code/tasks/example.py"])

    assert len(issues) == 1
    assert "writes Vault-encrypted data to embeds.encrypted_content" in issues[0]


def test_embed_vault_guard_blocks_unmarked_embed_cache_write(monkeypatch) -> None:
    guard = _load_guard_module()
    source = '''
async def bad_cache_writer(client, encryption_service):
    encrypted_content, _ = await encryption_service.encrypt_with_user_key("toon", "vault-key")
    await client.set(f"embed:{embed_id}", json.dumps({"encrypted_content": encrypted_content}))
'''
    monkeypatch.setattr(guard, "_staged_file_text", lambda _path: source)

    issues = guard._audit_backend_embed_vault_boundaries(["backend/apps/code/tasks/example.py"])

    assert len(issues) == 1
    assert "without EMBED_VAULT_INFERENCE_CACHE_OK" in issues[0]


def test_embed_vault_guard_allows_marked_inference_cache(monkeypatch) -> None:
    guard = _load_guard_module()
    source = '''
async def inference_cache_writer(client, encryption_service):
    # EMBED_VAULT_INFERENCE_CACHE_OK: runtime cache only; Directus still waits for client store_embed.
    encrypted_content, _ = await encryption_service.encrypt_with_user_key("toon", "vault-key")
    await client.set(f"embed:{embed_id}", json.dumps({"encrypted_content": encrypted_content}))
'''
    monkeypatch.setattr(guard, "_staged_file_text", lambda _path: source)

    issues = guard._audit_backend_embed_vault_boundaries(["backend/apps/ai/tasks/stream_consumer.py"])

    assert issues == []


def test_embed_vault_guard_blocks_chat_message_directus_write(monkeypatch) -> None:
    guard = _load_guard_module()
    source = '''
async def bad_message_writer(directus_service, encryption_service):
    encrypted_content, _ = await encryption_service.encrypt_with_user_key("hello", "vault-key")
    await directus_service.create_item('messages', {"encrypted_content": encrypted_content})
'''
    monkeypatch.setattr(guard, "_staged_file_text", lambda _path: source)

    issues = guard._audit_backend_embed_vault_boundaries(["backend/apps/reminder/skills/example.py"])

    assert len(issues) == 1
    assert "Directus chats/messages writes" in issues[0]


def test_embed_vault_guard_blocks_chat_metadata_directus_write(monkeypatch) -> None:
    guard = _load_guard_module()
    source = '''
async def bad_chat_writer(directus_service, encryption_service):
    encrypted_title, _ = await encryption_service.encrypt_with_user_key("title", "vault-key")
    await directus_service.update_item(collection='chats', item_id="chat-1", data={"encrypted_title": encrypted_title})
'''
    monkeypatch.setattr(guard, "_staged_file_text", lambda _path: source)

    issues = guard._audit_backend_embed_vault_boundaries(["backend/apps/reminder/skills/example.py"])

    assert len(issues) == 1
    assert "privacy-bound chat metadata" in issues[0]


def test_embed_vault_guard_ignores_non_backend_sources(monkeypatch) -> None:
    guard = _load_guard_module()
    monkeypatch.setattr(guard, "_staged_file_text", lambda _path: "this would otherwise mention encrypted_content")

    assert guard._audit_backend_embed_vault_boundaries(["backend/tests/example.py", "frontend/app.ts"]) == []
