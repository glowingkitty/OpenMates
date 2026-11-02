#!/usr/bin/env python3
"""Thin fixed gate protocol adapter; all read assertions execute in public libraries."""

# contract-test-file: tooling
from __future__ import annotations
import argparse
import hashlib
import json
import os
import selectors
import signal
import time
from pathlib import Path
import subprocess
import sys

ROOT = Path(__file__).resolve().parents[3]
CAPABILITY = "session.settings-reminders-read"
SOURCE = "tests/sdk-conformance/fixtures/session-settings-reminders-read.json"
SOURCE_SHA256 = "78885103ff46073bb19c0dc9f7b10373f84e06889f0440cf5888c79c0be7ea18"
COMMANDS = {
    "rust": [
        "cargo",
        "run",
        "--quiet",
        "--locked",
        "--manifest-path",
        "packages/openmates-rust/Cargo.toml",
        "--example",
        "sdk-session-settings-reminders-read-conformance",
        "--",
    ],
    "npm": [
        "node",
        "tests/sdk-conformance/runners/session-settings-reminders-read.mjs",
    ],
    "python": [
        sys.executable,
        "tests/sdk-conformance/runners/session-settings-reminders-read.py",
    ],
}


def document(raw):
    if len(raw) > 1024 * 1024:
        raise ValueError("bounded fixture required")
    return json.loads(raw)


def validate_projection(raw, canonical):
    if hashlib.sha256(canonical).hexdigest() != SOURCE_SHA256:
        raise ValueError("canonical reminders source identity mismatch")
    source = document(canonical)
    if source.get("capability") != CAPABILITY or len(source.get("cases", [])) != 28:
        raise ValueError("canonical reminders cases mismatch")
    ids = [case["id"] for case in source["cases"]]
    if len(set(ids)) != 28:
        raise ValueError("canonical reminders case IDs mismatch")
    projection = document(raw)
    expected = {
        CAPABILITY: {
            "source_fixture": SOURCE,
            "source_sha256": SOURCE_SHA256,
            "vectors": [{"id": identity} for identity in ids],
        }
    }
    if (
        set(projection) != {"schema_version", "provenance", "capabilities"}
        or type(projection["schema_version"]) is not int
        or projection["schema_version"] != 1
        or not isinstance(projection["provenance"], str)
        or projection["capabilities"] != expected
    ):
        raise ValueError("reminders gate projection mismatch")
    return ids


def validate_observed(result, language, ids):
    for key, expected in {
        "capability": CAPABILITY,
        "language": language,
        "status": "passed",
        "fixtureSha256": SOURCE_SHA256,
    }.items():
        if result.get(key) != expected:
            raise ValueError("native reminders result mismatch: " + key)
    observed = result.get("results")
    if not isinstance(observed, list) or len(observed) != len(ids):
        raise ValueError("native reminders missing per-case assertions")
    if any(
        not isinstance(item, dict)
        or item.get("status") != "passed"
        or item.get("id") != identity
        for item, identity in zip(observed, ids)
    ):
        raise ValueError("native reminders failed, duplicated or reordered assertions")
    # Preserve the actual runner's per-case observations. Never create passed rows here.
    return result


OWNER_CANCELLED = False
STREAM_LIMIT = 64 * 1024


def cancel_owner(_signal, _frame):
    # Signal handlers only set state, so repeated cancellation cannot interrupt cleanup.
    global OWNER_CANCELLED
    OWNER_CANCELLED = True


def run_owned(
    command, root, *, timeout=480, stream_limit=STREAM_LIMIT, cancelled=lambda: False
):
    """Bound both streams and retire only this new group before reaping its leader."""
    if cancelled():
        raise ValueError("reminders owner cancelled")
    child = subprocess.Popen(
        command,
        cwd=root,
        stdin=subprocess.DEVNULL,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        start_new_session=True,
    )
    stdout = bytearray()
    sizes = {"stdout": 0, "stderr": 0}
    deadline = time.monotonic() + timeout
    exited_at = None
    try:
        with selectors.DefaultSelector() as streams:
            streams.register(child.stdout, selectors.EVENT_READ, "stdout")
            streams.register(child.stderr, selectors.EVENT_READ, "stderr")
            while True:
                now = time.monotonic()
                if cancelled():
                    raise ValueError("reminders owner cancelled")
                if now >= deadline:
                    raise ValueError("reminders library runner deadline")
                # WNOWAIT keeps our leader PID reserved until owned-group cleanup.
                ended = os.waitid(
                    os.P_PID, child.pid, os.WEXITED | os.WNOHANG | os.WNOWAIT
                )
                if ended is not None:
                    if not streams.get_map():
                        break
                    exited_at = now if exited_at is None else exited_at
                    if now - exited_at >= 0.25:
                        raise ValueError("reminders descendant retained output pipes")
                for key, _ in streams.select(min(0.05, max(0, deadline - now))):
                    chunk = os.read(key.fd, 4096)
                    if not chunk:
                        streams.unregister(key.fileobj)
                        continue
                    sizes[key.data] += len(chunk)
                    if sizes[key.data] > stream_limit:
                        raise ValueError("reminders library output limit")
                    if key.data == "stdout":
                        stdout.extend(chunk)
                    # stderr is counted and discarded; private output never becomes a receipt.
    finally:
        # Leader remains unreaped until both signals target its reserved owned group.
        try:
            try:
                os.killpg(child.pid, signal.SIGTERM)
            except ProcessLookupError:
                pass
            time.sleep(0.15)
            try:
                os.killpg(child.pid, signal.SIGKILL)
            except ProcessLookupError:
                pass
            child.wait(timeout=1)
        finally:
            child.stdout.close()
            child.stderr.close()
    return child.returncode, bytes(stdout)


def execute(fixture, capability, language, root=ROOT):
    if capability != CAPABILITY:
        raise ValueError("fixed reminders capability required")
    projection = fixture.read_bytes()
    canonical_path = root / SOURCE
    ids = validate_projection(projection, canonical_path.read_bytes())
    command = [
        *COMMANDS[language],
        "--fixture",
        str(canonical_path),
        "--capability",
        CAPABILITY,
    ]
    returncode, output = run_owned(command, root, cancelled=lambda: OWNER_CANCELLED)
    if returncode:
        raise ValueError("actual reminders library runner failed: " + language)
    if OWNER_CANCELLED:
        raise ValueError("reminders owner cancelled")
    observed = validate_observed(json.loads(output), language, ids)
    # Bind the standard gate receipt to its projection while retaining raw-source identity.
    observed["canonicalFixtureSha256"] = observed["fixtureSha256"]
    observed["fixtureSha256"] = hashlib.sha256(projection).hexdigest()
    return observed


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--fixture", type=Path, required=True)
    parser.add_argument("--capability", choices=[CAPABILITY], required=True)
    parser.add_argument("--language", choices=list(COMMANDS), required=True)
    args = parser.parse_args()
    previous = {
        kind: signal.getsignal(kind)
        for kind in (signal.SIGTERM, signal.SIGHUP, signal.SIGINT)
    }
    try:
        for kind in previous:
            signal.signal(kind, cancel_owner)
        print(json.dumps(execute(args.fixture, args.capability, args.language)))
    finally:
        for kind, handler in previous.items():
            signal.signal(kind, handler)


if __name__ == "__main__":
    try:
        main()
    except Exception:
        print("Reminders library gate failed", file=sys.stderr)
        raise SystemExit(1)
