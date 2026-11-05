"""Private-network collector for signed, encrypted host reports.

Servers push (deployment/host_reporter/openmates-host-reporter); the dev server
never pulls and holds no server credentials. The collector listens only on a
private-network address taken from gitignored local configuration
(`SECURITY_HOST_COLLECTOR_BIND` in the environment or repository `.env`, or
`logs/security-monitoring/collector/config.json` {"bind": "<ip>:<port>"}) and
refuses to start without it or on a public, loopback or unspecified address.

Each body is CMS-decrypted with the collector key, the inner SSH signature is
verified against `allowed_signers` (principal = host role), and the report is
rejected on unknown signer, bad signature, role or host-id mismatch, replayed
nonce, stale or future timestamp, or any field outside HOST_REPORT_FIELDS.
Accepted reports are written atomically to hosts/<role>/latest.json (the prior
one kept as previous.json) under logs/security-monitoring/, which is gitignored.

Usage:
  python3 scripts/security_monitoring/host_collector.py init-collector
  python3 scripts/security_monitoring/host_collector.py register-host --role core --pubkey "ssh-ed25519 AAAA..."
  python3 scripts/security_monitoring/host_collector.py serve
  python3 scripts/security_monitoring/host_collector.py status

Contract: specifications/architecture/security-monitoring (host-reports.private-push).
"""

from __future__ import annotations

import argparse
import base64
import binascii
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from http.server import BaseHTTPRequestHandler, HTTPServer
import ipaddress
import json
import os
from pathlib import Path
import re
import socket
import ssl
import subprocess
import sys
import tempfile
from typing import Any

if __package__ in (None, ""):
    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from security_monitoring.config import canonical_root, dotenv_value, load_settings
from security_monitoring.models import HOST_REPORT_FIELDS, HOST_ROLES

SIGNATURE_NAMESPACE = "openmates-host-report"
REPORT_PATH = "/v1/host-report"
MAX_BODY_BYTES = 4 * 1024 * 1024
MAX_AGE = timedelta(hours=48)
MAX_FUTURE = timedelta(minutes=10)
NONCE_RETENTION = MAX_AGE + timedelta(hours=1)
ENVELOPE_KEYS = frozenset({"schema_version", "host_role", "host_id", "generated_at", "nonce", "contents"})
NONCE_RE = re.compile(r"^[0-9a-f]{32}$")
PUBKEY_RE = re.compile(r"^(ssh-ed25519) ([A-Za-z0-9+/]+={0,2})(?: .*)?$")
PRIVATE_NETWORKS = tuple(ipaddress.ip_network(n) for n in ("10.0.0.0/8", "172.16.0.0/12", "192.168.0.0/16", "fc00::/7"))
BIND_ENV = "SECURITY_HOST_COLLECTOR_BIND"
TOOL_TIMEOUT = 30


class Rejection(Exception):
    """A report that must not be stored. `reason` is a fixed code, safe to log and count."""

    def __init__(self, reason: str, status: int = 400) -> None:
        super().__init__(reason)
        self.reason = reason
        self.status = status


class CollectorConfigError(RuntimeError):
    """Missing or unsafe collector configuration; the collector refuses to start."""


@dataclass(frozen=True)
class CollectorPaths:
    state_dir: Path

    @property
    def collector_dir(self) -> Path:
        return self.state_dir / "collector"

    @property
    def key(self) -> Path:
        return self.collector_dir / "collector.key"

    @property
    def cert(self) -> Path:
        return self.collector_dir / "collector.crt"

    @property
    def tls_key(self) -> Path:
        return self.collector_dir / "tls.key"

    @property
    def tls_cert(self) -> Path:
        return self.collector_dir / "tls.crt"

    @property
    def config(self) -> Path:
        return self.collector_dir / "config.json"

    @property
    def nonces(self) -> Path:
        return self.collector_dir / "nonces.json"

    @property
    def rejections(self) -> Path:
        return self.collector_dir / "rejections.json"

    @property
    def allowed_signers(self) -> Path:
        return self.state_dir / "allowed_signers"

    @property
    def hosts_dir(self) -> Path:
        return self.state_dir / "hosts"


# ---------------------------------------------------------------------------
# Bind address
# ---------------------------------------------------------------------------


