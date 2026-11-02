#!/usr/bin/env python3
"""Actual Rust/NAPI/PyO3 version-content calls; fixed synthetic developer harness."""

import argparse
import hashlib
import json
import sys
import threading
from pathlib import Path
from urllib.parse import urlsplit

ROOT = Path(__file__).resolve().parents[3]
CAPABILITY = "sdk.embeds.version-content"


def valid(case):
    u = urlsplit(case["endpoint"])
    assert (
        u.scheme == "http"
        and u.hostname == "127.0.0.1"
        and u.port
        and u.path == ""
        and not u.query
        and not u.fragment
        and not u.username
        and not u.password
    )
    assert (
        case["suite"]["api_key"] == "sk-api-embedOwnerA.localSetupSuffix"
        and case["suite"]["device_id"] == "synthetic-embed-device"
    )


def python_case(case):
    sys.path.insert(0, str(ROOT / "packages/openmates-python"))
    from openmates import OpenMates, OpenMatesApiError
    from openmates.session_client import SessionClientError

    s = case["suite"]
    v = case["vector"]
    client = OpenMates(
        api_key=s["api_key"], api_url=case["endpoint"], device_id=s["device_id"]
    )
    try:
        return {
            "ok": True,
            "value": client.embeds.version_content(v["embed_id"], v["version"]),
        }
    except SessionClientError as e:
        return {"ok": False, "error": e.code}
    except OpenMatesApiError as e:
        return {
            "ok": False,
            "error": {401: "authentication", 403: "forbidden", 409: "conflict"}.get(
                e.status_code,
                "invalid_argument"
                if e.status_code in (400, 404, 410, 422)
                else "offline"
                if e.status_code == 429 or e.status_code >= 500
                else "protocol",
            ),
        }


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
    assert len(vectors) == 102 and len({v["id"] for v in vectors}) == 102
    sys.path.insert(0, str(ROOT / "tests/sdk-conformance"))
    from api_key_embed_version_peer import VersionContentPeer

    # Reuse the already-owned bounded binary-pipe adapter: one absolute20s
    # deadline, bounded stdin/stdout and settled process-group cleanup.
    import importlib.util

    spec = importlib.util.spec_from_file_location(
        "_bounded_adapter", ROOT / "tests/sdk-conformance/runners/session-drafts.py"
    )
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    argv = (
        [str(a.rust_executable.resolve(strict=True)), "--case"]
        if a.language == "rust"
        else [
            "node",
            "--experimental-strip-types",
            str(ROOT / "tests/sdk-conformance/runners/sdk-embed-version-content.mjs"),
            "--case",
        ]
        if a.language == "npm"
        else [sys.executable, str(Path(__file__)), "--case"]
    )
    results = []
    for vector in vectors:
        peer = VersionContentPeer(suite, vector, a.language)
        server = peer.server()
        thread = threading.Thread(
            target=server.serve_forever, kwargs={"poll_interval": 0.02}, daemon=True
        )
        thread.start()
        try:
            observed = module.invoke(
                argv,
                {
                    "endpoint": f"http://127.0.0.1:{server.server_address[1]}",
                    "suite": suite,
                    "vector": vector,
                },
            )
            peer.check(observed)
            results.append({"id": vector["id"], "status": "passed"})
        finally:
            server.shutdown()
            server.server_close()
            thread.join(timeout=2)
            assert not thread.is_alive()
    print(
        json.dumps(
            {
                "capability": CAPABILITY,
                "language": a.language,
                "status": "passed",
                "fixtureSha256": hashlib.sha256(raw).hexdigest(),
                "results": results,
            }
        )
    )


if __name__ == "__main__":
    try:
        main()
    except Exception:
        print("Version-content conformance failed", file=sys.stderr)
        raise SystemExit(1)
