"""Actual public API-key billing and memories calls in Rust, npm and Python.

Gate capabilities sdk.billing and sdk.memories. Each vector starts an
independent synthetic peer (tests/sdk-conformance/api_key_wire_peer.py); the
adapter calls the real library once and prints a language-neutral projection
(raw downloads as content_type/filename/data_b64, errors as stable codes), and
the peer checks routes, credentials and the decoded result. No real backend,
purchase, refund or deletion is involved. Only this harness spawns adapters.
"""
# contract-test-file: tooling

from __future__ import annotations

import argparse
import base64
import hashlib
import importlib.util
import json
import sys
import threading
from pathlib import Path
from urllib.parse import urlsplit

ROOT = Path(__file__).resolve().parents[3]
CAPABILITIES = {"sdk.billing", "sdk.memories"}
API_KEY = "sk-api-wireOwner.localSetupSuffix"
DEVICE = "synthetic-wire-device"
sys.path.insert(0, str(ROOT / "tests/sdk-conformance"))
from api_key_wire_peer import WirePeer, error_code  # noqa: E402 - harness path set just above


def valid(case: dict) -> None:
    u = urlsplit(case["endpoint"])
    assert u.scheme == "http" and u.hostname == "127.0.0.1" and u.port
    assert u.path == "" and not u.query and not u.fragment and not u.username and not u.password
    assert case["api_key"] == API_KEY and case["device_id"] == DEVICE


def project(value):
    """Language-neutral view: a RawDownload becomes content_type/filename/data_b64."""
    from openmates import RawDownload

    if isinstance(value, RawDownload):
        return {"content_type": value.content_type, "filename": value.filename, "data_b64": base64.b64encode(value.data).decode()}
    return value


def python_case(case: dict) -> dict:
    sys.path.insert(0, str(ROOT / "packages/openmates-python"))
    from openmates import OpenMates, OpenMatesApiError, OpenMatesConfigError

    client = OpenMates(api_key=case["api_key"], api_url=case["endpoint"], device_id=case["device_id"])
    v = case["vector"]
    namespace, method = v["operation"].split(".")
    kwargs = dict(v["kwargs"])
    if "query" in v:
        kwargs.update(dict(v["query"]))
    if "confirmed" in v:
        kwargs["confirmed"] = v["confirmed"]
    try:
        value = getattr(getattr(client, namespace), method)(*v["args"], **kwargs)
        return {"ok": True, "value": project(value)}
    except OpenMatesApiError as error:
        return {"ok": False, "error": error_code(error.status_code)}
    except OpenMatesConfigError:
        return {"ok": False, "error": "invalid"}


def adapter_command(language: str, rust_executable: Path | None) -> list[str]:
    if language == "rust":
        return [str(rust_executable.resolve(strict=True)), "--case"]
    if language == "npm":
        return ["node", "--experimental-strip-types", str(ROOT / "tests/sdk-conformance/runners/sdk-api-key-wire.mjs"), "--case"]
    return [sys.executable, str(Path(__file__)), "--case"]


def main() -> None:
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
    assert a.capability in CAPABILITIES and a.fixture
    raw = a.fixture.read_bytes()
    assert len(raw) <= 1024 * 1024
    suite = json.loads(raw)["capabilities"][a.capability]
    vectors = suite["vectors"]
    assert vectors and len({v["id"] for v in vectors}) == len(vectors)
    # Reuse the bounded binary-pipe adapter: one 20 s deadline, bounded
    # stdin/stdout and settled process-group cleanup.
    spec = importlib.util.spec_from_file_location("_bounded_adapter", ROOT / "tests/sdk-conformance/runners/session-drafts.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    argv = adapter_command(a.language, a.rust_executable)
    results = []
    for vector in vectors:
        peer = WirePeer(suite, vector, a.language)
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
                print(f"{a.capability}/{a.language} vector {vector['id']} failed: {error}", file=sys.stderr)
                raise
            results.append({"id": vector["id"], "status": "passed"})
        finally:
            server.shutdown()
            server.server_close()
            thread.join(timeout=2)
            assert not thread.is_alive()
    print(json.dumps({
        "capability": a.capability,
        "language": a.language,
        "status": "passed",
        "fixtureSha256": hashlib.sha256(raw).hexdigest(),
        "results": results,
    }))


if __name__ == "__main__":
    try:
        main()
    except Exception as error:  # noqa: BLE001 - harness boundary: report class only, exit nonzero
        print(f"API-key wire conformance failed: {type(error).__name__}: {error}", file=sys.stderr)
        raise SystemExit(1)
