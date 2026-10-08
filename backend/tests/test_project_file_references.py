"""Storage boundary regressions for Project file chat previews."""

import json
import sys
from types import ModuleType, SimpleNamespace

import pytest
from toon_format import decode

from backend.apps.ai.processing.project_file_references import (
    build_project_file_reference_preview, publish_project_file_reference_preview,
)


@pytest.fixture
def turn_key_import(monkeypatch):
    # Keep the publication unit test independent of Celery's package-level
    # task discovery and provider fixtures from other test modules.
    module = ModuleType("backend.apps.ai.tasks.async_skill_continuation")
    module.async_skill_latest_user_turn_key = lambda user, chat: f"turn:{user}:{chat}"
    monkeypatch.setitem(sys.modules, module.__name__, module)


def context(skill="project_search_files"):
    return {
        "app_id": "system", "skill_id": skill, "tool_arguments": {"query": "README", "path": "README.md"},
        "request_data": {"active_project_focus": {"project_id": "project"},
                         "project_focus_candidates": [{"project_id": "project", "name": "OpenMates"}]},
    }


# contract-test: supporting surface=gui.web assertions=projects.files.no-server-decryption-authority,projects.files.search-scoped
def test_remote_search_persists_locations_without_any_file_content_or_key():
    preview = build_project_file_reference_preview(
        context=context(), result_status="completed",
        completed_results=[{"status": "completed", "source_id": "remote-source",
                            "content": "DO_NOT_COPY_FILE_CONTENT", "key": "DO_NOT_COPY_KEY",
                            "matches": [{"path": "README.md", "line": 2,
                                         "snippet": "DO_NOT_COPY_SEARCH_SNIPPET",
                                         "metadata": {"content": "DO_NOT_COPY_NESTED_CONTENT"}}]}],
    )
    assert preview["results"] == [{"project_id": "project", "project_name": "OpenMates",
                                   "source_id": "remote-source", "path": "README.md", "line": 2}]
    assert "DO_NOT_COPY" not in json.dumps(preview)
    assert preview["query"] == "README"
    assert preview["search_target"] == "files"


# contract-test: supporting surface=gui.web assertions=projects.files.no-server-decryption-authority,projects.files.search-scoped
def test_content_search_uses_same_reference_embed_without_snippet() -> None:
    preview = build_project_file_reference_preview(
        context=context("project_search_text"), result_status="completed",
        completed_results=[{"status": "completed", "source_id": "remote-source",
                            "matches": [{"path": "docs/README.md", "line": 5,
                                         "snippet": "PRIVATE_MATCH"}]}],
    )
    assert preview["skill_id"] == "search"
    assert preview["search_target"] == "content"
    assert preview["results"] == [{
        "project_id": "project", "project_name": "OpenMates",
        "source_id": "remote-source", "path": "docs/README.md", "line": 5,
    }]
    assert "PRIVATE_MATCH" not in json.dumps(preview)


# contract-test: supporting surface=gui.web assertions=projects.files.no-server-decryption-authority,projects.files.search-scoped
@pytest.mark.asyncio
@pytest.mark.parametrize("skill,target,expected_target", [
    ("project_search_files", "files", "files"),
    ("project_search_text", "content", "content"),
    ("project_search_files", "arbitrary-client-value", None),
])
async def test_noncomposite_project_search_embed_serializes_target_and_locations_only(skill, target, expected_target):
    from backend.core.api.app.services.embed_service import EmbedService

    preview = build_project_file_reference_preview(
        context=context(skill), result_status="completed",
        completed_results=[{"status": "completed", "source_id": "remote-source",
                            "content": "PRIVATE_FILE_BYTES", "matches": [{
                                "path": "README.md", "line": 2, "snippet": "PRIVATE_SEARCH_SNIPPET",
                            }]}],
    )
    assert preview is not None
    sent = []

    class ProjectMetadataCache:
        async def get_discovered_apps_metadata(self):
            return {"projects": SimpleNamespace(embed_types=[
                SimpleNamespace(skill_id="search", child_type=None),
            ])}

    async def encrypt(value, _key):
        return "encrypted:" + value, None

    async def send(**kwargs):
        sent.append(kwargs)
        return True

    service = EmbedService.__new__(EmbedService)
    service.cache_service = ProjectMetadataCache()
    service.encryption_service = SimpleNamespace(encrypt_with_user_key=encrypt)
    service.send_embed_data_to_client = send
    service._schedule_embed_persistence_fallback = lambda _embed_id: None
    created = await service.create_embeds_from_skill_results(
        app_id="projects", skill_id="search", results=preview["results"],
        chat_id="chat", message_id="message", user_id="owner", user_id_hash="owner-hash",
        user_vault_key_id="vault-key", request_metadata={
            "query": preview["query"], "search_target": target,
            "private_metadata": "PRIVATE_METADATA",
        },
    )
    assert created is not None and created["child_embed_ids"] == []
    assert len(sent) == 1
    serialized = sent[0]["content_toon"]
    content = decode(serialized)
    if expected_target is None:
        assert "search_target" not in content
    else:
        assert content["search_target"] == expected_target
    assert content["results"] == preview["results"]
    expected_fields = {"app_id", "skill_id", "results", "result_count", "status",
                       "embed_ref", "query"}
    if expected_target is not None:
        expected_fields.add("search_target")
    assert set(content) == expected_fields
    assert "PRIVATE_" not in serialized


