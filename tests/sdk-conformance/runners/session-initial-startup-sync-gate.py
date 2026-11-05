#!/usr/bin/env python3
"""Fixed actual startup adapters using the existing bounded owned-group utility."""

# contract-test-file: tooling
from __future__ import annotations
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
CAPABILITY = "session.initial-startup-sync.v1"
FIXTURE = "tests/sdk-conformance/fixtures/session-initial-startup-sync.json"
FIXTURE_SHA256 = "9c772949c5bc42cb2fbe9fc8b557faba07a56facb452a8f0b39c522b1d9e824e"
COMMANDS = {
    "rust": [
        "cargo",
        "run",
        "--quiet",
        "--locked",
        "--manifest-path",
        "packages/openmates-session-bindings/Cargo.toml",
        "--example",
        "session-initial-startup-sync-conformance",
        "--",
    ],
    "npm": ["node", "tests/sdk-conformance/runners/session-initial-startup-sync.mjs"],
    "python": [
        sys.executable,
        "tests/sdk-conformance/runners/session-initial-startup-sync.py",
    ],
}
OWNER_CANCELLED = False


def owner_cancelled(_signal, _frame):
    global OWNER_CANCELLED
    OWNER_CANCELLED = True


def utility(root):
    name = root / "tests/sdk-conformance/runners/session-settings-reminders-gate.py"
    spec = importlib.util.spec_from_file_location(
        "startup_existing_owned_process", name
    )
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def fixture_bytes(path):
    descriptor = os.open(path, os.O_RDONLY | os.O_NOFOLLOW)
    try:
        info = os.fstat(descriptor)
        if not stat.S_ISREG(info.st_mode) or info.st_size > 64 * 1024:
            raise ValueError("fixed startup fixture required")
        raw = os.read(descriptor, 64 * 1024 + 1)
        if (
            len(raw) != info.st_size
            or hashlib.sha256(raw).hexdigest() != FIXTURE_SHA256
        ):
            raise ValueError("fixed startup fixture required")
        return raw
    finally:
        os.close(descriptor)


def validate_observed(value, language, ids):
    if (
        not isinstance(value, dict)
        or set(value)
        != {"capability", "language", "fixtureSha256", "status", "results"}
        or value["capability"] != CAPABILITY
        or value["language"] != language
        or value["fixtureSha256"] != FIXTURE_SHA256
        or value["status"] != "passed"
    ):
        raise ValueError("actual startup receipt required")
    rows = value["results"]
    if (
        not isinstance(rows, list)
        or len(rows) != len(ids)
        or any(
            not isinstance(row, dict)
            or set(row) != {"id", "status"}
            or row["status"] != "passed"
            for row in rows
        )
        or [row["id"] for row in rows] != ids
    ):
        raise ValueError("every actual startup case required in fixture order")
    return value


def execute(fixture, capability, language, root=ROOT):
    if (
        capability != CAPABILITY
        or language not in COMMANDS
        or fixture.absolute() != (root / FIXTURE).absolute()
    ):
        raise ValueError("fixed startup command required")
    owner = utility(root)
    raw = fixture_bytes(fixture)
    ids = [
        row["id"] for row in owner.document(raw)["capabilities"][CAPABILITY]["vectors"]
    ]
    if len(ids) != 10 or len(set(ids)) != 10:
        raise ValueError("ten fixed startup vectors required")
    command = [
        *COMMANDS[language],
        "--fixture",
        str(fixture),
        "--capability",
        CAPABILITY,
    ]
    status, output = owner.run_owned(command, root, cancelled=lambda: OWNER_CANCELLED)
    if status or OWNER_CANCELLED:
        raise ValueError("actual startup adapter failed")
    return validate_observed(owner.document(output), language, ids)


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--language", choices=tuple(COMMANDS), required=True)
    parser.add_argument("--fixture", type=Path, required=True)
    parser.add_argument("--capability", required=True)
    args = parser.parse_args()
    for kind in (signal.SIGTERM, signal.SIGHUP, signal.SIGINT):
        signal.signal(kind, owner_cancelled)
    try:
        print(json.dumps(execute(args.fixture, args.capability, args.language)))
    except (ValueError, OSError, KeyError, TypeError):
        print("initial startup conformance failed", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
