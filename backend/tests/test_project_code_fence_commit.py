"""Files the assistant writes in a cloud Project chat are normal code embeds that are the Project files.

Marco, 22 Nov (receipt ba57243847b51eee): one flow, the same as code in a normal
chat; no separate "File changed" entries. Plan: project-files-as-chat-code-embeds.
"""

from __future__ import annotations

from types import SimpleNamespace
from typing import Any

import pytest

from backend.apps.ai.processing import project_code_fence_commit as fence
from backend.apps.ai.processing.project_file_tools import build_project_file_tools, build_project_focus_prompt

FILE_ID = "6f1c2a7e-1b2c-5d3e-8f40-123456789abc"


def _request(**extra: Any) -> SimpleNamespace:
    return SimpleNamespace(active_project_focus={"project_id": "p-1", "team_id": None}, user_id="u-1",
                           project_code_fences=True, project_fence_files=None, **extra)


class _Sandbox:
    """Records sandbox operations and answers them like the Project sandbox /v1/op."""

    def __init__(self, answers: dict[str, list[dict[str, Any]]]) -> None:
        self.answers = answers
        self.calls: list[tuple[str, dict[str, Any]]] = []
        self.secrets: list[Any] = []

    async def __call__(self, request_data, focus, operation, arguments, **kwargs):
        self.calls.append((operation, arguments))
        self.secrets.append(kwargs.get("secrets_manager"))
        return self.answers[operation].pop(0)


KW = dict(cache_service=None, directus_service=None, log_prefix="")


# contract-test: supporting surface=rest_api assertions=projects.agentic.files-as-code-embeds,projects.sandbox.write-back
@pytest.mark.asyncio
async def test_a_closed_fence_is_created_as_the_project_file(monkeypatch) -> None:
    sandbox = _Sandbox({"create_file": [{"embed_id": FILE_ID, "revision": 1, "created": True},
                                        {"embed_id": FILE_ID, "revision": 1, "created": True}]})
    monkeypatch.setattr(fence, "_sandbox_op", sandbox)
    request = _request()
    committed = await fence.commit_code_fence(request, path="web-app/src/App.tsx", content="export {}\n", **KW)
    assert committed == {"embed_id": FILE_ID, "path": "web-app/src/App.tsx", "created": True}
    assert sandbox.calls == [("create_file", {"path": "web-app/src/App.tsx", "expected_base": None,
                                              "content": "export {}\n"})]
    # Saving does not decide what the reply shows: the chat code embed stays (the sandbox has no chat key).
    assert request.project_fence_files is None
    # Recipe proof 22 Nov: without the secrets manager the first file of a turn could not start the sandbox.
    vault = object()
    await fence.commit_code_fence(_request(), path="web-app/b.ts", content="x", secrets_manager=vault, **KW)
    assert sandbox.secrets[-1] is vault


# contract-test: supporting surface=rest_api assertions=projects.agentic.files-as-code-embeds,projects.sandbox.write-back
@pytest.mark.asyncio
async def test_a_fence_for_an_existing_file_becomes_a_revision_of_it(monkeypatch) -> None:
    sandbox = _Sandbox({
        "create_file": [{"status": "error", "code": "file_exists", "reason": "exists"}],
        "read_text": [{"path": "web-app/a.ts", "embed_id": FILE_ID, "content": "a\nb\n", "expected_base": "base-1"}],
        "update_file": [{"embed_id": FILE_ID, "revision": 2}],
    })
    monkeypatch.setattr(fence, "_sandbox_op", sandbox)
    committed = await fence.commit_code_fence(_request(), path="web-app/a.ts", content="a\nc\n", **KW)
    assert committed == {"embed_id": FILE_ID, "path": "web-app/a.ts", "created": False}
    operation, arguments = sandbox.calls[-1]
    assert operation == "update_file" and arguments["expected_base"] == "base-1"
    assert "-b\n" in arguments["patch"] and "+c\n" in arguments["patch"]


