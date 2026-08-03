"""Focused orchestration tests for the live Project remote-access verifier.

These tests keep the real-dev gate deterministic without contacting dev. They
assert that compiled crypto is built first and that host/requester logins use
separate session stores and device identities before the live Node process.
"""

from __future__ import annotations

from pathlib import Path

import scripts.verify_project_remote_access_api as verifier


def test_live_verifier_builds_then_uses_isolated_authenticated_sessions(monkeypatch) -> None:
    calls: list[tuple[list[str], Path, dict[str, str]]] = []

    def fake_run(
        command: list[str],
        *,
        cwd: Path = verifier.ROOT,
        timeout: int = 240,
        env: dict[str, str] | None = None,
    ) -> None:
        del timeout
        effective_env = env or {}
        calls.append((command, cwd, effective_env))
        if command[:2] == ["node", "scripts/openmates_cli_test_account.mjs"]:
            session_path = Path(effective_env["HOME"]) / ".openmates" / "session.json"
            session_path.parent.mkdir(parents=True)
            session_path.write_text("{}", encoding="utf-8")

    monkeypatch.setattr(verifier, "run", fake_run)
    verifier.run_live_verification(
        "api", "https://api.dev.openmates.org", "7", False, personal_and_team=True
    )

    assert calls[0][:2] == (["npm", "run", "build"], verifier.CLI_DIR)
    login_calls = [call for call in calls if call[0][:2] == ["node", "scripts/openmates_cli_test_account.mjs"]]
    assert len(login_calls) == 2
    assert login_calls[0][2]["HOME"] != login_calls[1][2]["HOME"]
    assert login_calls[0][2]["OPENMATES_CLI_DEVICE_IDENTITY"] != login_calls[1][2]["OPENMATES_CLI_DEVICE_IDENTITY"]
    live_calls = [call for call in calls if "scripts/project_remote_access_live.mjs" in call[0]]
    assert [call[0][-2] for call in live_calls] == ["api", "api-team"]
    for _, _, env in live_calls:
        assert env["OPENMATES_REMOTE_HOST_SESSION"] != env["OPENMATES_REMOTE_REQUESTER_SESSION"]


def test_skip_build_still_authenticates_both_devices(monkeypatch) -> None:
    commands: list[list[str]] = []

    def fake_run(
        command: list[str],
        *,
        cwd: Path = verifier.ROOT,
        timeout: int = 240,
        env: dict[str, str] | None = None,
    ) -> None:
        del cwd, timeout
        commands.append(command)
        if command[:2] == ["node", "scripts/openmates_cli_test_account.mjs"]:
            session_path = Path((env or {})["HOME"]) / ".openmates" / "session.json"
            session_path.parent.mkdir(parents=True)
            session_path.write_text("{}", encoding="utf-8")

    monkeypatch.setattr(verifier, "run", fake_run)
    verifier.run_live_verification("api", "https://api.dev.openmates.org", None, True)

    assert ["npm", "run", "build"] not in commands
    assert sum(command[:2] == ["node", "scripts/openmates_cli_test_account.mjs"] for command in commands) == 2


def test_live_script_uses_compiled_crypto_and_truthful_optional_probe_status() -> None:
    source = (verifier.ROOT / "scripts" / "project_remote_access_live.mjs").read_text(encoding="utf-8")

    assert 'dist/remoteAccessCrypto.js' in source
    assert '"opaque-request-envelope"' not in source
    assert '"opaque-result-envelope"' not in source
    assert '"cross_session_polling_denied", "passed"' in source
    assert '"cross_account_denial",\n      "not_run"' in source
    assert '"removed_member_denial",\n      "not_run"' in source
