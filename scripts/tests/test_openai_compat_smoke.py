"""Regression tests for the OpenAI-compatible live smoke helper.

The helper may derive a temporary API key from a local CLI session. These tests
pin the origin restriction and fail-closed cleanup behavior without reading real
session data, creating API keys, or making network calls.
"""

# contract-test-file: tooling

from __future__ import annotations

from contextlib import redirect_stderr
import io

import pytest

from scripts import openai_compat_smoke


def test_cli_session_key_mode_rejects_custom_api_url() -> None:
    with pytest.raises(RuntimeError, match="restricted to https://api.dev.openmates.org"):
        openai_compat_smoke._validate_cli_session_api_url("https://example.invalid")


@pytest.mark.parametrize(
    "api_url",
    [
        "https://api.dev.openmates.org/",
        "https://api.dev.openmates.org?query=1",
        "https://api.dev.openmates.org#fragment",
        "https://user@api.dev.openmates.org",
        "https://api.dev.openmates.org:444",
        "https://api.dev.openmates.org/custom",
    ],
)
def test_cli_session_key_mode_rejects_default_origin_variants(api_url: str) -> None:
    with pytest.raises(RuntimeError, match="restricted to https://api.dev.openmates.org"):
        openai_compat_smoke._validate_cli_session_api_url(api_url)


def test_temporary_key_cleanup_failure_fails_successful_smoke(monkeypatch: pytest.MonkeyPatch) -> None:
    def fake_run_cli_json(args: list[str], **_kwargs: object) -> dict[str, object]:
        if "create" in args:
            return {"api_key": "sk-api-test", "id": "key-1"}
        raise RuntimeError("cleanup failed")

    monkeypatch.setattr(openai_compat_smoke, "_run_cli_json", fake_run_cli_json)

    with pytest.raises(RuntimeError, match="failed to revoke temporary API key key-1"):
        with openai_compat_smoke._api_key_from_cli_session(
            "https://api.dev.openmates.org",
            "test-key",
        ):
            pass


def test_temporary_key_cleanup_failure_preserves_smoke_error(monkeypatch: pytest.MonkeyPatch) -> None:
    def fake_run_cli_json(args: list[str], **_kwargs: object) -> dict[str, object]:
        if "create" in args:
            return {"api_key": "sk-api-test", "id": "key-1"}
        raise RuntimeError("cleanup failed")

    monkeypatch.setattr(openai_compat_smoke, "_run_cli_json", fake_run_cli_json)
    stderr = io.StringIO()

    with pytest.raises(ValueError, match="smoke failed"), redirect_stderr(stderr):
        with openai_compat_smoke._api_key_from_cli_session(
            "https://api.dev.openmates.org",
            "test-key",
        ):
            raise ValueError("smoke failed")

    assert "WARNING: failed to revoke temporary API key key-1" in stderr.getvalue()


def test_missing_create_id_is_recovered_by_name_for_cleanup(monkeypatch: pytest.MonkeyPatch) -> None:
    commands: list[list[str]] = []

    def fake_run_cli_json(args: list[str], **_kwargs: object) -> dict[str, object]:
        commands.append(args)
        if "create" in args:
            return {"api_key": "sk-api-test"}
        if "list" in args:
            return {"api_keys": [{"id": "key-1", "name": "test-key"}]}
        return {"success": True}

    monkeypatch.setattr(openai_compat_smoke, "_run_cli_json", fake_run_cli_json)

    with pytest.raises(RuntimeError, match="CLI did not return API key id"):
        with openai_compat_smoke._api_key_from_cli_session(
            "https://api.dev.openmates.org",
            "test-key",
        ):
            pass

    assert any("list" in command for command in commands)
    assert any("revoke" in command and "key-1" in command for command in commands)


def test_ambiguous_name_recovery_does_not_revoke_preexisting_key(monkeypatch: pytest.MonkeyPatch) -> None:
    commands: list[list[str]] = []

    def fake_run_cli_json(args: list[str], **_kwargs: object) -> dict[str, object]:
        commands.append(args)
        if "create" in args:
            return {"api_key": "sk-api-test"}
        if "list" in args:
            return {"api_keys": [{"id": "old-1", "name": "test-key"}, {"id": "old-2", "name": "test-key"}]}
        return {"success": True}

    monkeypatch.setattr(openai_compat_smoke, "_run_cli_json", fake_run_cli_json)

    with pytest.raises(RuntimeError, match="CLI did not return API key id"):
        with openai_compat_smoke._api_key_from_cli_session(
            "https://api.dev.openmates.org",
            "test-key",
        ):
            pass

    assert any("list" in command for command in commands)
    assert not any("revoke" in command for command in commands)


def test_completion_text_rejects_standardized_ai_error() -> None:
    with pytest.raises(AssertionError, match="standardized AI error text"):
        openai_compat_smoke._assert_completion_text(
            "Plain chat completion",
            "The AI service encountered an error while processing your request. Please try again in a moment.",
        )