def is_private_network_address(address: ipaddress.IPv4Address | ipaddress.IPv6Address) -> bool:
    """RFC 1918 or IPv6 ULA only: never loopback, unspecified, link-local or public."""
    return any(address in network for network in PRIVATE_NETWORKS if network.version == address.version)


def parse_bind(value: str) -> tuple[str, int]:
    """Parse `<ip>:<port>` or `[<ipv6>]:<port>` and refuse anything but a private address."""
    text = value.strip()
    match = re.fullmatch(r"\[([0-9a-fA-F:]+)\]:(\d+)|([0-9.]+):(\d+)", text)
    if not match:
        raise CollectorConfigError(f"{BIND_ENV} must be <private-ip>:<port>")
    host = match.group(1) or match.group(3)
    port = int(match.group(2) or match.group(4))
    try:
        address = ipaddress.ip_address(host)
    except ValueError as error:
        raise CollectorConfigError(f"{BIND_ENV} host is not an IP address") from error
    if not is_private_network_address(address):
        raise CollectorConfigError("refusing to bind the collector to a non-private address")
    if not 1024 <= port <= 65535:
        raise CollectorConfigError(f"{BIND_ENV} port must be 1024-65535")
    return str(address), port


def configured_bind(paths: CollectorPaths, root: Path) -> tuple[str, int]:
    value = dotenv_value(root, BIND_ENV)
    if not value and paths.config.exists():
        data = json.loads(paths.config.read_text(encoding="utf-8"))
        value = str(data.get("bind", "")) if isinstance(data, dict) else ""
    if not value:
        raise CollectorConfigError(f"{BIND_ENV} is not configured (.env or {paths.config}); refusing to start")
    return parse_bind(value)


# ---------------------------------------------------------------------------
# Storage helpers
# ---------------------------------------------------------------------------


def write_private(path: Path, data: bytes) -> None:
    path.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
    fd, tmp = tempfile.mkstemp(dir=path.parent, prefix=f".{path.name}.")
    with os.fdopen(fd, "wb") as handle:
        handle.write(data)
    os.chmod(tmp, 0o600)
    os.replace(tmp, path)


def read_json(path: Path, default: Any) -> Any:
    return json.loads(path.read_text(encoding="utf-8")) if path.exists() else default


def parse_timestamp(value: Any) -> datetime:
    if not isinstance(value, str):
        raise Rejection("malformed_timestamp")
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError as error:
        raise Rejection("malformed_timestamp") from error
    if parsed.tzinfo is None:
        raise Rejection("malformed_timestamp")
    return parsed.astimezone(timezone.utc)


