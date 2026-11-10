"""Isolated runner for operator-installed app package providers.

Runs inside the ``app-packages-runner`` container, which has no server
environment file, Vault, database or internal-service access. The HTTP API is
served only on a Unix domain socket in a dedicated volume shared with the
services that call it; the container's only network is internet egress.
Implements the protocol in docs/architecture/apps/instance-app-packages.md:

- ``POST /v1/run``: re-check registry.json, re-verify every recorded file digest,
  execute the provider entrypoint with a minimal environment, a fresh scratch
  directory, a timeout (process group killed) and a 4 MiB stdout cap.
- ``GET /v1/health``: ``{"ok": true}``.

``runner.py --healthcheck`` probes ``/v1/health`` over the socket (exit 0/1).

Standard library only so the same file runs on a bare ``python:3.13-slim``.
"""
from __future__ import annotations

import hashlib
import json
import logging
import os
import platform
import re
import shutil
import signal
import socket
import socketserver
import stat
import subprocess
import tempfile
import sys
import threading
from http.client import HTTPConnection
from http.server import BaseHTTPRequestHandler
from pathlib import Path
from typing import Any

from manifest_yaml import parse_manifest

PACKAGE_ROOT = Path(os.environ.get("APP_PACKAGES_ROOT", "/app-packages"))
SCRATCH_ROOT = Path(os.environ.get("APP_PACKAGES_SCRATCH", "/tmp/run"))
SOCKET_PATH = Path(os.environ.get("APP_PACKAGES_RUNNER_SOCKET", "/run/app-packages-runner/runner.sock"))
MAX_STDOUT_BYTES = 4 * 1024 * 1024
MAX_REQUEST_BYTES = 1024 * 1024
MAX_TIMEOUT_SECONDS = 60
MAX_MESSAGE_CHARS = 300
MAX_CONCURRENT_RUNS = int(os.environ.get("APP_PACKAGES_MAX_CONCURRENT_RUNS", "8"))
PROTOCOL_VERSION = 1
PACKAGE_ID_RE = re.compile(r"^[a-z0-9]+(\.[a-z0-9_-]+)+$")
VERSION_RE = re.compile(r"^\d+\.\d+\.\d+(-[0-9A-Za-z.-]+)?(\+[0-9A-Za-z.-]+)?$")
PROVIDER_ID_RE = re.compile(r"^[a-z0-9_]{2,40}$")
SHA256_RE = re.compile(r"^[0-9a-f]{64}$")

logger = logging.getLogger("app_packages_runner")
_run_slots = threading.BoundedSemaphore(MAX_CONCURRENT_RUNS)


class RunError(Exception):
    """A typed runner failure returned to the caller as ``{"ok": false, "error": code}``."""

    def __init__(self, code: str, message: str | None = None) -> None:
        super().__init__(code)
        self.code = code
        self.message = message


# --------------------------------------------------------------------------
# Package verification
# --------------------------------------------------------------------------

def _read_json(path: Path) -> Any:
    with path.open("r", encoding="utf-8") as handle:
        return json.load(handle)


def _sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _safe_relative(path: str) -> bool:
    return bool(path) and not path.startswith("/") and "\\" not in path and all(
        part not in ("", ".", "..") for part in path.split("/")
    )


def verify_package(package_id: str, version: str) -> tuple[Path, dict[str, Any]]:
    """Return (files_dir, manifest) after confirming the version is active and untampered."""
    try:
        registry = _read_json(PACKAGE_ROOT / "registry.json")
        active = registry["active"][package_id]
        version_dir = PACKAGE_ROOT / "packages" / package_id / version
        install = _read_json(version_dir / "install.json")
        digests = install["file_digests"]
    except (OSError, ValueError, KeyError, TypeError) as exc:
        raise RunError("PACKAGE_UNAVAILABLE") from exc
    if not isinstance(active, dict) or active.get("version") != version:
        raise RunError("PACKAGE_UNAVAILABLE")
    sha = install.get("archive_sha256")
    if (not isinstance(sha, str) or not SHA256_RE.match(sha) or active.get("sha256") != sha
            or install.get("package_id") != package_id or install.get("version") != version
            or not isinstance(digests, dict) or not digests):
        raise RunError("PACKAGE_UNAVAILABLE")
    files_dir = version_dir / "files"
    for root, dirs, files in os.walk(files_dir, followlinks=False):
        for name in dirs + files:
            full = Path(root) / name
            relative = full.relative_to(files_dir).as_posix()
            if full.is_symlink() or (name in files and relative not in digests):
                logger.warning("Refusing %s@%s: unrecorded or linked file", package_id, version)
                raise RunError("PACKAGE_UNAVAILABLE")
    for relative, expected in digests.items():
        full = files_dir / relative
        if (not isinstance(relative, str) or not _safe_relative(relative) or not isinstance(expected, str)
                or full.is_symlink() or not full.is_file() or _sha256_file(full) != expected):
            logger.warning("Refusing %s@%s: digest mismatch", package_id, version)
            raise RunError("PACKAGE_UNAVAILABLE")
    if "manifest.yml" not in digests:
        raise RunError("PACKAGE_UNAVAILABLE")
    try:
        manifest = parse_manifest((files_dir / "manifest.yml").read_text(encoding="utf-8"))
    except (OSError, ValueError) as exc:
        raise RunError("PACKAGE_UNAVAILABLE") from exc
    if not isinstance(manifest, dict) or manifest.get("id") != package_id or str(manifest.get("version")) != version:
        raise RunError("PACKAGE_UNAVAILABLE")
    return files_dir, manifest


