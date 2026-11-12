# backend/apps/ai/tests/test_code_run_skill_execution.py
#
# Contract tests for assistant-dispatched Code Run.
# The assistant may run code it created or edited in the current turn, but the
# backend must derive that authorization from cache markers and enforce a bounded
# rerun limit before starting E2B.

from __future__ import annotations

import sys
from types import ModuleType, SimpleNamespace

import pytest

from backend.apps.code.skills import run_code_skill
from backend.apps.code.skills.run_code_skill import (
    CODE_RUN_ASSISTANT_MAX_AUTO_RUNS,
    RunCodeRequest,
    RunCodeSkill,
    mark_assistant_code_run_authorized,
)


CHAT_ID = "chat-1"
MESSAGE_ID = "message-1"
TARGET_EMBED_ID = "embed-code-1"
USER_ID = "user-1"
VAULT_KEY_ID = "vault-key"


class FakeCache:
    def __init__(self, user_data: dict[str, object] | None = None):
        self.values: dict[str, object] = {}
        self.user_data = {"credits": 10} if user_data is None else user_data

    async def get(self, key: str):
        return self.values.get(key)

    async def set(self, key: str, value: object, ttl: int | None = None):
        self.values[key] = value
        return True

    async def get_user_by_id(self, user_id: str):
        assert user_id == USER_ID
        return self.user_data


def _skill() -> RunCodeSkill:
    return RunCodeSkill(
        app=SimpleNamespace(),
        app_id="code",
        skill_id="run",
        skill_name="Run code",
        skill_description="Run code",
    )


# contract-test: direct surface=rest_api assertions=code-run.assistant.auto-debug-bounded
@pytest.mark.anyio
async def test_assistant_code_run_rejects_unmarked_user_code() -> None:
    result = await _skill().execute(
        RunCodeRequest(chat_id=CHAT_ID, target_embed_id=TARGET_EMBED_ID),
        user_id=USER_ID,
        user_vault_key_id=VAULT_KEY_ID,
        message_id=MESSAGE_ID,
        cache_service=FakeCache(),
        encryption_service=object(),
    )

    assert result.status == "requires_confirmation"
    assert result.execution_id is None
    assert "created or edited" in (result.error or "")


# contract-test: direct surface=rest_api assertions=code-run.assistant.auto-debug-bounded
@pytest.mark.anyio
async def test_assistant_code_run_ignores_forged_confirmation_flag() -> None:
    result = await _skill().execute(
        RunCodeRequest(
            chat_id=CHAT_ID,
            target_embed_id=TARGET_EMBED_ID,
            user_confirmed_unmodified_code=True,
        ),
        user_id=USER_ID,
        user_vault_key_id=VAULT_KEY_ID,
        message_id=MESSAGE_ID,
        cache_service=FakeCache(),
        encryption_service=object(),
    )

    assert result.status == "requires_confirmation"
    assert result.execution_id is None
    assert "created or edited" in (result.error or "")


# contract-test: direct surface=rest_api assertions=code-run.output.chat-bound-encrypted,code-run.assistant.auto-debug-bounded
@pytest.mark.anyio
async def test_assistant_code_run_rejects_mismatched_tool_chat_id() -> None:
    result = await _skill().execute(
        RunCodeRequest(chat_id="other-chat", target_embed_id=TARGET_EMBED_ID),
        user_id=USER_ID,
        user_vault_key_id=VAULT_KEY_ID,
        chat_id=CHAT_ID,
        message_id=MESSAGE_ID,
        cache_service=FakeCache(),
        encryption_service=object(),
    )

    assert result.status == "error"
    assert result.execution_id is None
    assert "does not match" in (result.error or "")


