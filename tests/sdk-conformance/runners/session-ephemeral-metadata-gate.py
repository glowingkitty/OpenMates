#!/usr/bin/env python3
"""Fixed three-language direct library gate. Authored UNRUN, never release proof.

Each independent synthetic peer lives in this owner; each actual adapter lives
in a separately reserved bounded process group using the maintained utility.
No adapter launches CLI, account login, another peer or inference.
"""

# contract-test-file: tooling
import argparse
import hashlib
import importlib.util
import json
import os
from pathlib import Path
import signal
import stat
import sys

ROOT = Path(__file__).resolve().parents[3]
CAPABILITY = "session.ephemeral-metadata-startup.v1"
FIXTURE = "tests/sdk-conformance/fixtures/session-ephemeral-metadata.json"
FIXTURE_SHA256 = "b12e0435615ff939ccc7a82eaa01f8782f3107df09c2e193cac333759a67a68b"
COMMANDS = {
    "rust": [
        "cargo",
        "run",
        "--quiet",
        "--locked",
        "--manifest-path",
        "packages/openmates-session-bindings/Cargo.toml",
        "--example",
        "session-ephemeral-metadata-conformance",
        "--",
    ],
    "npm": ["node", "tests/sdk-conformance/runners/session-ephemeral-metadata.mjs"],
    "python": [
        sys.executable,
        "tests/sdk-conformance/runners/session-ephemeral-metadata.py",
    ],
}
OWNER_CANCELLED = False


def cancelled(_signal, _frame):
    global OWNER_CANCELLED
    OWNER_CANCELLED = True


def utility(root):
    path = root / "tests/sdk-conformance/runners/session-settings-reminders-gate.py"
    spec = importlib.util.spec_from_file_location(
        "metadata_existing_owned_process", path
    )
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def fixture_bytes(path):
    fd = os.open(path, os.O_RDONLY | os.O_NOFOLLOW)
    try:
        info = os.fstat(fd)
        if not stat.S_ISREG(info.st_mode) or info.st_size > 65536:
            raise ValueError("fixed metadata fixture required")
        raw = os.read(fd, 65537)
        if (
            len(raw) != info.st_size
            or hashlib.sha256(raw).hexdigest() != FIXTURE_SHA256
        ):
            raise ValueError("fixed metadata fixture required")
        return raw
    finally:
        os.close(fd)


def validate_observed(value, language, ids, lifecycles=None):
    if (
        not isinstance(value, dict)
        or set(value)
        != {"capability", "language", "fixtureSha256", "status", "results"}
        or value["capability"] != CAPABILITY
        or value["language"] != language
        or value["fixtureSha256"] != FIXTURE_SHA256
        or value["status"] != "passed"
    ):
        raise ValueError("actual metadata receipt required")
    rows = value["results"]
    lifecycles = lifecycles or {}
    if not isinstance(rows, list) or len(rows) != len(ids):
        raise ValueError("every actual metadata case required in order")
    for name, row in zip(ids, rows):
        expected = {"id": name, "status": "passed"}
        if name in lifecycles:
            expected["lifecycle"] = lifecycles[name][language]
        if row != expected:
            raise ValueError(
                "every actual metadata case and supported lifecycle required in order"
            )
    return value


def execute(fixture, capability, language, root=ROOT):
    if (
        capability != CAPABILITY
        or language not in COMMANDS
        or fixture.absolute() != (root / FIXTURE).absolute()
    ):
        raise ValueError("fixed metadata invocation required")
    owner = utility(root)
    raw = fixture_bytes(fixture)
    suite = owner.document(raw)["capabilities"][CAPABILITY]
    vectors = suite["vectors"]
    ids = [row["id"] for row in vectors]
    if len(ids) != 29 or len(set(ids)) != 29 or "master_key" in suite["account"]:
        raise ValueError("twenty-nine no-key cases required")
    lifecycles = {row["id"]: row["lifecycle"] for row in vectors if "lifecycle" in row}
    sys.path.insert(0, str(root / "tests/sdk-conformance"))
    from ephemeral_metadata_server import MetadataPeer

    results = []
    for vector in vectors:
        if OWNER_CANCELLED:
            raise ValueError("metadata owner cancelled")
        peer = MetadataPeer(
            suite, vector, "pip" if language == "python" else language
        ).start()
        try:
            command = [
                *COMMANDS[language],
                "--fixture",
                str(fixture),
                "--vector",
                vector["id"],
                "--endpoint",
                peer.endpoint,
            ]
            status, output = owner.run_owned(
                command, root, timeout=100, cancelled=lambda: OWNER_CANCELLED
            )
            if status or OWNER_CANCELLED:
                raise ValueError("actual metadata adapter failed")
            row = owner.document(output)
            expected = {"id": vector["id"], "status": "passed"}
            if "lifecycle" in vector:
                expected["lifecycle"] = vector["lifecycle"][language]
            if row != expected:
                raise ValueError("actual vector result required")
            mode = vector["mode"]
            connections = vector.get("connections", 1)
            if connections and not peer.closed.wait(2):
                raise ValueError("actual original socket disconnect required")
            observed = peer.status()
            if observed["failure"] is not None or observed["unexpected"] != 0:
                raise ValueError("peer rejected protocol")
            auth = vector.get("auth_requests", 3 if mode == "foreign_snapshot" else 2)
            if (
                observed["auth_requests"] != auth
                or observed["connections"] != connections
                or observed["disconnects"] != connections
            ):
                raise ValueError("actual auth/socket lifecycle required")
            if observed["startup_requests"] != connections or observed[
                "metadata_requests"
            ] != (connections if mode != "small" else 0):
                raise ValueError("actual bounded startup exchange required")
            if mode in {
                "late_invalid_cookie",
                "late_undecodable_cookie",
                "malformed_body",
                "truncated_body",
                "held_malformed_body",
                "cancel_before_headers",
                "cancel_after_headers",
                "foreign_auth_cancel",
                "early_invalid_cookie",
                "early_undecodable_cookie",
            }:
                if not peer.auth_finished.wait(2):
                    raise ValueError("bounded actual auth peer completion required")
                observed = peer.status()
                if observed["auth_active"] != 0:
                    raise ValueError("original auth IO still held")
                expected_events = ["request"]
                if mode == "cancel_before_headers":
                    expected_events += ["before_headers_held", "released"]
                expected_events += ["headers_flushed"]
                if mode in {
                    "held_malformed_body",
                    "cancel_after_headers",
                    "foreign_auth_cancel",
                }:
                    expected_events += ["body_held", "released"]
                expected_events += [
                    "body_truncated" if mode == "truncated_body" else "body_written"
                ]
                if observed["auth_events"] != expected_events:
                    raise ValueError("actual auth header/body order required")
            results.append(row)
        finally:
            peer.close()
    return validate_observed(
        {
            "capability": CAPABILITY,
            "language": language,
            "fixtureSha256": FIXTURE_SHA256,
            "status": "passed",
            "results": results,
        },
        language,
        ids,
        lifecycles,
    )


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--language", choices=tuple(COMMANDS), required=True)
    parser.add_argument("--fixture", type=Path, required=True)
    parser.add_argument("--capability", required=True)
    args = parser.parse_args()
    for kind in (signal.SIGTERM, signal.SIGHUP, signal.SIGINT):
        signal.signal(kind, cancelled)
    try:
        print(json.dumps(execute(args.fixture, args.capability, args.language)))
    except Exception:
        print("opaque metadata library conformance failed", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