def find_entrypoint(files_dir: Path, manifest: dict[str, Any], provider_id: str, contract: str) -> Path:
    providers = (manifest.get("contributes") or {}).get("providers") if isinstance(manifest.get("contributes"), dict) else None
    match = next((item for item in providers or [] if isinstance(item, dict) and item.get("id") == provider_id), None)
    if match is None or match.get("contract") != contract or match.get("runtime") != "executable":
        raise RunError("PACKAGE_UNAVAILABLE")
    entrypoint = str(match.get("entrypoint") or "").replace("{target}", platform.machine())
    if not _safe_relative(entrypoint):
        raise RunError("PACKAGE_UNAVAILABLE")
    path = files_dir / entrypoint
    if not path.is_file() or not os.access(path, os.X_OK):
        raise RunError("EXECUTION_FAILED")
    return path


# --------------------------------------------------------------------------
# Execution
# --------------------------------------------------------------------------

def _kill_group(process: subprocess.Popen) -> None:
    try:
        os.killpg(process.pid, signal.SIGKILL)
    except (ProcessLookupError, PermissionError):
        pass


def sanitize_message(message: Any, secrets: dict[str, str]) -> str:
    text = str(message)
    for value in secrets.values():
        if value:
            text = text.replace(value, "[redacted]")
    text = re.sub(r"[\x00-\x1f\x7f]+", " ", text)
    return re.sub(r"\s+", " ", text).strip()[:MAX_MESSAGE_CHARS]


def execute(entrypoint: Path, payload: dict[str, Any], secrets: dict[str, str], timeout: float) -> dict[str, Any]:
    SCRATCH_ROOT.mkdir(parents=True, exist_ok=True)
    workdir = tempfile.mkdtemp(prefix="run-", dir=SCRATCH_ROOT)
    env = {"PATH": "/usr/local/bin:/usr/bin:/bin", "HOME": workdir, "LANG": "C.UTF-8", "TMPDIR": workdir}
    stdout = bytearray()
    overflow = threading.Event()
    try:
        try:
            process = subprocess.Popen(
                [str(entrypoint)], stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.DEVNULL,
                cwd=workdir, env=env, start_new_session=True, close_fds=True,
            )
        except OSError as exc:
            raise RunError("EXECUTION_FAILED") from exc

        def read_stdout() -> None:
            while True:
                chunk = process.stdout.read(65536)
                if not chunk:
                    return
                stdout.extend(chunk)
                if len(stdout) > MAX_STDOUT_BYTES:
                    overflow.set()
                    _kill_group(process)
                    return

        def write_stdin() -> None:
            try:
                process.stdin.write(json.dumps(payload).encode("utf-8"))
                process.stdin.close()
            except (BrokenPipeError, OSError):
                return

        threads = [threading.Thread(target=read_stdout, daemon=True), threading.Thread(target=write_stdin, daemon=True)]
        for thread in threads:
            thread.start()
        try:
            returncode = process.wait(timeout=timeout)
        except subprocess.TimeoutExpired:
            _kill_group(process)
            process.wait()
            raise RunError("TIMEOUT")
        finally:
            _kill_group(process)
            for thread in threads:
                thread.join(timeout=2)
            process.stdout.close()
        if overflow.is_set():
            raise RunError("OUTPUT_TOO_LARGE")
    finally:
        shutil.rmtree(workdir, ignore_errors=True)
    try:
        output = json.loads(bytes(stdout).decode("utf-8"))
    except (UnicodeDecodeError, ValueError) as exc:
        raise RunError("EXECUTION_FAILED" if returncode else "INVALID_OUTPUT") from exc
    if isinstance(output, dict) and isinstance(output.get("error"), str):
        raise RunError("PROVIDER_ERROR", sanitize_message(output["error"], secrets) or "Provider error")
    if returncode:
        raise RunError("EXECUTION_FAILED")
    if not isinstance(output, dict) or not isinstance(output.get("results"), list):
        raise RunError("INVALID_OUTPUT")
    return {"ok": True, "results": output["results"]}