def iso(moment: datetime) -> str:
    return moment.astimezone(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def record_rejection(paths: CollectorPaths, reason: str, now: datetime) -> None:
    data = read_json(paths.rejections, {"counts": {}, "last_at": {}})
    data["counts"][reason] = int(data["counts"].get(reason, 0)) + 1
    data["last_at"][reason] = iso(now)
    write_private(paths.rejections, json.dumps(data, sort_keys=True).encode())


def rejection_summary(paths: CollectorPaths) -> dict[str, Any]:
    """Rejection counts by reason code for the digest (no addresses are ever recorded)."""
    return read_json(paths.rejections, {"counts": {}, "last_at": {}})


# ---------------------------------------------------------------------------
# Crypto via ssh-keygen and openssl
# ---------------------------------------------------------------------------


def run_tool(args: list[str], stdin: bytes | None = None) -> subprocess.CompletedProcess[bytes]:
    return subprocess.run(args, input=stdin, capture_output=True, timeout=TOOL_TIMEOUT, check=False)


def decrypt(body: bytes, paths: CollectorPaths) -> bytes:
    result = run_tool(
        ["openssl", "cms", "-decrypt", "-binary", "-inform", "DER", "-inkey", str(paths.key), "-recip", str(paths.cert)],
        stdin=body,
    )
    if result.returncode != 0:
        raise Rejection("undecryptable")
    return result.stdout


def signer_keys(paths: CollectorPaths) -> dict[str, str]:
    """Role principal -> `<type> <base64>` from allowed_signers."""
    keys: dict[str, str] = {}
    if not paths.allowed_signers.exists():
        return keys
    for line in paths.allowed_signers.read_text(encoding="utf-8").splitlines():
        parts = line.split()
        if len(parts) >= 4 and not line.startswith("#"):
            keys[parts[0]] = f"{parts[2]} {parts[3]}"
    return keys


def fingerprint(public_key: str) -> str:
    result = run_tool(["ssh-keygen", "-lf", "-"], stdin=(public_key + "\n").encode())
    parts = result.stdout.decode().split()
    if result.returncode != 0 or len(parts) < 2 or not parts[1].startswith("SHA256:"):
        raise CollectorConfigError("invalid public key")
    return parts[1]


def verify_signature(report: bytes, signature: str, paths: CollectorPaths) -> str:
    """Return the signer's role principal, or reject."""
    if not paths.allowed_signers.exists():
        raise Rejection("unknown_signer", 403)
    with tempfile.TemporaryDirectory(prefix="host-report-") as tmp:
        sig_path = Path(tmp) / "report.sig"
        sig_path.write_text(signature, encoding="utf-8")
        found = run_tool(["ssh-keygen", "-Y", "find-principals", "-s", str(sig_path), "-f", str(paths.allowed_signers)])
        principals = found.stdout.decode().split()
        if found.returncode != 0 or len(principals) != 1 or principals[0] not in HOST_ROLES:
            raise Rejection("unknown_signer", 403)
        principal = principals[0]
        verified = run_tool(
            ["ssh-keygen", "-Y", "verify", "-f", str(paths.allowed_signers), "-I", principal,
             "-n", SIGNATURE_NAMESPACE, "-s", str(sig_path)],
            stdin=report,
        )
        if verified.returncode != 0:
            raise Rejection("bad_signature", 403)
    return principal


# ---------------------------------------------------------------------------
# Validation and acceptance
# ---------------------------------------------------------------------------


def unwrap(plaintext: bytes) -> tuple[bytes, str]:
    try:
        wrapper = json.loads(plaintext)
    except (UnicodeDecodeError, json.JSONDecodeError) as error:
        raise Rejection("malformed") from error
    if not isinstance(wrapper, dict) or set(wrapper) != {"report", "signature"}:
        raise Rejection("malformed")
    if not isinstance(wrapper["report"], str) or not isinstance(wrapper["signature"], str):
        raise Rejection("malformed")
    try:
        report = base64.b64decode(wrapper["report"], validate=True)
    except binascii.Error as error:
        raise Rejection("malformed") from error
    return report, wrapper["signature"]


def validate_report(report_bytes: bytes, principal: str, paths: CollectorPaths, now: datetime) -> dict[str, Any]:
    try:
        report = json.loads(report_bytes)
    except (UnicodeDecodeError, json.JSONDecodeError) as error:
        raise Rejection("malformed") from error
    if not isinstance(report, dict) or set(report) != ENVELOPE_KEYS or report["schema_version"] != 1:
        raise Rejection("malformed")
    if report["host_role"] != principal:
        raise Rejection("role_mismatch", 403)
    contents = report["contents"]
    if not isinstance(contents, dict):
        raise Rejection("malformed")
    if set(contents) - set(HOST_REPORT_FIELDS):
        raise Rejection("field_not_allowlisted")
    if set(HOST_REPORT_FIELDS) - set(contents):
        raise Rejection("field_missing")
    if report["host_id"] != fingerprint(signer_keys(paths)[principal]):
        raise Rejection("host_id_mismatch", 403)
    if not isinstance(report["nonce"], str) or not NONCE_RE.match(report["nonce"]):
        raise Rejection("malformed")
    generated = parse_timestamp(report["generated_at"])
    if now - generated > MAX_AGE:
        raise Rejection("stale")
    if generated - now > MAX_FUTURE:
        raise Rejection("from_future")
    return report


def claim_nonce(paths: CollectorPaths, role: str, nonce: str, now: datetime) -> None:
    seen = {
        key: stamp
        for key, stamp in read_json(paths.nonces, {}).items()
        if now - parse_timestamp(stamp) <= NONCE_RETENTION
    }
    key = f"{role}:{nonce}"
    if key in seen:
        raise Rejection("replayed", 409)
    seen[key] = iso(now)
    write_private(paths.nonces, json.dumps(seen, sort_keys=True).encode())


def store(paths: CollectorPaths, report: dict[str, Any], now: datetime) -> Path:
    role_dir = paths.hosts_dir / report["host_role"]
    role_dir.mkdir(mode=0o700, parents=True, exist_ok=True)
    latest = role_dir / "latest.json"
    record = {
        "host_role": report["host_role"],
        "host_id": report["host_id"],
        "generated_at": report["generated_at"],
        "received_at": iso(now),
        "nonce": report["nonce"],
        "contents": report["contents"],
    }
    if latest.exists():
        os.replace(latest, role_dir / "previous.json")
    write_private(latest, json.dumps(record, sort_keys=True, indent=1).encode())
    return latest


def accept_report(body: bytes, paths: CollectorPaths, now: datetime | None = None) -> dict[str, Any]:
    """Validate one POST body end to end and store it. Raises Rejection (and counts it) otherwise."""
    moment = now or datetime.now(timezone.utc)
    try:
        if len(body) > MAX_BODY_BYTES:
            raise Rejection("too_large", 413)
        report_bytes, signature = unwrap(decrypt(body, paths))
        principal = verify_signature(report_bytes, signature, paths)
        report = validate_report(report_bytes, principal, paths, moment)
        claim_nonce(paths, principal, report["nonce"], moment)
        store(paths, report, moment)
    except Rejection as rejection:
        record_rejection(paths, rejection.reason, moment)
        raise
    return {"host_role": report["host_role"], "generated_at": report["generated_at"]}


# ---------------------------------------------------------------------------
# Setup commands
# ---------------------------------------------------------------------------


def init_collector(paths: CollectorPaths, bind_host: str, force: bool = False) -> None:
    if paths.key.exists() and not force:
        raise CollectorConfigError(f"{paths.key} exists; pass --force to replace (every server must then be updated)")
    paths.collector_dir.mkdir(mode=0o700, parents=True, exist_ok=True)
    os.chmod(paths.collector_dir, 0o700)
    old_umask = os.umask(0o077)
    try:
        subprocess.run(
            ["openssl", "req", "-x509", "-newkey", "rsa:3072", "-nodes", "-days", "3650",
             "-subj", "/CN=openmates-host-report-recipient", "-keyout", str(paths.key), "-out", str(paths.cert)],
            capture_output=True, timeout=120, check=True,
        )
        subprocess.run(
            ["openssl", "req", "-x509", "-newkey", "ec", "-pkeyopt", "ec_paramgen_curve:prime256v1", "-nodes",
             "-days", "1825", "-subj", "/CN=openmates-host-collector", "-addext", f"subjectAltName=IP:{bind_host}",
             "-keyout", str(paths.tls_key), "-out", str(paths.tls_cert)],
            capture_output=True, timeout=120, check=True,
        )
    finally:
        os.umask(old_umask)
    for path in (paths.cert, paths.tls_cert):
        os.chmod(path, 0o644)


def register_host(paths: CollectorPaths, role: str, pubkey: str) -> str:
    if role not in HOST_ROLES:
        raise CollectorConfigError(f"role must be one of {', '.join(HOST_ROLES)}")
    match = PUBKEY_RE.match(pubkey.strip())
    if not match:
        raise CollectorConfigError("pubkey must be one `ssh-ed25519 <base64>` line")
    key = f"{match.group(1)} {match.group(2)}"
    key_fingerprint = fingerprint(key)
    lines = [
        line for line in (paths.allowed_signers.read_text(encoding="utf-8").splitlines() if paths.allowed_signers.exists() else [])
        if line.strip() and line.split()[0] != role
    ]
    lines.append(f'{role} namespaces="{SIGNATURE_NAMESPACE}" {key}')
    write_private(paths.allowed_signers, ("\n".join(sorted(lines)) + "\n").encode())
    return key_fingerprint


# ---------------------------------------------------------------------------
# HTTPS server
# ---------------------------------------------------------------------------


class CollectorHandler(BaseHTTPRequestHandler):
    server_version = "openmates-host-collector"
    sys_version = ""
    paths: CollectorPaths

    def log_message(self, format: str, *args: Any) -> None:  # noqa: A002 - BaseHTTPRequestHandler signature
        """Suppress default access logs, which include peer addresses."""

    def _reply(self, status: int, body: dict[str, Any]) -> None:
        payload = json.dumps(body).encode()
        self.send_response(status)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(payload)))
        self.end_headers()
        self.wfile.write(payload)

    def do_GET(self) -> None:  # noqa: N802 - http.server naming
        self._reply(405, {"error": "method_not_allowed"})

    def do_POST(self) -> None:  # noqa: N802 - http.server naming
        if self.path != REPORT_PATH:
            self._reply(404, {"error": "not_found"})
            return
        length_header = self.headers.get("Content-Length", "")
        if not length_header.isdigit():
            self._reply(411, {"error": "length_required"})
            return
        length = int(length_header)
        if length > MAX_BODY_BYTES:
            record_rejection(self.paths, "too_large", datetime.now(timezone.utc))
            self._reply(413, {"error": "too_large"})
            return
        try:
            accepted = accept_report(self.rfile.read(length), self.paths)
        except Rejection as rejection:
            print(f"host report rejected: {rejection.reason}", file=sys.stderr)
            self._reply(rejection.status, {"error": rejection.reason})
            return
        print(f"host report accepted: {accepted['host_role']} {accepted['generated_at']}", file=sys.stderr)
        self._reply(202, {"status": "accepted"})


