# contract-test-file: infrastructure
# backend/tests/test_groq_client_retry_config.py
#
# Verify bounded safety requests retain their configured SDK retry limits while
# every async transport is closed on its owning loop. Celery creates a fresh
# loop per task, so provider pools must never survive across worker turns.
# Architecture: specifications/architecture/app-skill-execution/specification.yml

from types import SimpleNamespace

import pytest

from backend.apps.ai.llm_providers import groq_client


@pytest.fixture
def configured_groq(monkeypatch):
    monkeypatch.setattr(groq_client, "_groq_client_initialized", True)
    monkeypatch.setattr(groq_client, "_groq_api_key", "synthetic-test-key")
    monkeypatch.setattr(groq_client, "_groq_base_url", None)


# contract-test: supporting surface=rest_api assertions=app-skills.output.bounded-failure
@pytest.mark.asyncio
@pytest.mark.parametrize("reasoning_effort", ["low", "medium", "high"])
@pytest.mark.parametrize("max_retries", [None, 0])
@pytest.mark.parametrize("base_url", [None, "", "https://provider.example/v1"])
async def test_groq_request_preserves_retry_options_and_closes_client(
    monkeypatch, configured_groq, reasoning_effort, max_retries, base_url,
):
    monkeypatch.setattr(groq_client, "_groq_base_url", base_url)
    options, calls, closed = [], [], []

    class Client:
        def __init__(self, **kwargs):
            options.append(kwargs)
            self.chat = SimpleNamespace(completions=self)

        async def create(self, **kwargs):
            calls.append(kwargs)
            return SimpleNamespace(choices=[SimpleNamespace(message=SimpleNamespace(tool_calls=None, content="ok"))], usage=None)

        async def close(self):
            closed.append(True)

    monkeypatch.setattr(groq_client, "AsyncGroq", Client)
    result = await groq_client.invoke_groq_chat_completions(
        task_id="test", model_id="model", messages=[{"role": "user", "content": "classify"}],
        max_retries=max_retries, reasoning_effort=reasoning_effort,
    )
    expected = {"api_key": "synthetic-test-key", "base_url": base_url or None}
    if max_retries is not None:
        expected["max_retries"] = max_retries
    assert options == [expected]
    assert calls == [{"model": "model", "messages": [{"role": "user", "content": "classify"}], "temperature": 0.7, "stream": False, "reasoning_effort": reasoning_effort}]
    assert result.success
    assert closed == [True]


# contract-test: supporting surface=rest_api assertions=app-skills.output.bounded-failure
@pytest.mark.asyncio
async def test_groq_invalid_reasoning_effort_never_opens_transport(monkeypatch, configured_groq):
    def forbidden_client(**kwargs):
        raise AssertionError("invalid options must not open transport")
    monkeypatch.setattr(groq_client, "AsyncGroq", forbidden_client)
    with pytest.raises(ValueError, match="reasoning_effort"):
        await groq_client.invoke_groq_chat_completions(
            task_id="test", model_id="model", messages=[], reasoning_effort="minimal",
        )


# contract-test: supporting surface=rest_api assertions=app-skills.output.bounded-failure
@pytest.mark.asyncio
@pytest.mark.parametrize("stream", [False, True])
async def test_groq_failed_request_closes_transport_without_retry(monkeypatch, configured_groq, stream):
    calls, closed = [], []
    class Client:
        def __init__(self, **kwargs):
            assert kwargs["max_retries"] == 0
            self.chat = SimpleNamespace(completions=self)
        async def create(self, **kwargs):
            calls.append(True)
            raise RuntimeError("synthetic connection failure")
        async def close(self):
            closed.append(True)
    monkeypatch.setattr(groq_client, "AsyncGroq", Client)
    result = await groq_client.invoke_groq_chat_completions(task_id="test", model_id="model", messages=[], stream=stream, max_retries=0)
    if stream:
        with pytest.raises(RuntimeError, match="synthetic connection failure"):
            async for _ in result:
                pass
    else:
        assert not result.success
    assert calls == [True]
    assert closed == [True]


# contract-test: supporting surface=rest_api assertions=app-skills.output.bounded-failure
def test_groq_client_does_not_reuse_transport_across_worker_event_loops(monkeypatch: pytest.MonkeyPatch) -> None:
    import asyncio

    clients = []

    class LoopBoundClient:
        def __init__(self, **kwargs):
            self.loop = asyncio.get_running_loop()
            self.closed = False
            self.chat = SimpleNamespace(completions=self)
            clients.append(self)

        async def create(self, **kwargs):
            if self.loop is not asyncio.get_running_loop() or self.loop.is_closed():
                raise RuntimeError("Event loop is closed")
            return SimpleNamespace(
                choices=[SimpleNamespace(message=SimpleNamespace(tool_calls=None, content="safe"))],
                usage=None,
            )

        async def close(self):
            assert asyncio.get_running_loop() is self.loop
            self.closed = True

    class TestSecrets:
        async def get_secret(self, *, secret_path, secret_key):
            return "synthetic-test-key" if secret_key == "api_key" else None

    monkeypatch.setattr(groq_client, "AsyncGroq", LoopBoundClient)
    monkeypatch.setattr(groq_client, "_groq_client_initialized", False)
    monkeypatch.setattr(groq_client, "_groq_api_key", None)

    async def worker_turn():
        return await groq_client.invoke_groq_chat_completions(
            task_id="loop-lifecycle", model_id="test-model",
            messages=[{"role": "user", "content": "classify"}], secrets_manager=TestSecrets(),
        )

    first = asyncio.run(worker_turn())
    second = asyncio.run(worker_turn())
    assert first.success and second.success
    assert len(clients) == 2
    assert all(client.closed for client in clients)


# contract-test: supporting surface=rest_api assertions=app-skills.output.bounded-failure
@pytest.mark.asyncio
@pytest.mark.parametrize("stop_early", [False, True])
async def test_groq_stream_closes_transport_after_completion_or_consumer_stop(monkeypatch, configured_groq, stop_early):
    closed = []
    class Client:
        def __init__(self, **kwargs):
            self.chat = SimpleNamespace(completions=self)
        async def create(self, **kwargs):
            async def chunks():
                for word in ["first", "second"]:
                    yield SimpleNamespace(choices=[SimpleNamespace(delta=SimpleNamespace(content=word), finish_reason=None)])
            return chunks()
        async def close(self):
            closed.append(True)
    monkeypatch.setattr(groq_client, "AsyncGroq", Client)
    result = await groq_client.invoke_groq_chat_completions(task_id="test", model_id="model", messages=[], stream=True, max_retries=0)
    assert await anext(result) == "first"
    assert closed == []
    if stop_early:
        await result.aclose()
    else:
        assert [chunk async for chunk in result] == ["second"]
    assert closed == [True]
