"""Unit tests for the isolated app package runner (stdlib HTTP server on a Unix socket).

Spec: specifications/features/instance-app-packages (instance-app-packages.isolated-runner).
Runs fast: a tiny Python-script provider in a temporary package root.
"""
from __future__ import annotations

import hashlib
import importlib
import json
import platform
import shutil
import socket
import stat
import sys
import tempfile
import threading
from pathlib import Path

import httpx
import pytest

RUNNER_DIR = Path(__file__).resolve().parents[1] / "core" / "app_packages_runner"
sys.path.insert(0, str(RUNNER_DIR))
runner = importlib.import_module("runner")
manifest_yaml = importlib.import_module("manifest_yaml")

PROVIDER_SCRIPT = f"""#!{sys.executable}
import json, os, sys, time
payload = json.load(sys.stdin)
query = payload["input"].get("query")
if query == "error":
    print(json.dumps({{"error": "upstream rejected key " + payload["secrets"].get("api_key", "") + "\\n\\tdetails"}}))
elif query == "sleep":
    time.sleep(30)
elif query == "big":
    sys.stdout.write("x" * (5 * 1024 * 1024))
elif query == "garbage":
    print("not json")
elif query == "crash":
    sys.exit(3)
elif query == "env":
    print(json.dumps({{"results": [{{"env": sorted(os.environ), "cwd": os.getcwd(), "home": os.environ["HOME"],
                                     "payload": payload}}]}}))
else:
    print(json.dumps({{"results": [{{"title": "Workshop", "url": "https://example.com/e/1",
                                     "date_start": "2026-11-07T19:00:00+01:00"}}]}}))
"""

MANIFEST = """format: openmates-app-package
format_version: 1
id: my.events
version: 1.0.0
name: My events
contributes:
  providers:
    - app: events
      skill: search
      contract: events.search@1
      id: my_events
      name: My events
      runtime: executable
      entrypoint: bin/{target}/provider
      secrets: [api_key]
"""