# contract-test: direct surface=rest_api assertions=code-run.assistant.auto-debug-bounded,code-run.execution.stream-status-visible,code-run.surface-parity
@pytest.mark.anyio
async def test_assistant_code_run_dispatches_marked_current_turn_code(monkeypatch: pytest.MonkeyPatch) -> None:
    cache = FakeCache()
    await mark_assistant_code_run_authorized(
        cache,
        chat_id=CHAT_ID,
        message_id=MESSAGE_ID,
        target_embed_id=TARGET_EMBED_ID,
        action="created",
    )
    dispatch_calls: list[dict[str, object]] = []

    class FakeDirectusService:
        async def get_user_fields_direct(self, *_args, **_kwargs):
            raise AssertionError("Assistant Code Run must use cached user credits, not Directus cleartext credits.")

    async def fake_collect_code_files(**kwargs):
        assert kwargs["chat_id"] == CHAT_ID
        assert kwargs["target_embed_id"] == TARGET_EMBED_ID
        return ([{"path": "main.py", "content": "print('ok')", "language": "python", "is_target": True}], "main.py")

    async def fake_start_code_run_execution(**kwargs):
        dispatch_calls.append(kwargs)
        assert kwargs["current_user"].id == USER_ID
        assert kwargs["current_user"].credits == 10
        assert kwargs["chat_id"] == CHAT_ID
        assert kwargs["target_embed_id"] == TARGET_EMBED_ID
        assert kwargs["message_id"] == MESSAGE_ID
        return SimpleNamespace(
            execution_id="execution-1",
            status="queued",
            target_filename="main.py",
            files=["main.py"],
            credits_per_minute=5,
        )

    monkeypatch.setattr(run_code_skill, "create_directus_service", lambda **_kwargs: FakeDirectusService())
    monkeypatch.setattr(run_code_skill, "collect_code_files_for_assistant", fake_collect_code_files)
    monkeypatch.setattr(run_code_skill, "start_code_run_for_assistant", fake_start_code_run_execution)

    result = await _skill().execute(
        RunCodeRequest(chat_id=CHAT_ID, target_embed_id=TARGET_EMBED_ID),
        user_id=USER_ID,
        user_vault_key_id=VAULT_KEY_ID,
        message_id=MESSAGE_ID,
        cache_service=cache,
        encryption_service=object(),
    )

    assert result.status == "processing"
    assert result.execution_id == "execution-1"
    assert result.task_id == "execution-1"
    assert result.status_path == "/v1/code/run/execution-1"
    assert dispatch_calls


@pytest.mark.parametrize(
    ("entry_path", "language", "source", "supporting_files"),
    [
        (
            "main.py",
            "python",
            "import sympy as sp\nimport numpy as np\nimport matplotlib.pyplot as plt\n"
            "from IPython.display import display\n"
            "x = sp.symbols('x')\ndisplay(sp.integrate(x**2, (x, 0, 1)))\n"
            "print(np.mean([1, 2, 3]))\nplt.plot([0, 1], [0, 1])\nplt.savefig('chart.png')\n",
            [{"path": "requirements.txt", "code": "sympy\nnumpy\nmatplotlib\nIPython\n"}],
        ),
        ("main.rs", "rust", 'fn main() { println!("sum={}", (1..=10).sum::<u32>()); }', []),
    ],
)
@pytest.mark.anyio
# contract-test: direct surface=rest_api assertions=code-run.assistant.auto-debug-bounded,code-run.execution.e2b-only,code-run.surface-parity
async def test_assistant_code_run_creates_inline_code_embed_before_dispatch(
    monkeypatch: pytest.MonkeyPatch,
    entry_path: str,
    language: str,
    source: str,
    supporting_files: list[dict[str, str]],
) -> None:
    cache = FakeCache()
    dispatch_calls: list[dict[str, object]] = []
    created_calls: list[dict[str, object]] = []
    finalized_calls: list[dict[str, object]] = []

    class FakeDirectusService:
        async def get_user_fields_direct(self, *_args, **_kwargs):
            raise AssertionError("Assistant Code Run must use cached user credits, not Directus cleartext credits.")

    class FakeEmbedService:
        def __init__(self, **kwargs):
            assert kwargs["cache_service"] is cache

        async def create_code_embed_placeholder(self, **kwargs):
            created_calls.append(kwargs)
            assert kwargs["chat_id"] == CHAT_ID
            assert kwargs["message_id"] == MESSAGE_ID
            assert kwargs["user_id"] == USER_ID
            assert kwargs["user_vault_key_id"] == VAULT_KEY_ID
            return {"embed_id": TARGET_EMBED_ID if kwargs["filename"] == entry_path else "manifest-embed"}

        async def update_code_embed_content(self, **kwargs):
            finalized_calls.append(kwargs)
            assert kwargs["status"] == "finished"
            return True

    embed_module = ModuleType("backend.core.api.app.services.embed_service")
    embed_module.EmbedService = FakeEmbedService
    monkeypatch.setitem(sys.modules, embed_module.__name__, embed_module)

    async def fake_start_code_run_execution(**kwargs):
        dispatch_calls.append(kwargs)
        assert len(finalized_calls) == 1 + len(supporting_files)
        assert kwargs["assistant_async_task"] is True
        assert kwargs["files"][0]["content"] == source
        assert kwargs["files"][0]["language"] == language
        assert await cache.get(run_code_skill.assistant_code_run_authorization_key(
            CHAT_ID, MESSAGE_ID, TARGET_EMBED_ID,
        ))
        assert kwargs["files"][0]["path"] == entry_path
        assert kwargs["target_path"] == entry_path
        assert kwargs["target_embed_id"] == TARGET_EMBED_ID
        return SimpleNamespace(
            execution_id="execution-inline",
            status="queued",
            target_filename=entry_path,
            files=[entry_path, *[file["path"] for file in supporting_files]],
            credits_per_minute=5,
        )

    monkeypatch.setattr(run_code_skill, "create_directus_service", lambda **_kwargs: FakeDirectusService())
    monkeypatch.setattr(run_code_skill, "start_code_run_for_assistant", fake_start_code_run_execution)

    result = await _skill().execute(
        RunCodeRequest(entry_path=entry_path, files=[{"path": entry_path, "code": source}, *supporting_files]),
        user_id=USER_ID,
        user_vault_key_id=VAULT_KEY_ID,
        chat_id=CHAT_ID,
        message_id=MESSAGE_ID,
        cache_service=cache,
        encryption_service=object(),
    )

    assert result.status == "processing"
    assert result.execution_id == "execution-inline"
    assert result.embed_id == TARGET_EMBED_ID
    assert result.target_embed_id == TARGET_EMBED_ID
    assert result.created_embed_ids == [TARGET_EMBED_ID, *(["manifest-embed"] if supporting_files else [])]
    assert created_calls[0]["language"] == language
    assert created_calls[0]["code_content"] == source
    assert created_calls
    assert dispatch_calls


