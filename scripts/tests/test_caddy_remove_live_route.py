"""Focused safety checks for live-only Caddy host retirement.

Synthetic configs prove exclusive route removal, full-config concurrency, and
fail-closed backup/application behavior without contacting a running service.
The shell entrypoint must delegate before broad configuration setup runs.
No runtime Caddy, credentials, service manager, or installed package is changed.
"""
# contract-test-file: tooling

import copy
import importlib.util
import json
from pathlib import Path
import subprocess

import pytest

ROOT = Path(__file__).resolve().parents[2]
SPEC = importlib.util.spec_from_file_location("caddy_remove_live_route", ROOT / "scripts/caddy_remove_live_route.py")
module = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(module)
HOST = "retired.example.org"


def fixture():
    return {"apps": {"http": {"servers": {"shared": {"routes": [
        {"match": [{"host": ["app.example.org"]}], "handle": [{"handler": "static_response", "body": "keep"}]},
        {"match": [{"host": [HOST]}], "handle": [{"handler": "reverse_proxy", "upstreams": [{"dial": "localhost:4096"}]}]},
    ]}}}}, "admin": {"listen": "localhost:2019"}}


def test_exclusive_route_removal_preserves_every_other_value():
    config = fixture()
    original = copy.deepcopy(config)
    expected = copy.deepcopy(config)
    del expected["apps"]["http"]["servers"]["shared"]["routes"][1]
    assert module.remove_exclusive_host(config, HOST) == expected
    assert config == original


@pytest.mark.parametrize("kind", ["missing", "duplicate", "shared-host", "extra-matcher"])
def test_ambiguous_or_shared_route_rejected(kind):
    config = fixture()
    routes = config["apps"]["http"]["servers"]["shared"]["routes"]
    if kind == "missing":
        routes.pop()
    elif kind == "duplicate":
        routes.append(copy.deepcopy(routes[-1]))
    elif kind == "shared-host":
        routes[-1]["match"][0]["host"].append("keep.example.org")
    else:
        routes[-1]["match"][0]["path"] = ["/shared"]
    with pytest.raises(module.RouteRemovalError):
        module.remove_exclusive_host(config, HOST)


def test_review_is_read_only_and_exposes_only_hashes():
    calls = []
    def transport(*args, **kwargs):
        calls.append((args, kwargs))
        return fixture(), '"/config/ original"'
    result = module.execute(HOST, apply=False, expected_hash=None, backup=None, transport=transport)
    assert len(calls) == 1
    assert result["mode"] == "review"
    assert "upstreams" not in json.dumps(result)


def test_apply_uses_full_config_etag_private_backup_and_exact_postdiff(tmp_path):
    state = fixture()
    original = copy.deepcopy(state)
    calls = []
    def transport(method="GET", *, data=None, etag=None):
        nonlocal state
        calls.append(method)
        if method == "POST":
            assert etag == '"/config/ original"'
            state = json.loads(data)
            return None, None
        return state, '"/config/ original"'
    backup = tmp_path / "before.json"
    result = module.execute(HOST, apply=True, expected_hash=module.config_hash(original), backup=backup, transport=transport)
    assert calls == ["GET", "POST", "GET"]
    assert result["unrelated_config_unchanged"]
    assert json.loads(backup.read_text()) == original
    assert backup.stat().st_mode & 0o777 == 0o600


@pytest.mark.parametrize("failure", ["stale-review", "missing-etag", "rejected-post", "postdiff", "existing-backup"])
def test_failure_never_retries_or_restarts(tmp_path, failure):
    calls = []
    def transport(method="GET", **kwargs):
        calls.append(method)
        if method == "POST" and failure == "rejected-post":
            raise module.RouteRemovalError("HTTP 412")
        return fixture(), None if failure == "missing-etag" else '"/config/ original"'
    backup = tmp_path / "before.json"
    if failure == "existing-backup":
        backup.write_text("preserve")
    expected = "stale" if failure == "stale-review" else module.config_hash(fixture())
    with pytest.raises((module.RouteRemovalError, FileExistsError)):
        module.execute(HOST, apply=True, expected_hash=expected, backup=backup, transport=transport)
    assert calls.count("POST") <= 1
    if failure == "existing-backup":
        assert backup.read_text() == "preserve"


def test_shell_narrow_help_never_enters_environment_or_system_setup():
    result = subprocess.run(["bash", str(ROOT / "deployment/apply-caddy-config.sh"),
                             "--remove-live-host", HOST, "--help"], capture_output=True, text=True)
    assert result.returncode == 0, result.stderr
    assert "--expected-config-sha256" in result.stdout
    assert "Applying Caddy Configuration" not in result.stdout