def _validate_request(body: Any) -> tuple[str, str, str, str, dict[str, Any], dict[str, str], float]:
    if not isinstance(body, dict):
        raise RunError("INVALID_REQUEST")
    package_id, version = body.get("package_id"), body.get("version")
    provider_id, contract = body.get("provider_id"), body.get("contract")
    secrets, data = body.get("secrets") or {}, body.get("input")
    timeout = body.get("timeout_seconds", MAX_TIMEOUT_SECONDS)
    if (not isinstance(package_id, str) or not PACKAGE_ID_RE.match(package_id) or len(package_id) > 64
            or not isinstance(version, str) or not VERSION_RE.match(version)
            or not isinstance(provider_id, str) or not PROVIDER_ID_RE.match(provider_id)
            or not isinstance(contract, str) or not isinstance(data, dict)
            or not isinstance(secrets, dict) or not all(isinstance(k, str) and isinstance(v, str) for k, v in secrets.items())
            or isinstance(timeout, bool) or not isinstance(timeout, (int, float)) or timeout <= 0):
        raise RunError("INVALID_REQUEST")
    return package_id, version, provider_id, contract, data, secrets, float(min(timeout, MAX_TIMEOUT_SECONDS))


def handle_run(body: Any) -> dict[str, Any]:
    package_id, version, provider_id, contract, data, secrets, timeout = _validate_request(body)
    with _run_slots:
        files_dir, manifest = verify_package(package_id, version)
        entrypoint = find_entrypoint(files_dir, manifest, provider_id, contract)
        payload = {"protocol": PROTOCOL_VERSION, "contract": contract, "provider": provider_id,
                   "input": data, "secrets": secrets}
        return execute(entrypoint, payload, secrets, timeout)


class RunnerHandler(BaseHTTPRequestHandler):
    server_version = "app-packages-runner"
    sys_version = ""

    def _send(self, status: int, body: dict[str, Any]) -> None:
        data = json.dumps(body).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(data)))
        self.end_headers()
        self.wfile.write(data)

    def do_GET(self) -> None:
        if self.path == "/v1/health":
            self._send(200, {"ok": True})
        else:
            self._send(404, {"ok": False, "error": "NOT_FOUND"})

    def do_POST(self) -> None:
        if self.path != "/v1/run":
            self._send(404, {"ok": False, "error": "NOT_FOUND"})
            return
        try:
            length = int(self.headers.get("Content-Length") or "0")
        except ValueError:
            length = -1
        if length <= 0 or length > MAX_REQUEST_BYTES:
            self._send(400, {"ok": False, "error": "INVALID_REQUEST"})
            return
        try:
            body = json.loads(self.rfile.read(length).decode("utf-8"))
        except (UnicodeDecodeError, ValueError):
            self._send(400, {"ok": False, "error": "INVALID_REQUEST"})
            return
        try:
            response = handle_run(body)
        except RunError as exc:
            status = 400 if exc.code == "INVALID_REQUEST" else 200
            response = {"ok": False, "error": exc.code}
            if exc.message:
                response["message"] = exc.message
            logger.info("run %s/%s -> %s", body.get("package_id") if isinstance(body, dict) else "?",
                        body.get("provider_id") if isinstance(body, dict) else "?", exc.code)
            self._send(status, response)
            return
        self._send(200, response)

    def address_string(self) -> str:
        # Unix socket peers have no address.
        return "unix"

    def log_message(self, fmt: str, *args: Any) -> None:
        logger.debug("%s %s", self.address_string(), fmt % args)


class UnixHTTPServer(socketserver.ThreadingMixIn, socketserver.UnixStreamServer):
    """Threaded HTTP server bound to a Unix domain socket."""

    daemon_threads = True

    def __init__(self, path: Path) -> None:
        self.socket_path = path
        _remove_stale_socket(path)
        super().__init__(str(path), RunnerHandler)
        # The socket volume is dedicated to this runner and its callers.
        os.chmod(path, 0o666)

    def get_request(self) -> tuple[socket.socket, Any]:
        connection, _ = self.socket.accept()
        # BaseHTTPRequestHandler expects a (host, port)-like client address.
        return connection, ("unix", 0)

    def server_close(self) -> None:
        super().server_close()
        _remove_stale_socket(self.socket_path)


def _remove_stale_socket(path: Path) -> None:
    try:
        mode = path.lstat().st_mode
    except FileNotFoundError:
        return
    if not stat.S_ISSOCK(mode):
        raise RuntimeError(f"{path} exists and is not a socket")
    path.unlink()


class _UnixHTTPConnection(HTTPConnection):
    def __init__(self, path: Path, timeout: float) -> None:
        super().__init__("app-packages-runner", timeout=timeout)
        self._path = str(path)

    def connect(self) -> None:
        self.sock = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
        self.sock.settimeout(self.timeout)
        self.sock.connect(self._path)


def healthcheck(path: Path = SOCKET_PATH, timeout: float = 3.0) -> bool:
    connection = _UnixHTTPConnection(path, timeout)
    try:
        connection.request("GET", "/v1/health")
        return connection.getresponse().status == 200
    except OSError:
        return False
    finally:
        connection.close()


def main() -> None:
    if sys.argv[1:] == ["--healthcheck"]:
        sys.exit(0 if healthcheck() else 1)
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
    server = UnixHTTPServer(SOCKET_PATH)
    logger.info("app-packages-runner listening on %s (root %s, target %s)", SOCKET_PATH, PACKAGE_ROOT, platform.machine())
    try:
        server.serve_forever()
    finally:
        server.server_close()


if __name__ == "__main__":
    main()
