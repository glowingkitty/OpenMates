# contract-test-file: infrastructure
# backend/tests/test_skill_executor_context_preserved.py
#
# Regression tests for production PDF failures: pdf.read/pdf.view were called
# with a page list, the executor split the list into per-page requests and the
# server-injected file index and Vault key were left off the top level, so the
# skill answered "No PDF embed found ... Available: []".
#
# Architecture: docs/architecture/apps/app-skills.md

import sys
import types

import pytest

from tests.runtime_import_stubs import install_code_route_import_stubs

install_code_route_import_stubs()

skill_registry_module = types.ModuleType("backend.core.api.app.services.skill_registry")
skill_registry_module.get_global_registry = lambda: None
skill_registry_module.build_skill_registry = lambda **_kwargs: (None, {})
skill_registry_module.set_global_registry = lambda _registry: None
sys.modules["backend.core.api.app.services.skill_registry"] = skill_registry_module

from backend.apps.ai.processing import skill_executor  # noqa: E402
from backend.apps.ai.processing.skill_executor import execute_skill_with_multiple_requests  # noqa: E402

FILE_INDEX = {"Nova 42 Leistungen und Nutzen.pdf": "05de76ab-d283-4194-b8ea-d6e1db3ce536"}


def _capture_dispatch(monkeypatch: pytest.MonkeyPatch) -> list[dict]:
    dispatched: list[dict] = []

    async def fake_execute_skill(app_id, skill_id, arguments, *_args, **_kwargs):
        dispatched.append(arguments)
        return {"results": []}

    monkeypatch.setattr(skill_executor, "execute_skill", fake_execute_skill)
    return dispatched


@pytest.mark.asyncio
@pytest.mark.parametrize("skill_id", ["read", "view"])
async def test_pdf_page_list_stays_one_call_with_file_index(monkeypatch, skill_id: str) -> None:
    dispatched = _capture_dispatch(monkeypatch)

    await execute_skill_with_multiple_requests(
        "pdf",
        skill_id,
        {
            "file_path": "Nova 42 Leistungen und Nutzen.pdf",
            "pages": [1, 2],
            "_file_path_index": FILE_INDEX,
            "_user_vault_key_id": "vault-key",
        },
    )

    assert len(dispatched) == 1
    assert dispatched[0]["pages"] == [1, 2]
    assert dispatched[0]["_file_path_index"] == FILE_INDEX
    assert dispatched[0]["_user_vault_key_id"] == "vault-key"
    assert "requests" not in dispatched[0]


@pytest.mark.asyncio
async def test_expanded_list_arguments_keep_server_context_at_top_level(monkeypatch) -> None:
    dispatched = _capture_dispatch(monkeypatch)

    await execute_skill_with_multiple_requests(
        "web",
        "search",
        {
            "query": ["first", "second"],
            "_file_path_index": FILE_INDEX,
            "_user_vault_key_id": "vault-key",
        },
    )

    assert len(dispatched) == 1
    assert [request["query"] for request in dispatched[0]["requests"]] == ["first", "second"]
    assert dispatched[0]["_file_path_index"] == FILE_INDEX
    assert dispatched[0]["_user_vault_key_id"] == "vault-key"