class TLSCollectorServer(HTTPServer):
    """Single-threaded server; TLS handshakes happen per connection under a timeout."""

    ssl_context: ssl.SSLContext

    def get_request(self) -> tuple[socket.socket, Any]:
        connection, peer = self.socket.accept()
        connection.settimeout(20)
        # A failed handshake raises ssl.SSLError (an OSError), which HTTPServer drops per request.
        return self.ssl_context.wrap_socket(connection, server_side=True), peer


def serve(paths: CollectorPaths, root: Path) -> None:
    host, port = configured_bind(paths, root)
    for required in (paths.key, paths.cert, paths.tls_key, paths.tls_cert):
        if not required.exists():
            raise CollectorConfigError(f"missing {required}; run init-collector first")
    context = ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER)
    context.minimum_version = ssl.TLSVersion.TLSv1_2
    context.load_cert_chain(str(paths.tls_cert), str(paths.tls_key))
    handler = type("BoundCollectorHandler", (CollectorHandler,), {"paths": paths, "timeout": 20})
    family = socket.AF_INET6 if ":" in host else socket.AF_INET
    server_class = type("CollectorServer", (TLSCollectorServer,), {"address_family": family})
    httpd = server_class((host, port), handler)
    httpd.ssl_context = context
    print(f"host collector listening on the configured private address, port {port}", file=sys.stderr)
    httpd.serve_forever()