# contract-test: direct surface=rest_api assertions=code-run.assistant.auto-debug-bounded
@pytest.mark.anyio
async def test_assistant_code_run_stops_after_two_unprompted_reruns(monkeypatch: pytest.MonkeyPatch) -> None:
    cache = FakeCache()
    await mark_assistant_code_run_authorized(
        cache,
        chat_id=CHAT_ID,
        message_id=MESSAGE_ID,
        target_embed_id=TARGET_EMBED_ID,
        action="edited",
    )

    class FakeDirectusService:
        async def get_user_fields_direct(self, *_args, **_kwargs):
            raise AssertionError("Assistant Code Run must use cached user credits, not Directus cleartext credits.")

    async def fake_collect_code_files(**_kwargs):
        return ([{"path": "main.py", "content": "print('ok')", "language": "python", "is_target": True}], "main.py")

    async def fake_start_code_run_execution(**_kwargs):
        return SimpleNamespace(
            execution_id="execution-ok",
            status="queued",
            target_filename="main.py",
            files=["main.py"],
            credits_per_minute=5,
        )

    monkeypatch.setattr(run_code_skill, "create_directus_service", lambda **_kwargs: FakeDirectusService())
    monkeypatch.setattr(run_code_skill, "collect_code_files_for_assistant", fake_collect_code_files)
    monkeypatch.setattr(run_code_skill, "start_code_run_for_assistant", fake_start_code_run_execution)

    for _ in range(CODE_RUN_ASSISTANT_MAX_AUTO_RUNS):
        result = await _skill().execute(
            RunCodeRequest(chat_id=CHAT_ID, target_embed_id=TARGET_EMBED_ID),
            user_id=USER_ID,
            user_vault_key_id=VAULT_KEY_ID,
            message_id=MESSAGE_ID,
            cache_service=cache,
            encryption_service=object(),
        )
        assert result.status == "processing"

    result = await _skill().execute(
        RunCodeRequest(chat_id=CHAT_ID, target_embed_id=TARGET_EMBED_ID),
        user_id=USER_ID,
        user_vault_key_id=VAULT_KEY_ID,
        message_id=MESSAGE_ID,
        cache_service=cache,
        encryption_service=object(),
    )

    assert result.status == "requires_confirmation"
    assert "two unprompted reruns" in (result.error or "")


# contract-test: direct surface=rest_api assertions=code-run.assistant.auto-debug-bounded
@pytest.mark.anyio
async def test_assistant_inline_code_run_stops_after_two_unprompted_reruns(monkeypatch: pytest.MonkeyPatch) -> None:
    cache = FakeCache()

    class FakeDirectusService:
        async def get_user_fields_direct(self, *_args, **_kwargs):
            raise AssertionError("Assistant Code Run must use cached user credits, not Directus cleartext credits.")

    async def fake_create_code_embeds_for_assistant(**_kwargs):
        return TARGET_EMBED_ID, [TARGET_EMBED_ID]

    async def fake_start_code_run_execution(**_kwargs):
        return SimpleNamespace(
            execution_id="execution-inline",
            status="queued",
            target_filename="main.py",
            files=["main.py"],
            credits_per_minute=5,
        )

    monkeypatch.setattr(run_code_skill, "create_directus_service", lambda **_kwargs: FakeDirectusService())
    monkeypatch.setattr(run_code_skill, "create_code_embeds_for_assistant", fake_create_code_embeds_for_assistant)
    monkeypatch.setattr(run_code_skill, "start_code_run_for_assistant", fake_start_code_run_execution)

    request = RunCodeRequest(entry_path="main.py", files=[{"path": "main.py", "code": "print('ok')"}])
    for _ in range(CODE_RUN_ASSISTANT_MAX_AUTO_RUNS):
        result = await _skill().execute(
            request,
            user_id=USER_ID,
            user_vault_key_id=VAULT_KEY_ID,
            chat_id=CHAT_ID,
            message_id=MESSAGE_ID,
            cache_service=cache,
            encryption_service=object(),
        )
        assert result.status == "processing"

    result = await _skill().execute(
        request,
        user_id=USER_ID,
        user_vault_key_id=VAULT_KEY_ID,
        chat_id=CHAT_ID,
        message_id=MESSAGE_ID,
        cache_service=cache,
        encryption_service=object(),
    )

    assert result.status == "requires_confirmation"
    assert "two unprompted reruns" in (result.error or "")


