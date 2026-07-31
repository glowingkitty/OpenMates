# backend/tests/test_code_notebook_execution.py
#
# Contract tests for the first-party notebook execution API. The route validates
# Python nbformat input, creates an inert runner bundle, and delegates execution
# to the existing Code Run E2B lifecycle.

from __future__ import annotations

from types import SimpleNamespace

import pytest
from fastapi import HTTPException

from backend.tests.runtime_import_stubs import install_code_route_import_stubs


install_code_route_import_stubs()

from backend.core.api.app.models.user import User  # noqa: E402
from backend.core.api.app.routes import code_notebook_execution  # noqa: E402


def _python_notebook() -> dict:
    return {
        "nbformat": 4,
        "nbformat_minor": 5,
        "metadata": {"kernelspec": {"language": "python", "name": "python3"}},
        "cells": [
            {"cell_type": "markdown", "metadata": {}, "source": "# Weather analysis"},
            {"cell_type": "code", "metadata": {}, "source": "print('first')", "outputs": []},
            {"cell_type": "code", "metadata": {}, "source": "print('second')", "outputs": []},
        ],
    }


class _AwaitableValue:
    def __init__(self, value):
        self.value = value

    def __await__(self):
        async def _inner():
            return self.value

        return _inner().__await__()


def test_build_notebook_run_bundle_creates_runner_and_requirements() -> None:
    files, target_path, selected = code_notebook_execution.build_notebook_run_bundle(
        notebook=_python_notebook(),
        notebook_embed_id="embed-1",
        run_scope="cells",
        cell_indices=[2],
        dependency_installs=[],
    )

    paths = {file["path"] for file in files}
    assert target_path == "openmates_notebook_runner.py"
    assert "notebook.ipynb" in paths
    assert "openmates_notebook_runner.py" in paths
    assert "requirements.txt" in paths
    assert selected == [2]
    runner = next(file for file in files if file["path"] == "openmates_notebook_runner.py")
    assert "OPENMATES_NOTEBOOK_OUTPUT_JSON" in runner["content"]


def test_build_notebook_run_bundle_rejects_invalid_cell_indices() -> None:
    with pytest.raises(HTTPException) as exc:
        code_notebook_execution.build_notebook_run_bundle(
            notebook=_python_notebook(),
            notebook_embed_id="embed-1",
            run_scope="cells",
            cell_indices=[99],
            dependency_installs=[],
        )

    assert exc.value.status_code == 422


@pytest.mark.anyio
async def test_start_notebook_run_delegates_to_code_run(monkeypatch: pytest.MonkeyPatch) -> None:
    calls: list[dict] = []

    async def fake_start_code_run_execution(**kwargs):
        calls.append(kwargs)
        return SimpleNamespace(execution_id="execution-1", status="queued", target_filename="openmates_notebook_runner.py", files=["openmates_notebook_runner.py"])

    async def fake_verify(*_args, **_kwargs):
        return True

    monkeypatch.setattr(code_notebook_execution, "start_code_run_execution", fake_start_code_run_execution)
    monkeypatch.setattr(code_notebook_execution, "verify_notebook_embed_access", fake_verify)

    response = await code_notebook_execution.start_notebook_run(
        request=SimpleNamespace(),
        body=code_notebook_execution.NotebookRunStartRequest(
            chat_id="chat-1",
            notebook_embed_id="embed-1",
            client_notebook=_python_notebook(),
        ),
        current_user=User(id="user-1", username="alice", vault_key_id="vault-1", credits=10),
        cache_service=SimpleNamespace(client=_AwaitableValue(SimpleNamespace())),
        directus_service=SimpleNamespace(),
        encryption_service=SimpleNamespace(),
    )

    assert response.execution_id == "execution-1"
    assert response.notebook_embed_id == "embed-1"
    assert response.stream_path == "/v1/code/run/execution-1/stream"
    assert calls[0]["target_embed_id"] == "embed-1"
    assert calls[0]["target_path"] == "openmates_notebook_runner.py"
    assert calls[0]["dependency_installs"]


@pytest.mark.anyio
async def test_start_notebook_run_allows_valid_client_notebook_for_example_chat(monkeypatch: pytest.MonkeyPatch) -> None:
    calls: list[dict] = []

    async def fake_start_code_run_execution(**kwargs):
        calls.append(kwargs)
        return SimpleNamespace(execution_id="execution-example", status="queued", target_filename="openmates_notebook_runner.py", files=["openmates_notebook_runner.py"])

    async def fake_verify(*_args, **_kwargs):
        return False

    monkeypatch.setattr(code_notebook_execution, "start_code_run_execution", fake_start_code_run_execution)
    monkeypatch.setattr(code_notebook_execution, "verify_notebook_embed_access", fake_verify)

    response = await code_notebook_execution.start_notebook_run(
        request=SimpleNamespace(),
        body=code_notebook_execution.NotebookRunStartRequest(
            chat_id="example-open-meteo-weather-notebook",
            notebook_embed_id="example-notebook-embed",
            client_notebook=_python_notebook(),
        ),
        current_user=User(id="user-1", username="alice", vault_key_id="vault-1", credits=10),
        cache_service=SimpleNamespace(client=_AwaitableValue(SimpleNamespace())),
        directus_service=SimpleNamespace(),
        encryption_service=SimpleNamespace(),
    )

    assert response.execution_id == "execution-example"
    assert calls[0]["chat_id"] == "example-open-meteo-weather-notebook"
    assert calls[0]["target_embed_id"] == "example-notebook-embed"
