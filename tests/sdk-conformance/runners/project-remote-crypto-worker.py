#!/usr/bin/env python3
"""Direct public Python library worker for the independent harness; never a CLI."""

# contract-test-file: tooling
from __future__ import annotations
import base64
import json
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(ROOT / "packages/openmates-python"))
from openmates import RemoteHandshake  # noqa: E402 - import follows sys.path setup for sibling runner modules


def decode(value):
    return base64.urlsafe_b64decode(value + "=" * ((-len(value)) % 4))


def encode(value):
    return base64.urlsafe_b64encode(value).rstrip(b"=").decode()


pending = session = None
while True:
    line = sys.stdin.buffer.readline(1024 * 1024 + 1)
    if not line:
        break
    if len(line) > 1024 * 1024 or not line.endswith(b"\n"):
        raise SystemExit(1)
    item = None
    try:
        item = json.loads(line)
        op = item["op"]
        if op == "new":
            if pending is not None:
                pending.close()
            if session is not None:
                session.close()
            pending = session = None
            pending = RemoteHandshake(
                decode(item["key"]), item["identity"], item["role"]
            )
            value = pending.handshake()
        elif op == "handshake":
            value = pending.handshake()
        elif op == "finish":
            session = pending.finish(item["remote"])
            value = None
        elif op == "seal":
            value = session.seal(item["id"], decode(item["plaintext"]))
        elif op == "open":
            value = encode(session.open(item["id"], item["envelope"]))
        elif op == "open_json_text":
            value = session.open_json_text(item["id"], item["envelope"])
        elif op == "close_handshake":
            pending.close()
            value = None
        elif op == "close_session":
            session.close()
            value = None
        else:
            raise ValueError("fixed worker operation")
        output = {"ok": True, "value": value}
    except Exception as error:
        output = {"ok": False, "code": getattr(error, "code", "protocol")}
    output["sequence"] = item.get("sequence") if isinstance(item, dict) else None
    sys.stdout.write(json.dumps(output, separators=(",", ":")) + "\n")
    sys.stdout.flush()
if pending is not None:
    pending.close()
if session is not None:
    session.close()
