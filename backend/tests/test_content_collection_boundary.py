"""Unavailable content collection must fail before secrets, network or writes."""
# contract-test-file: infrastructure

import argparse
import ast
import importlib
from pathlib import Path
from unittest.mock import AsyncMock

import httpx
import pytest


@pytest.mark.asyncio
@pytest.mark.parametrize("url", [
    "https://example.com/article", "https://youtube.com/watch?v=example",
    "http://127.0.0.1/", "https://source.example/redirect",
])
async def test_web_reader_is_unavailable_without_source_client_or_network(monkeypatch, url):
    from backend.apps.web.skills.read_skill import ReadSkill

    def forbidden(*args, **kwargs):
        pytest.fail("Unavailable content reading must not initialize network clients")

    monkeypatch.setattr(httpx, "AsyncClient", forbidden)
    credential_access = AsyncMock(side_effect=AssertionError("No credential access allowed"))
    monkeypatch.setattr(ReadSkill, "_get_or_create_secrets_manager", credential_access)
    skill = object.__new__(ReadSkill)
    result = await skill.execute(requests=[{"url": url}], secrets_manager=None)
    assert result.results == []
    assert result.provider == ""
    assert result.error == "No supported content reader is configured."
    credential_access.assert_not_called()


@pytest.mark.asyncio
@pytest.mark.parametrize("module_name,function,kwargs", [
    ("fetch_lmarena_rankings", "fetch_lmarena_rankings", {"category": "text"}),
    ("fetch_openrouter_rankings", "fetch_rankings", {"basic_mode": False}),
    ("fetch_openrouter_rankings", "fetch_rankings", {"basic_mode": True}),
    ("fetch_simplebench_rankings", "fetch_simplebench_rankings", {}),
    ("aggregate_leaderboards", "fetch_lmarena_data", {}),
    ("aggregate_leaderboards", "fetch_openrouter_data", {}),
])
async def test_ranking_collectors_have_no_callable_network_path(monkeypatch, module_name, function, kwargs):
    import urllib.request
    module = importlib.import_module(f"backend.scripts.{module_name}")

    def forbidden(*args, **kwargs):
        pytest.fail("Unsupported collection must not access network")

    monkeypatch.setattr(httpx, "AsyncClient", forbidden)
    monkeypatch.setattr(urllib.request, "urlopen", forbidden)
    with pytest.raises(RuntimeError, match="No supported leaderboard data source is configured"):
        await getattr(module, function)(**kwargs)


@pytest.mark.asyncio
async def test_comparison_rejects_removed_source_before_secret_access(monkeypatch):
    from scripts import compare_search_providers as module
    secrets = AsyncMock(side_effect=AssertionError("No credentials allowed"))
    monkeypatch.setattr(module, "_get_secrets_manager", secrets)
    with pytest.raises(ValueError, match="No supported search comparison source"):
        await module.run(argparse.Namespace(provider="unsupported_source"))
    secrets.assert_not_called()


def test_automatic_collection_schedule_and_startup_enqueue_are_absent():
    root = Path(__file__).resolve().parents[2]
    config = ast.parse((root / "backend/core/api/app/tasks/celery_config.py").read_text())
    for node in ast.walk(config):
        if isinstance(node, ast.Dict):
            pairs = {key.value: value.value for key, value in zip(node.keys, node.values)
                     if isinstance(key, ast.Constant) and isinstance(value, ast.Constant)}
            assert pairs.get("task") != "leaderboard.update_daily"
    startup = ast.parse((root / "backend/core/api/main.py").read_text())
    for node in ast.walk(startup):
        if isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute) and node.func.attr == "send_task":
            assert not any(isinstance(arg, ast.Constant) and arg.value == "leaderboard.update_daily" for arg in node.args)