# contract-test: supporting surface=rest_api assertions=projects.agentic.files-as-code-embeds
@pytest.mark.asyncio
async def test_a_refused_commit_leaves_the_fence_a_chat_embed(monkeypatch) -> None:
    sandbox = _Sandbox({"create_file": [{"status": "error", "code": "path_not_allowed", "reason": "no"}]})
    monkeypatch.setattr(fence, "_sandbox_op", sandbox)
    request = _request()
    assert await fence.commit_code_fence(request, path="web-app/a.ts", content="x", **KW) is None
    assert request.project_fence_files is None
    # Without code-fence mode (no cloud Project focus or no sandbox consent) nothing is sent to a sandbox.
    assert await fence.commit_code_fence(SimpleNamespace(active_project_focus=None), path="a/b", content="x", **KW) is None
    off = _request()
    off.project_code_fences = False
    assert await fence.commit_code_fence(off, path="a/b", content="x", **KW) is None
    assert len(sandbox.calls) == 1
    assert fence.hosted_project_focus(SimpleNamespace(active_project_focus={"project_id": "p", "source_id": "m"})) is None


# contract-test: supporting surface=rest_api assertions=projects.agentic.files-as-code-embeds,projects.sandbox.write-back
@pytest.mark.asyncio
async def test_a_diff_fence_updates_the_project_file_against_its_revision(monkeypatch) -> None:
    sandbox = _Sandbox({
        "read_text": [{"path": "web-app/a.ts", "embed_id": FILE_ID, "content": "a\n", "expected_base": "base-7"}],
        "update_file": [{"embed_id": FILE_ID, "revision": 8}],
    })
    monkeypatch.setattr(fence, "_sandbox_op", sandbox)
    patch = "--- a/web-app/a.ts\n+++ b/web-app/a.ts\n@@ -1 +1 @@\n-a\n+b\n"
    applied = await fence.apply_project_diff_fence(_request(), path="web-app/a.ts", patch=patch, **KW)
    assert applied and applied["embed_id"] == FILE_ID
    assert sandbox.calls[-1] == ("update_file", {"path": "web-app/a.ts", "expected_base": "base-7", "patch": patch})


# contract-test: supporting surface=rest_api assertions=projects.agentic.files-as-code-embeds
def test_inline_links_point_at_the_chat_code_embed_of_the_file() -> None:
    request = _request()
    fence.remember_shown_file(request, "web-app/src/App.tsx", FILE_ID)
    fence.remember_shown_file(request, "web-app/none.ts", None)
    assert request.project_fence_files == {"web-app/src/App.tsx": FILE_ID}
    text = "See [App.tsx](embed:web-app/src/App.tsx#L3) and [x](embed:web-app/other.ts)."
    linked = fence.link_project_file_references(text, {"web-app/src/App.tsx": FILE_ID})
    assert linked == f"See [App.tsx](embed:{FILE_ID}#L3) and [x](embed:web-app/other.ts)."
    assert fence.project_file_path("web-app/src/App.tsx") == "web-app/src/App.tsx"
    for bad in ("App.tsx", "/etc/passwd", "web-app/../x", "a\\b", None):
        assert fence.project_file_path(bad) is None


# contract-test: supporting surface=rest_api assertions=projects.agentic.files-as-code-embeds
def test_cloud_project_chats_write_files_as_code_blocks() -> None:
    names = {tool["function"]["name"] for tool in build_project_file_tools(code_fences=True)}
    assert "project_create_file" not in names and "project_update_file" not in names
    assert {tool["function"]["name"] for tool in build_project_file_tools()} >= {"project_create_file",
                                                                                 "project_update_file"}
    prompt = build_project_focus_prompt({"instruction": "Work in this Project."}, [], code_fences=True)
    assert "```tsx:web-app/src/App.tsx" in prompt
    assert "```diff:" in prompt
    # Recipe proof 22 Nov: the model ran the test before writing it, then wrote it in the final answer.
    assert "before you call code-run" in prompt and "final answer is never run" in prompt
    assert "[App.tsx](embed:web-app/src/App.tsx)" in prompt
    assert "never emit an application_preview block" in prompt