# contract-test: supporting surface=gui.web assertions=projects.files.no-server-decryption-authority
def test_hosted_read_reuses_original_embed_identity_without_copying_contents():
    preview = build_project_file_reference_preview(
        context=context("project_read_text"), result_status="completed",
        completed_results=[{"status": "completed", "source_id": None, "path": "README.md",
                            "embed_id": "original-hosted-embed", "content": "DO_NOT_COPY",
                            "expected_base": "private-content-fingerprint", "revision": 17}],
    )
    assert preview["results"] == [{"project_id": "project", "project_name": "OpenMates",
                                   "path": "README.md", "embed_id": "original-hosted-embed"}]
    assert "DO_NOT_COPY" not in json.dumps(preview)
    assert "private-content-fingerprint" not in json.dumps(preview)


# contract-test: supporting surface=gui.web assertions=projects.files.no-server-decryption-authority,projects.files.search-scoped
def test_remote_read_reply_without_path_uses_dispatched_path_and_not_returned_path():
    for returned_path in (None, "different-file.md"):
        result = {"status": "completed", "source_id": "remote-source", "content": "DO_NOT_COPY"}
        if returned_path is not None:
            result["path"] = returned_path
        preview = build_project_file_reference_preview(
            context=context("project_read_text"), result_status="completed", completed_results=[result],
        )
        assert preview["query"] == "README.md"
        assert preview["results"] == [{"project_id": "project", "project_name": "OpenMates",
                                       "source_id": "remote-source", "path": "README.md"}]
        assert "DO_NOT_COPY" not in json.dumps(preview)


# contract-test: supporting surface=gui.web assertions=projects.files.search-scoped,projects.focus.inferred-consent
@pytest.mark.parametrize("status", ["failed", "user_declined", "waiting_for_executor"])
def test_incomplete_or_rejected_file_result_has_no_durable_reference(status):
    assert build_project_file_reference_preview(
        context=context(), result_status=status,
        completed_results=[{"status": status, "source_id": "remote", "matches": [{"path": "README.md"}]}],
    ) is None


# contract-test: supporting surface=gui.web assertions=projects.files.search-scoped
@pytest.mark.parametrize("path", ["../README.md", "/README.md", "docs/../../README.md", "docs\\README.md"])
def test_invalid_file_location_cannot_be_published(path):
    assert build_project_file_reference_preview(
        context=context(), result_status="completed",
        completed_results=[{"status": "completed", "source_id": "remote", "matches": [{"path": path}]}],
    ) is None


# contract-test: supporting surface=gui.web assertions=projects.files.search-scoped,projects.files.no-server-decryption-authority
@pytest.mark.asyncio
async def test_publication_rechecks_current_project_and_strips_unexpected_fields(monkeypatch, turn_key_import):
    calls = []
    module = ModuleType("backend.core.api.app.services.embed_service")

    class EmbedService:
        def __init__(self, *_args):
            pass

        async def create_embeds_from_skill_results(self, **kwargs):
            calls.append(kwargs)
            return {"embed_reference": "reference"}

    module.EmbedService = EmbedService
    monkeypatch.setitem(sys.modules, module.__name__, module)
    request = SimpleNamespace(active_project_focus={"project_id": "project"}, is_async_skill_continuation=True,
                              chat_id="chat", message_id="message", user_id="owner", user_id_hash="owner-hash")
    preview = {"project_id": "other-project", "skill_id": "read", "query": "README.md",
               "results": [{"project_id": "project", "path": "README.md", "embed_id": "original",
                            "content": "DO_NOT_COPY", "snippet": "DO_NOT_COPY"}]}
    class Cache:
        async def get(self, _key):
            return "message"

    args = dict(preview=preview, request_data=request, cache_service=Cache(), directus_service=object(),
                encryption_service=object(), user_vault_key_id="vault-key", task_id="task", log_prefix="")
    assert await publish_project_file_reference_preview(**args) is None
    assert calls == []
    preview["project_id"] = "project"
    assert await publish_project_file_reference_preview(**args) == "reference"
    assert calls[0]["results"] == [{"project_id": "project", "path": "README.md", "embed_id": "original"}]
    assert "DO_NOT_COPY" not in json.dumps(calls[0])
    preview.update(skill_id="search", search_target="content", query="needle")
    assert await publish_project_file_reference_preview(**args) == "reference"
    assert calls[1]["request_metadata"] == {"query": "needle", "search_target": "content"}
    assert "DO_NOT_COPY" not in json.dumps(calls[1])


# contract-test: supporting surface=gui.web assertions=projects.focus.inferred-consent,projects.files.search-scoped
@pytest.mark.asyncio
async def test_new_turn_after_dispatch_prevents_reference_publication(monkeypatch, turn_key_import):
    from backend.shared.python_utils.chat_recovery_context import RequiredRecoveryOutputError

    module = ModuleType("backend.core.api.app.services.embed_service")
    class EmbedService:
        def __init__(self, *_args):
            pytest.fail("A superseded completion must not enter embed publication")
    module.EmbedService = EmbedService
    monkeypatch.setitem(sys.modules, module.__name__, module)
    class Cache:
        async def get(self, _key):
            return "new-user-turn"
    request = SimpleNamespace(active_project_focus={"project_id": "project"}, is_async_skill_continuation=True,
                              chat_id="chat", message_id="old-user-turn", user_id="owner", user_id_hash="owner-hash")
    with pytest.raises(RequiredRecoveryOutputError, match="superseded user turn"):
        await publish_project_file_reference_preview(
            preview={"project_id": "project", "skill_id": "read",
                     "results": [{"project_id": "project", "path": "README.md", "embed_id": "original"}]},
            request_data=request, cache_service=Cache(), directus_service=object(),
            encryption_service=object(), user_vault_key_id="vault-key", task_id="task", log_prefix="",
        )
