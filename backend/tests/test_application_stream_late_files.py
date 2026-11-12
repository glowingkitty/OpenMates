"""Stream-consumer coverage: every streamed app file becomes a code embed and joins the application."""

import asyncio
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

from backend.apps.ai.processing.preprocessor import PreprocessingResult
from backend.apps.ai.skills.ask_skill import AskSkillRequest
from backend.apps.ai.tasks import stream_consumer
from backend.core.api.app.services.embed_service import EmbedService

FILES = [
    ("json", "package.json", '{"name":"recipes","scripts":{"dev":"vite"},"dependencies":{"react":"^18","vite":"^5"}}\n'),
    ("javascript", "vite.config.js", "import { defineConfig } from 'vite';\nexport default defineConfig({});\n"),
    ("html", "index.html", '<!doctype html>\n<div id="root"></div>\n<script type="module" src="/src/main.jsx"></script>\n'),
    ("css", "src/index.css", "body {\n  margin: 0;\n  font-family: sans-serif;\n}\n"),
    ("javascript", "src/main.jsx", "import App from './App.jsx';\nconsole.log(App);\n"),
    ("javascript", "src/App.jsx", "export default function App() {\n  return null;\n}\n"),
]


def _gemini_like_tokens() -> list[str]:
    tokens = ["Here is a simple recipe web app.\n\n"]
    for language, path, content in FILES:
        tokens += ["```", f"{language}:{path}\n{content}", "```\n\n"]
    return tokens


def _gemini_merged_fence_tokens() -> list[str]:
    """The end of one file and the opening fence of the next arrive in one chunk (real dev run)."""
    tokens = ["Here is a simple recipe web app.\n\n", "```"]
    for index, (language, path, content) in enumerate(FILES):
        tokens.append(f"{language}:{path}\n{content}")
        tokens.append("```\n\n```" if index < len(FILES) - 1 else "```\n\n")
    return tokens


@pytest.mark.parametrize("tokens", [_gemini_like_tokens, _gemini_merged_fence_tokens])
# contract-test: supporting surface=rest_api assertions=chats.rendering.assistant-document-convergence
def test_gemini_chunked_application_files_all_join_the_application(monkeypatch, tokens) -> None:
    created_apps: list[list[dict]] = []
    app_embed_ids: list[str | None] = []
    counter = {"n": 0}

    async def main_stream(**_kwargs):
        for token in tokens():
            yield token

    async def create_placeholder(*_args, **kwargs):
        counter["n"] += 1
        embed_id = f"file-{counter['n']}"
        return {"embed_id": embed_id, "embed_reference": f'{{"type":"code","embed_id":"{embed_id}"}}'}

    async def create_application(*_args, **kwargs):
        created_apps.append(list(kwargs["file_refs"]))
        app_embed_ids.append(kwargs.get("embed_id"))
        return {"embed_id": "app-1", "embed_reference": '{"type":"application","embed_id":"app-1"}'}

    class FakeEmbedService(EmbedService):
        create_code_embed_placeholder = AsyncMock(side_effect=create_placeholder)
        update_code_embed_content = AsyncMock(return_value=True)
        create_application_embed = AsyncMock(side_effect=create_application)
        update_application_embed = AsyncMock(return_value=True)

        def __init__(self, *_args, **_kwargs):
            pass

    monkeypatch.setattr(stream_consumer, "handle_main_processing", main_stream)
    monkeypatch.setattr(stream_consumer.celery_config.app, "AsyncResult",
                        lambda _: SimpleNamespace(state="STARTED"))
    monkeypatch.setattr(stream_consumer, "_mark_code_embed_assistant_runnable", AsyncMock())
    monkeypatch.setattr("backend.core.api.app.services.embed_service.EmbedService", FakeEmbedService)
    request = AskSkillRequest(
        chat_id="chat-1", message_id="message-1", user_id="user-1",
        user_id_hash="hash-1", message_history=[], is_incognito=True,
    )
    response, *_ = asyncio.run(stream_consumer._consume_main_processing_stream(
        task_id="task-1", request_data=request,
        preprocessing_result=PreprocessingResult(can_proceed=True),
        base_instructions={}, directus_service=SimpleNamespace(),
        encryption_service=SimpleNamespace(), user_vault_key_id="vault-1",
        all_mates_configs=[], discovered_apps_metadata={}, cache_service=AsyncMock(),
    ))

    assert FakeEmbedService.create_code_embed_placeholder.await_count == 6
    for _language, path, content in FILES:
        assert content.strip().splitlines()[0] not in response
        assert f":{path}" not in response
    assert "javascript:" not in response
    assert response.count('"type":"code"') == 6
    assert response.count('"type":"application"') == 1
    # Created once script entries exist (not at index.html), then refreshed in place with the late file.
    assert [len(refs) for refs in created_apps] == [5, 6]
    assert app_embed_ids == [None, "app-1"]
    assert [ref["path"] for ref in created_apps[-1]] == [path for _l, path, _c in FILES]
