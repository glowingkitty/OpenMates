"""Tests for the install release-age gate and its Bash hook parser (network faked)."""

# contract-test-file: infrastructure

from __future__ import annotations

import json
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import install_age_guard as guard  # noqa: E402 - path insert above
import install_age_hook as hook  # noqa: E402 - path insert above
from security_monitoring import release_age as ra  # noqa: E402 - path insert above

NOW = datetime(2026, 11, 21, 12, 0, tzinfo=timezone.utc)
VERSIONS = {
    "1.0.0": NOW - timedelta(days=60),
    "1.1.0": NOW - timedelta(days=10),
    "1.2.0": NOW - timedelta(days=2),
    "2.0.0-rc.1": NOW - timedelta(days=9),
}


@pytest.fixture(autouse=True)
def fake_network(monkeypatch):
    monkeypatch.setattr(guard, "registry_versions", lambda eco, name: ("1.2.0", dict(VERSIONS)))
    monkeypatch.setattr(guard, "kev_cves", lambda: {"CVE-2026-0001"})


# Spec coverage: security-monitoring.release-age.install-time
# contract-test: infrastructure
def test_old_version_allowed():
    result = guard.decide("npm", "my-pkg", "1.1.0", now=NOW)
    assert result["allowed"] is True


# Spec coverage: security-monitoring.release-age.install-time
# contract-test: infrastructure
def test_latest_default_too_young_suggests_newest_older_stable():
    result = guard.decide("PyPI", "my-pkg", now=NOW)
    assert result["version"] == "1.2.0"
    assert result["allowed"] is False
    assert result["suggested_version"] == "1.1.0"


# Spec coverage: security-monitoring.release-age.install-time
# contract-test: infrastructure
def test_kev_allows_young_version_only_if_cve_listed():
    assert guard.decide("npm", "my-pkg", "1.2.0", kev="CVE-2026-0001", now=NOW)["allowed"] is True
    refused = guard.decide("npm", "my-pkg", "1.2.0", kev="CVE-2026-9999", now=NOW)
    assert refused["allowed"] is False and "not in the CISA KEV" in refused["reason"]


# Spec coverage: security-monitoring.release-age.install-time
# contract-test: infrastructure
def test_unknown_version_refused():
    assert guard.decide("crates.io", "my-pkg", "9.9.9", now=NOW)["allowed"] is False


# Spec coverage: security-monitoring.release-age.install-time
# contract-test: infrastructure
def test_lookup_error_fails_closed(monkeypatch):
    def boom(eco, name):
        raise ra.RegistryLookupError("offline")
    monkeypatch.setattr(guard, "registry_versions", boom)
    result = guard.decide("npm", "my-pkg", "1.0.0", now=NOW)
    assert result["allowed"] is False and result["error"] is True


# Spec coverage: security-monitoring.release-age.install-time
# contract-test: infrastructure
def test_kev_lookup_error_fails_closed(monkeypatch):
    def boom():
        raise guard.FetchError("network_error")
    monkeypatch.setattr(guard, "kev_cves", boom)
    assert guard.decide("npm", "my-pkg", "1.2.0", kev="CVE-2026-0001", now=NOW)["allowed"] is False


# Spec coverage: security-monitoring.release-age.install-time
# contract-test: infrastructure
def test_cli_exit_codes_and_json(capsys, monkeypatch):
    monkeypatch.setattr(guard, "decide", lambda *a, **k: {"allowed": True})
    assert guard.main(["check", "--ecosystem", "npm", "--name", "x"]) == 0
    assert json.loads(capsys.readouterr().out)["allowed"] is True
    monkeypatch.setattr(guard, "decide", lambda *a, **k: {"allowed": False})
    assert guard.main(["check", "--ecosystem", "npm", "--name", "x"]) == 1
    monkeypatch.setattr(guard, "decide", lambda *a, **k: {"allowed": False, "error": True})
    assert guard.main(["check", "--ecosystem", "npm", "--name", "x"]) == 2


@pytest.mark.parametrize("command", [
    "npm install my-pkg",
    "npm i my-pkg@1.2.0",
    "pnpm add my-pkg",
    "pnpm --filter web add my-pkg@1.1.0",
    "yarn add my-pkg",
    "pip install my-pkg",
    "pip3 install my-pkg==1.1.0",
    "python3 -m pip install -r requirements.txt",
    "uv pip install my-pkg",
    "uv add my-pkg",
    "cargo add my-pkg",
    "cargo install my-pkg",
    "cd x && npm install my-pkg",
    "OPENMATES_AGE_CHECKED=npm:other@1.1.0 npm install my-pkg@1.1.0",
])
# Spec coverage: security-monitoring.release-age.install-time
# contract-test: infrastructure
def test_unchecked_installs_refused(command, capsys):
    assert hook.check_command(command) == 2
    assert "install_age_guard.py check" in capsys.readouterr().err


@pytest.mark.parametrize("command", [
    "pnpm install --frozen-lockfile",
    "pnpm install",
    "npm ci",
    "npm install",
    "pip install -r requirements.txt --require-hashes",
    "pip install -e .",
    "pip install ./local/pkg",
    "uv pip install --require-hashes -r requirements.txt",
    "cargo build",
    "cargo install --path .",
    "git commit -m 'docs: pip install my-pkg'",
    "echo npm install my-pkg",
    "ls -la",
])
# Spec coverage: security-monitoring.release-age.install-time
# contract-test: infrastructure
def test_lockfile_and_unrelated_commands_allowed(command):
    assert hook.check_command(command) == 0


# Spec coverage: security-monitoring.release-age.install-time
# contract-test: infrastructure
def test_passthrough_reverified_and_allowed(monkeypatch):
    calls = []
    monkeypatch.setattr(hook.guard, "decide", lambda eco, name, ver, kev=None: calls.append((eco, name, ver, kev)) or {"allowed": True})
    assert hook.check_command("OPENMATES_AGE_CHECKED=npm:my-pkg@1.1.0 npm install my-pkg@1.1.0") == 0
    assert hook.check_command("OPENMATES_AGE_CHECKED=PyPI:My_Pkg@1.1.0 pip install my-pkg==1.1.0") == 0
    assert hook.check_command("OPENMATES_AGE_CHECKED=crates.io:my-pkg@1.1.0 cargo install my-pkg --version 1.1.0") == 0
    assert hook.check_command("OPENMATES_AGE_CHECKED=npm:@s/p@1.1.0 OPENMATES_AGE_KEV=CVE-2026-0001 pnpm add @s/p@1.1.0") == 0
    assert calls[0] == ("npm", "my-pkg", "1.1.0", None)
    assert calls[-1] == ("npm", "@s/p", "1.1.0", "CVE-2026-0001")


# Spec coverage: security-monitoring.release-age.install-time
# contract-test: infrastructure
def test_passthrough_cannot_be_faked(capsys):
    """The hook re-runs the check: a claimed-but-young version is still refused."""
    command = "OPENMATES_AGE_CHECKED=npm:my-pkg@1.2.0 npm install my-pkg@1.2.0"
    assert hook.check_command(command) == 2
    assert "Newest allowed older version: 1.1.0" in capsys.readouterr().err


# Spec coverage: security-monitoring.release-age.install-time
# contract-test: infrastructure
def test_passthrough_must_match_spec_version():
    assert hook.check_command("OPENMATES_AGE_CHECKED=npm:my-pkg@1.1.0 npm install my-pkg@1.2.0") == 2
    assert hook.check_command("OPENMATES_AGE_CHECKED=npm:my-pkg@1.1.0 npm install my-pkg@^1.1.0") == 2
