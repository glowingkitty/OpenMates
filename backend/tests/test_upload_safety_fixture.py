"""Isolated CI second opinion for uploads: benign only behind all CI guards."""
# contract-test-file: infrastructure

import asyncio
from types import SimpleNamespace

import pytest

from backend.shared.testing.upload_safety_fixture import isolated_image_second_opinion
from backend.upload.services.upload_safety_policy import JEV_FALLBACK_SAFE_BELOW

GUARDS = {"CI": "true", "OPENMATES_CI_ISOLATED": "1",
          "OPENMATES_CI_AI_FIXTURES": "1", "MOCK_EXTERNAL_APIS": "true"}


@pytest.fixture
def isolated(monkeypatch):
    for key, value in GUARDS.items():
        monkeypatch.setenv(key, value)


@pytest.mark.parametrize("missing", list(GUARDS))
def test_fixture_needs_every_isolated_ci_guard(isolated, monkeypatch, missing):
    monkeypatch.delenv(missing)
    assert isolated_image_second_opinion() is None


def test_fixture_is_clearly_harmless_for_the_strict_fallback(isolated):
    answer = isolated_image_second_opinion()
    assert set(answer) == {"nudity", "minor", "gore"}
    assert all(value < JEV_FALLBACK_SAFE_BELOW for value in answer.values())


def test_second_opinion_route_answers_from_the_fixture_without_a_provider(isolated):
    from backend.core.api.app.routes.internal_upload_safety import image_second_opinion

    async def body():
        return b"synthetic-camera-frame"

    request = SimpleNamespace(body=body, app=SimpleNamespace(state=SimpleNamespace(secrets_manager=None)))
    assert asyncio.run(image_second_opinion(request)) == {"nudity": 0.0, "minor": 0.0, "gore": 0.0}
