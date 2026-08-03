"""Focused orchestration tests for the live Project remote-access verifier.

These tests keep the real-dev gate deterministic without contacting dev. They
assert that compiled crypto is built first and that host/requester logins use
separate session stores and device identities before the live Node process.
"""

from __future__ import annotations

import subprocess
from pathlib import Path

import scripts.verify_project_remote_access_api as verifier


def test_cli_loader_preserves_relative_js_imports_from_dist(tmp_path: Path) -> None:
    dist_dir = tmp_path / "frontend" / "packages" / "openmates-cli" / "dist"
    dist_dir.mkdir(parents=True)
    (dist_dir / "entry.js").write_text(
        'import { value } from "./chunk.js"; console.log(value);\n',
        encoding="utf-8",
    )
    (dist_dir / "chunk.js").write_text('export const value = "dist-loaded";\n', encoding="utf-8")

    result = subprocess.run(
        [
            "node",
            "--experimental-strip-types",
            "--loader",
            str(verifier.CLI_DIR / "tests" / "loader.mjs"),
            str(dist_dir / "entry.js"),
        ],
        cwd=verifier.ROOT,
        text=True,
        capture_output=True,
        check=False,
    )

    assert result.returncode == 0, result.stderr
    assert result.stdout.strip() == "dist-loaded"


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


def test_takeover_websocket_is_constructed_immediately_before_open() -> None:
    source = (verifier.ROOT / "scripts" / "project_remote_access_live.mjs").read_text(encoding="utf-8")
    verification = source[source.index("async function runApiVerification") : source.index("async function requestCliOperation")]

    construction = "takeoverWs = makeWebSocket(requesterClient);"
    opening = "await takeoverWs.open();"
    assert "let takeoverWs = null;" in verification
    assert verification.count(construction) == 1
    assert verification.index(opening) > verification.index(construction)
    assert verification[verification.index(construction) : verification.index(opening)].strip() == construction
    assert "takeoverWs?.close();" in verification


def test_fixture_cleanup_retries_only_bounded_transient_statuses() -> None:
    source = (verifier.ROOT / "scripts" / "project_remote_access_live.mjs").read_text(encoding="utf-8")
    cleanup = source[source.index("async function deleteFixture") : source.index("async function refreshOwnerId")]

    assert "const FIXTURE_DELETE_MAX_ATTEMPTS = 4;" in source
    assert "new Set([429, 500, 502, 503, 504])" in source
    assert "attempt <= FIXTURE_DELETE_MAX_ATTEMPTS" in cleanup
    assert "response.status === 200 || response.status === 404" in cleanup
    assert "!FIXTURE_DELETE_RETRYABLE_STATUSES.has(response.status)" in cleanup
    assert "attempt === FIXTURE_DELETE_MAX_ATTEMPTS" in cleanup
    assert "setTimeout(resolvePromise, FIXTURE_DELETE_RETRY_DELAY_MS)" in cleanup
    assert "throw new Error(`Fixture cleanup failed with HTTP ${response.status}`)" in cleanup