# contract-test: direct surface=rest_api assertions=code-run.tests.project-snapshot
@pytest.mark.anyio
async def test_test_run_does_not_create_chat_code_embeds_for_project_snapshot(monkeypatch: pytest.MonkeyPatch) -> None:
    cache = FakeCache()
    dispatch_calls: list[dict[str, object]] = []

    class FakeDirectusService:
        async def get_user_fields_direct(self, *_args, **_kwargs):
            raise AssertionError("Assistant Code Run must use cached user credits.")

    async def forbidden_create(**_kwargs):
        raise AssertionError("test_run must not create chat code embeds for the Project snapshot")

    async def fake_authorize(*_args, **_kwargs):
        return True, "ok"

    async def fake_prepare(self, request, **_kwargs):
        return request.model_copy(update={"target": "e2b"}), None

    async def fake_start(**kwargs):
        dispatch_calls.append(kwargs)
        return SimpleNamespace(
            execution_id="execution-test", status="queued", target_filename="web-app/tests/app.spec.ts",
            files=["web-app/index.html", "web-app/tests/app.spec.ts"], credits_per_minute=5,
        )

    monkeypatch.setattr(run_code_skill, "create_directus_service", lambda **_kwargs: FakeDirectusService())
    monkeypatch.setattr(run_code_skill, "create_code_embeds_for_assistant", forbidden_create)
    monkeypatch.setattr(run_code_skill, "start_code_run_for_assistant", fake_start)
    monkeypatch.setattr(run_code_skill, "_authorize_assistant_test_run", fake_authorize)
    monkeypatch.setattr(run_code_skill.RunCodeSkill, "_prepare_test_run", fake_prepare)

    result = await _skill().execute(
        RunCodeRequest(
            entry_path="web-app/tests/app.spec.ts",
            files=[
                {"path": "web-app/index.html", "code": "<h1>Recipes</h1>"},
                {"path": "web-app/tests/app.spec.ts", "code": "test('x', () => {})"},
            ],
            test_run={
                "kind": "browser",
                "revisions": [{"path": "web-app/index.html", "revision": "r1"}, {"path": "web-app/tests/app.spec.ts", "revision": "r2"}],
                "test_command": {"argv": ["npx", "playwright", "test"], "cwd": "web-app"},
            },
        ),
        user_id=USER_ID, user_vault_key_id=VAULT_KEY_ID, chat_id=CHAT_ID, message_id=MESSAGE_ID,
        cache_service=cache, encryption_service=object(),
    )

    assert result.status == "processing"
    assert result.created_embed_ids == []
    assert dispatch_calls[0]["target_embed_id"] is None
    assert [file["path"] for file in dispatch_calls[0]["files"]] == ["web-app/index.html", "web-app/tests/app.spec.ts"]


# contract-test: direct surface=rest_api assertions=code-run.tests.project-snapshot
def test_test_run_accepts_package_json_scripts_but_plain_run_refuses_them() -> None:
    """A hosted Vite app always has npm scripts; only test runs may carry them."""
    package_json = '{"scripts": {"dev": "vite"}, "dependencies": {"react": "^18.3.1"}}'
    files = [
        {"path": "web-app/package.json", "code": package_json},
        {"path": "web-app/tests/app.spec.js", "code": "test('x', () => {})"},
    ]
    test_run = {
        "kind": "browser",
        "revisions": [{"path": "web-app/package.json", "revision": "r1"}],
        "test_command": {"argv": ["npx", "playwright", "test"], "cwd": "web-app"},
    }
    collected, target = run_code_skill.collect_inline_code_files_for_assistant(
        RunCodeRequest(entry_path="web-app/tests/app.spec.js", files=files, test_run=test_run)
    )
    assert target == "web-app/tests/app.spec.js"
    assert {file["path"] for file in collected} == {"web-app/package.json", "web-app/tests/app.spec.js"}
    with pytest.raises(run_code_skill.CodeRunInlineValidationError, match="scripts are not supported"):
        run_code_skill.collect_inline_code_files_for_assistant(
            RunCodeRequest(entry_path="web-app/tests/app.spec.js", files=files)
        )
