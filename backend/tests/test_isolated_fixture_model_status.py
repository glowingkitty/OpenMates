# Runner-only model readiness regression for the real server-status endpoint.
# contract-test-file: infrastructure
# Extract the small status helpers to avoid unrelated settings-route imports.
# The source functions run unchanged with real fixture files and no credentials.
# Normal self-hosting, disabled replay, and production never acquire readiness
# merely because committed test data exists in an open-source checkout.

import ast
import asyncio
import os
from pathlib import Path
from types import SimpleNamespace

import pytest

SOURCE = Path(__file__).parents[1] / "core/api/app/routes/settings.py"


def status_functions():
    tree = ast.parse(SOURCE.read_text())
    names = {"_has_isolated_ci_ai_fixtures", "_are_ai_models_configured"}
    module = ast.Module(
        body=[
            n
            for n in tree.body
            if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef))
            and n.name in names
        ],
        type_ignores=[],
    )
    namespace = dict(
        os=os,
        Path=Path,
        __file__=str(SOURCE),
        Request=object,
        _has_configured_local_llm_model=lambda: False,
        LLM_PROVIDER_ENV_KEYS=(),
        LLM_PROVIDER_VAULT_PATHS=(),
    )
    exec(compile(module, str(SOURCE), "exec"), namespace)
    return namespace


@pytest.fixture
def isolated(monkeypatch):
    for name, value in dict(
        CI="true",
        OPENMATES_CI_ISOLATED="1",
        OPENMATES_CI_AI_FIXTURES="1",
        MOCK_EXTERNAL_APIS="true",
        SERVER_ENVIRONMENT="development",
    ).items():
        monkeypatch.setenv(name, value)
    return status_functions()


def test_real_fixture_engine_is_ready_without_provider_key(isolated):
    request = SimpleNamespace(app=SimpleNamespace(state=SimpleNamespace()))
    assert asyncio.run(isolated["_are_ai_models_configured"](request)) is True


@pytest.mark.parametrize(
    "name,value",
    [
        ("CI", "false"),
        ("OPENMATES_CI_ISOLATED", "0"),
        ("OPENMATES_CI_AI_FIXTURES", "0"),
        ("MOCK_EXTERNAL_APIS", "false"),
        ("SERVER_ENVIRONMENT", "production"),
        ("SERVER_ENVIRONMENT", "prod"),
    ],
)
def test_every_isolation_boundary_is_required(isolated, monkeypatch, name, value):
    monkeypatch.setenv(name, value)
    assert isolated["_has_isolated_ci_ai_fixtures"]() is False
    request = SimpleNamespace(app=SimpleNamespace(state=SimpleNamespace()))
    assert asyncio.run(isolated["_are_ai_models_configured"](request)) is False


def test_missing_fixture_checkout_is_not_ready(isolated, tmp_path):
    isolated["__file__"] = str(tmp_path / "backend/core/api/app/routes/settings.py")
    assert isolated["_has_isolated_ci_ai_fixtures"]() is False
