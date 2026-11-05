"""Actual public API-key chat reads (list/search/load) in Rust, npm and Python.

Each vector starts an independent synthetic peer; the adapter calls the real
library and the peer checks routes, credentials and the decrypted projection.
Only this developer harness spawns adapters; SDK code never spawns anything.
"""

from __future__ import annotations

import argparse
import hashlib
import importlib.util
import json
import sys
import threading
from pathlib import Path
from urllib.parse import urlsplit

ROOT = Path(__file__).resolve().parents[3]
CAPABILITY = "sdk.chats"
API_KEY = "sk-api-chatOwnerA.localSetupSuffix"
DEVICE = "synthetic-chat-device"
VECTORS = 16


def valid(case):
    u = urlsplit(case["endpoint"])
    assert u.scheme == "http" and u.hostname == "127.0.0.1" and u.port
    assert u.path == "" and not u.query and not u.fragment and not u.username and not u.password
    assert case["api_key"] == API_KEY and case["device_id"] == DEVICE


def http_code(status):
    return {401: "authentication", 403: "forbidden", 409: "conflict"}.get(status) or (
        "invalid" if status in (400, 404, 410, 422) else "offline" if status == 429 or status >= 500 else "protocol"
    )


def python_case(case):
    sys.path.insert(0, str(ROOT / "packages/openmates-python"))
    from openmates import OpenMates, OpenMatesApiError, OpenMatesConfigError

    client = OpenMates(api_key=case["api_key"], api_url=case["endpoint"], device_id=case["device_id"])
    v = case["vector"]
    a = v["arguments"]
    try:
        if v["operation"] == "list":
            value = client.chats.list(limit=a.get("limit", 10), offset=a.get("offset", 0))
        elif v["operation"] == "search":
            value = client.chats.search(a["query"], limit=a.get("limit", 10), offset=a.get("offset", 0))
        else:
            assert v["operation"] == "load"
            value = client.chats.load(a["chat_id"])
        return {"ok": True, "value": value}
    except OpenMatesApiError as error:
        return {"ok": False, "error": http_code(error.status_code)}
    except OpenMatesConfigError:
        return {"ok": False, "error": "invalid"}


def adapter_command(language, rust_executable):
    if language == "rust":
        return [str(rust_executable.resolve(strict=True)), "--case"]
    if language == "npm":
        return ["node", "--experimental-strip-types", str(ROOT / "tests/sdk-conformance/runners/sdk-api-key-chats.mjs"), "--case"]
    return [sys.executable, str(Path(__file__)), "--case"]


def main():
    p = argparse.ArgumentParser()
    p.add_argument("--case", action="store_true")
    p.add_argument("--fixture", type=Path)
    p.add_argument("--capability")
    p.add_argument("--language", choices=["rust", "npm", "python"], default="python")
    p.add_argument("--rust-executable", type=Path)
    a = p.parse_args()
    if a.case:
        raw = sys.stdin.buffer.read(1024 * 1024 + 1)
        assert len(raw) <= 1024 * 1024
        case = json.loads(raw)
        valid(case)
        print(json.dumps(python_case(case)))
        return
    assert a.capability == CAPABILITY and a.fixture
    raw = a.fixture.read_bytes()
    assert len(raw) <= 1024 * 1024
    suite = json.loads(raw)["capabilities"][CAPABILITY]
    vectors = suite["vectors"]
    assert len(vectors) == VECTORS and len({v["id"] for v in vectors}) == VECTORS
    sys.path.insert(0, str(ROOT / "tests/sdk-conformance"))
    from api_key_chats_peer import ChatsPeer

    # Reuse the bounded binary-pipe adapter: one 20 s deadline, bounded
    # stdin/stdout and settled process-group cleanup.
    spec = importlib.util.spec_from_file_location("_bounded_adapter", ROOT / "tests/sdk-conformance/runners/session-drafts.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    argv = adapter_command(a.language, a.rust_executable)
    results = []
    for vector in vectors:
        peer = ChatsPeer(suite, vector, a.language)
        server = peer.server()
        thread = threading.Thread(target=server.serve_forever, kwargs={"poll_interval": 0.02}, daemon=True)
        thread.start()
        try:
            observed = module.invoke(argv, {
                "endpoint": f"http://127.0.0.1:{server.server_address[1]}",
                "api_key": suite["api_key"],
                "device_id": suite["device_id"],
                "vector": vector,
            })
            try:
                peer.check(observed)
            except AssertionError as error:
                print(f"sdk.chats/{a.language} vector {vector['id']} failed: {error}", file=sys.stderr)
                raise
            results.append({"id": vector["id"], "status": "passed"})
        finally:
            server.shutdown()
            server.server_close()
            thread.join(timeout=2)
            assert not thread.is_alive()
    print(json.dumps({
        "capability": CAPABILITY,
        "language": a.language,
        "status": "passed",
        "fixtureSha256": hashlib.sha256(raw).hexdigest(),
        "results": results,
    }))


if __name__ == "__main__":
    try:
        main()
    except Exception as error:
        print(f"Chat conformance failed: {type(error).__name__}", file=sys.stderr)
        raise SystemExit(1)
