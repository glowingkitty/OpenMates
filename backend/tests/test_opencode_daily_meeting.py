"""Regression tests for the OpenCode daily meeting launcher.

The launcher lives under scripts/ because it is a host-side cron helper, but
its URL generation is part of the backend notification contract. These tests
guard the OpenCode deep-link shape without invoking the OpenCode CLI, sending
email, or reading secret configuration from the local environment.
"""

from __future__ import annotations

import importlib.util
from pathlib import Path


SCRIPT_PATH = Path(__file__).resolve().parents[2] / "scripts" / "_opencode_daily_meeting.py"


def _load_launcher_module():
    spec = importlib.util.spec_from_file_location("opencode_daily_meeting", SCRIPT_PATH)
    assert spec is not None
    assert spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_project_path_token_matches_opencode_web_route() -> None:
    module = _load_launcher_module()

    token = module._project_path_token(Path("/home/superdev/projects/OpenMates"))

    assert token == "L2hvbWUvc3VwZXJkZXYvcHJvamVjdHMvT3Blbk1hdGVz"


def test_session_url_uses_configured_base_url(monkeypatch) -> None:
    module = _load_launcher_module()
    monkeypatch.setenv("OPENCODE_WEB_BASE_URL", "https://example.invalid/")

    url = module._build_session_url("ses_test")

    assert url == (
        "https://example.invalid/"
        "L2hvbWUvc3VwZXJkZXYvcHJvamVjdHMvT3Blbk1hdGVz/session/ses_test"
    )


def test_session_url_is_missing_when_base_url_is_unconfigured(monkeypatch) -> None:
    module = _load_launcher_module()
    monkeypatch.delenv("OPENCODE_WEB_BASE_URL", raising=False)

    assert module._build_session_url("ses_test") is None