def status(paths: CollectorPaths) -> dict[str, Any]:
    roles = {}
    for role in HOST_ROLES:
        latest = paths.hosts_dir / role / "latest.json"
        data = read_json(latest, None)
        roles[role] = {"generated_at": data["generated_at"], "received_at": data["received_at"]} if data else None
    return {"roles": roles, "rejections": rejection_summary(paths), "registered": sorted(signer_keys(paths))}


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="OpenMates private-network host report collector")
    sub = parser.add_subparsers(dest="command", required=True)
    init = sub.add_parser("init-collector", help="generate the recipient key/cert and the pinned TLS cert")
    init.add_argument("--force", action="store_true")
    register = sub.add_parser("register-host", help="allow one host signing key for a role")
    register.add_argument("--role", required=True, choices=HOST_ROLES)
    register.add_argument("--pubkey", required=True)
    sub.add_parser("serve", help="run the HTTPS collector on the configured private address")
    sub.add_parser("status", help="show latest report times and rejection counts")
    args = parser.parse_args(argv)
    root = canonical_root()
    paths = CollectorPaths(load_settings(project_root=root).state_dir)
    try:
        if args.command == "init-collector":
            host, _ = configured_bind(paths, root)
            init_collector(paths, host, force=args.force)
            print(f"Copy to each server: {paths.cert} (as collector.crt) and {paths.tls_cert} (as collector-tls.crt)")
        elif args.command == "register-host":
            print(f"registered {args.role} signer {register_host(paths, args.role, args.pubkey)}")
        elif args.command == "serve":
            serve(paths, root)
        else:
            print(json.dumps(status(paths), indent=2))
    except CollectorConfigError as error:
        print(f"host_collector: {error}", file=sys.stderr)
        return 2
    return 0


if __name__ == "__main__":
    sys.exit(main())