def _sha(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


@pytest.fixture()
def package_root(tmp_path, monkeypatch):
    root = tmp_path / "app-packages"
    version_dir = root / "packages" / "my.events" / "1.0.0"
    files = version_dir / "files"
    entry = files / "bin" / platform.machine() / "provider"
    entry.parent.mkdir(parents=True)
    entry.write_text(PROVIDER_SCRIPT)
    entry.chmod(0o755)
    (files / "manifest.yml").write_text(MANIFEST)
    (version_dir / "manifest.yml").write_text(MANIFEST)
    digests = {
        "manifest.yml": _sha(MANIFEST.encode()),
        f"bin/{platform.machine()}/provider": _sha(PROVIDER_SCRIPT.encode()),
    }
    archive_sha = "a" * 64
    (version_dir / "install.json").write_text(json.dumps({
        "package_id": "my.events", "version": "1.0.0", "archive_sha256": archive_sha,
        "installed_at": 1, "file_digests": digests,
    }))
    (root / "registry.json").write_text(json.dumps({
        "format": 1, "revision": 1,
        "active": {"my.events": {"version": "1.0.0", "sha256": archive_sha}},
        "installed": {"my.events": ["1.0.0"]},
    }))
    monkeypatch.setattr(runner, "PACKAGE_ROOT", root)
    monkeypatch.setattr(runner, "SCRATCH_ROOT", tmp_path / "scratch")
    return root


def _request(query: str = "techno", **overrides):
    body = {"package_id": "my.events", "version": "1.0.0", "provider_id": "my_events",
            "contract": "events.search@1", "input": {"query": query}, "secrets": {"api_key": "sk-test-secret"},
            "timeout_seconds": 10}
    body.update(overrides)
    return body


def _error(body) -> str:
    with pytest.raises(runner.RunError) as excinfo:
        runner.handle_run(body)
    return excinfo.value.code


# contract-test: direct surface=rest_api assertions=instance-app-packages.isolated-runner
def test_successful_run_returns_results(package_root):
    response = runner.handle_run(_request())
    assert response == {"ok": True, "results": [
        {"title": "Workshop", "url": "https://example.com/e/1", "date_start": "2026-11-07T19:00:00+01:00"}]}


# contract-test: direct surface=rest_api assertions=instance-app-packages.isolated-runner
def test_minimal_environment_and_fresh_scratch(package_root):
    result = runner.handle_run(_request("env"))["results"][0]
    assert result["env"] == ["HOME", "LANG", "PATH", "TMPDIR"]
    assert result["cwd"] == result["home"]
    assert result["payload"] == {"protocol": 1, "contract": "events.search@1", "provider": "my_events",
                                 "input": {"query": "env"}, "secrets": {"api_key": "sk-test-secret"}}
    assert not Path(result["cwd"]).exists()


# contract-test: direct surface=rest_api assertions=instance-app-packages.isolated-runner
def test_tampered_file_is_refused(package_root):
    entry = package_root / "packages/my.events/1.0.0/files/bin" / platform.machine() / "provider"
    entry.write_text(PROVIDER_SCRIPT + "\n# changed\n")
    assert _error(_request()) == "PACKAGE_UNAVAILABLE"


# contract-test: direct surface=rest_api assertions=instance-app-packages.isolated-runner
def test_unrecorded_file_is_refused(package_root):
    (package_root / "packages/my.events/1.0.0/files/extra.sh").write_text("echo hi")
    assert _error(_request()) == "PACKAGE_UNAVAILABLE"


# contract-test: direct surface=rest_api assertions=instance-app-packages.isolated-runner
def test_inactive_version_is_refused(package_root):
    assert _error(_request(version="1.1.0")) == "PACKAGE_UNAVAILABLE"
    registry = json.loads((package_root / "registry.json").read_text())
    registry["active"] = {}
    (package_root / "registry.json").write_text(json.dumps(registry))
    assert _error(_request()) == "PACKAGE_UNAVAILABLE"


# contract-test: direct surface=rest_api assertions=instance-app-packages.isolated-runner
def test_unknown_provider_or_contract_is_refused(package_root):
    assert _error(_request(provider_id="other_provider")) == "PACKAGE_UNAVAILABLE"
    assert _error(_request(contract="events.search@2")) == "PACKAGE_UNAVAILABLE"


# contract-test: direct surface=rest_api assertions=instance-app-packages.isolated-runner
def test_invalid_request_is_rejected(package_root):
    assert _error(_request(package_id="../etc")) == "INVALID_REQUEST"
    assert _error(_request(secrets={"api_key": 1})) == "INVALID_REQUEST"


# contract-test: direct surface=rest_api assertions=instance-app-packages.isolated-runner
def test_provider_error_is_sanitized_and_redacted(package_root):
    with pytest.raises(runner.RunError) as excinfo:
        runner.handle_run(_request("error"))
    assert excinfo.value.code == "PROVIDER_ERROR"
    assert "sk-test-secret" not in excinfo.value.message
    assert "\n" not in excinfo.value.message and len(excinfo.value.message) <= 300


# contract-test: direct surface=rest_api assertions=instance-app-packages.isolated-runner
def test_timeout_kills_process(package_root):
    assert _error(_request("sleep", timeout_seconds=0.5)) == "TIMEOUT"


# contract-test: direct surface=rest_api assertions=instance-app-packages.isolated-runner
def test_output_limit(package_root):
    assert _error(_request("big")) == "OUTPUT_TOO_LARGE"


# contract-test: direct surface=rest_api assertions=instance-app-packages.isolated-runner
def test_invalid_output_and_crash(package_root):
    assert _error(_request("garbage")) == "INVALID_OUTPUT"
    assert _error(_request("crash")) == "EXECUTION_FAILED"


@pytest.fixture
def socket_path():
    # AF_UNIX paths are limited to ~108 bytes; keep it short and private.
    directory = Path(tempfile.mkdtemp(prefix="apr-", dir="/tmp"))
    yield directory / "runner.sock"
    shutil.rmtree(directory, ignore_errors=True)


def _serve(path: Path):
    server = runner.UnixHTTPServer(path)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    return server


# contract-test: direct surface=rest_api assertions=instance-app-packages.isolated-runner
def test_unix_socket_health_and_run(package_root, socket_path):
    assert runner.healthcheck(socket_path) is False
    server = _serve(socket_path)
    try:
        assert stat.S_IMODE(socket_path.stat().st_mode) == 0o666
        assert runner.healthcheck(socket_path) is True
        transport = httpx.HTTPTransport(uds=str(socket_path))
        with httpx.Client(transport=transport, base_url="http://app-packages-runner") as client:
            assert client.get("/v1/health").json() == {"ok": True}
            assert client.post("/v1/run", json=_request("crash")).json() == {"ok": False, "error": "EXECUTION_FAILED"}
            assert client.post("/v1/run", content=b"not json").status_code == 400
            assert client.get("/elsewhere").status_code == 404
    finally:
        server.shutdown()
        server.server_close()
    assert not socket_path.exists()


# contract-test: direct surface=rest_api assertions=instance-app-packages.isolated-runner
def test_stale_socket_is_replaced_and_non_socket_refused(socket_path):
    stale = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
    stale.bind(str(socket_path))
    stale.close()
    server = _serve(socket_path)
    try:
        assert runner.healthcheck(socket_path) is True
    finally:
        server.shutdown()
        server.server_close()
    socket_path.write_text("not a socket")
    with pytest.raises(RuntimeError):
        runner.UnixHTTPServer(socket_path)


# contract-test: direct surface=rest_api assertions=instance-app-packages.isolated-runner
@pytest.mark.anyio
async def test_runner_client_reaches_runner_over_unix_socket(package_root, socket_path, monkeypatch):
    from backend.shared.app_packages import loader, runner_client

    provider = loader.InstalledProvider(
        package_id="my.events", package_version="1.0.0", archive_sha256="0" * 64, app_id="events",
        skill_id="search", contract="events.search@1", provider_id="my_events", name="My events",
        entrypoint="bin/{target}/provider", secrets=(), skill_hint=None)
    monkeypatch.setenv(runner_client.RUNNER_SOCKET_ENV, str(socket_path))
    down = await runner_client.run_provider(provider, {"query": "q"}, {})
    assert down.ok is False and down.error_code == runner_client.RUNNER_UNAVAILABLE
    server = _serve(socket_path)
    try:
        result = await runner_client.run_provider(provider, {"query": "q"}, {})
    finally:
        server.shutdown()
        server.server_close()
    assert result.ok is True and result.results


# contract-test: direct surface=rest_api assertions=instance-app-packages.isolated-runner
def test_manifest_subset_parser_matches_expected_structure():
    parsed, _ = manifest_yaml._parse_block(manifest_yaml._logical_lines(MANIFEST), 0, 0)
    provider = parsed["contributes"]["providers"][0]
    assert parsed["id"] == "my.events" and parsed["version"] == "1.0.0"
    assert provider["secrets"] == ["api_key"] and provider["entrypoint"] == "bin/{target}/provider"
