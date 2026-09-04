#!/usr/bin/env python3
"""Unit tests for the AI model routing verifier.

The live verifier performs authenticated REST and WebSocket checks against the
dev API. These tests cover deterministic local setup behavior only, keeping real
test-account credentials out of fixtures and output.
"""

# contract-test-file: infrastructure

from __future__ import annotations

import socket

import pytest

from scripts import verify_ai_model_routing as verifier


def test_load_local_dotenv_uses_control_plane_root_without_overriding_env(tmp_path) -> None:
    control_root = tmp_path / "OpenMates"
    repo_root = control_root / ".openmates-agent-worktrees" / "agent-cc62"
    repo_root.mkdir(parents=True)
    (control_root / ".env").write_text(
        "OPENMATES_TEST_ACCOUNT_1_EMAIL=from-file@example.test\n"
        "OPENMATES_TEST_ACCOUNT_1_PASSWORD='file password'\n"
        "OPENMATES_TEST_ACCOUNT_1_OTP_KEY=JBSWY3DPEHPK3PXP\n",
        encoding="utf-8",
    )
    env = {"OPENMATES_TEST_ACCOUNT_1_EMAIL": "from-env@example.test"}

    verifier._load_local_dotenv(env, repo_root=repo_root)

    assert env["OPENMATES_TEST_ACCOUNT_1_EMAIL"] == "from-env@example.test"
    assert env["OPENMATES_TEST_ACCOUNT_1_PASSWORD"] == "file password"
    assert env["OPENMATES_TEST_ACCOUNT_1_OTP_KEY"] == "JBSWY3DPEHPK3PXP"


def test_rejected_websocket_probe_treats_handshake_timeout_as_rejection(monkeypatch) -> None:
    seen_timeout: list[float] = []

    class TimeoutWebSocket:
        def __init__(self, _api_url: str, *, query: dict[str, str], handshake_timeout: float) -> None:
            assert query["token"] == "bad-token"
            seen_timeout.append(handshake_timeout)

        def connect(self) -> int:
            raise socket.timeout("timed out")

        def close(self) -> None:
            return None

    monkeypatch.setattr(verifier, "WireWebSocket", TimeoutWebSocket)

    verifier._expect_rejected_ws("https://api.dev.openmates.org", "bad-token", timeout=30)

    assert seen_timeout == [5.0]


def test_parse_args_defaults_to_configured_account_slots(monkeypatch) -> None:
    monkeypatch.delenv("OPENMATES_AI_MODEL_ROUTING_ACCOUNT_SLOT", raising=False)
    monkeypatch.delenv("OPENMATES_TEST_ACCOUNT_SOURCE_SLOT", raising=False)
    monkeypatch.delenv("OPENMATES_AI_MODEL_ROUTING_ISOLATION_SLOT", raising=False)

    args = verifier.parse_args([])

    assert args.slot == 1
    assert args.isolation_slot == 2


def test_isolation_login_does_not_fall_back_to_base_account(monkeypatch) -> None:
    seen_fallbacks: list[bool] = []

    def fake_load_test_account(_slot: int, *, allow_base_fallback: bool):
        seen_fallbacks.append(allow_base_fallback)
        return None

    monkeypatch.setattr(verifier, "load_test_account", fake_load_test_account)

    with pytest.raises(verifier.ContractFailure, match="configured isolation test-account credentials are incomplete"):
        verifier._login(
            "https://api.dev.openmates.org",
            origin="https://app.dev.openmates.org",
            slot=15,
            timeout=1,
            allow_base_fallback=False,
            account_label="isolation",
        )

    assert seen_fallbacks == [False]


def test_receive_event_reports_unrelated_event_types_before_timeout() -> None:
    class EventThenTimeoutWebSocket:
        def __init__(self) -> None:
            self._sent = False

        def receive_json(self, _timeout: float) -> dict[str, object]:
            if not self._sent:
                self._sent = True
                return {"type": "send_embed_data"}
            raise socket.timeout("timed out")

    with pytest.raises(verifier.ContractFailure, match="seen event types: send_embed_data"):
        verifier._receive_event(EventThenTimeoutWebSocket(), "chat_model_preference_updated", timeout=1)


def test_configured_api_key_prefers_requested_account_slot(monkeypatch) -> None:
    monkeypatch.setenv("OPENMATES_TEST_ACCOUNT_1_API_KEY", "slot-key")
    monkeypatch.setenv("OPENMATES_TEST_ACCOUNT_API_KEY", "shared-key")

    assert verifier._configured_api_key(1) == "slot-key"


def test_run_dispatches_cli_and_sdk_checks_without_session_login(monkeypatch) -> None:
    args = verifier.parse_args(["--real-auth", "--check-cli", "--check-npm", "--check-pip"])
    seen: list[str] = []

    monkeypatch.setattr(verifier, "_login", lambda *_args, **_kwargs: pytest.fail("session login must not run"))
    monkeypatch.setattr(verifier, "_configured_api_key", lambda _slot: "test-key")
    monkeypatch.setattr(
        verifier,
        "run_cli_checks",
        lambda *_args, **_kwargs: seen.append("cli") or ["cli_passed"],
    )
    monkeypatch.setattr(
        verifier,
        "run_sdk_checks_with_temporary_key",
        lambda surface, *_args, **_kwargs: seen.append(surface) or [f"{surface}_passed"],
    )

    result = verifier.run(args)

    assert seen == ["cli", "npm", "pip"]
    assert result["checks"] == ["cli_passed", "npm_passed", "pip_passed"]
