#!/usr/bin/env python3
"""Actual API-key library adapters against an independent shared history peer.

Only this developer harness spawns adapters; no SDK production code spawns CLI,
Python or Node. SDK child inputs use synthetic credentials via a private pipe.
"""

# contract-test-file: tooling
from __future__ import annotations
import argparse
import hashlib
import json
import os
from pathlib import Path
import signal
import subprocess
import sys
import threading
from urllib.parse import urlsplit

ROOT = Path(__file__).resolve().parents[3]
CAPABILITY = "sdk.history"
DEADLINE = 20


def python_case(case):
    sys.path.insert(0, str(ROOT / "packages/openmates-python"))
    from openmates import OpenMates, OpenMatesApiError

    client = OpenMates(
        api_key=case["api_key"], api_url=case["endpoint"], device_id=case["device_id"]
    )
    vector = case["vector"]
    try:
        op = vector["operation"]
        if op == "list":
            value = client.history.list(**vector["filters"])
        elif op == "show":
            value = client.history.show(vector["change_set_id"])
        elif op == "undo":
            value = client.history.undo(vector["change_set_id"])
        else:
            raise AssertionError("unknown history operation")
        return {"ok": True, "value": value}
    except OpenMatesApiError as error:
        status = error.status_code
        code = {401: "authentication", 403: "forbidden", 409: "conflict"}.get(status)
        code = code or (
            "invalid"
            if status in (400, 404, 410, 422)
            else "offline"
            if status == 429 or status >= 500
            else "protocol"
        )
        return {"ok": False, "error": code, "http_status": status}


def validate_case(case):
    endpoint = urlsplit(case["endpoint"])
    assert (
        endpoint.scheme == "http" and endpoint.hostname == "127.0.0.1" and endpoint.port
    )
    assert endpoint.path == "" and not endpoint.query and not endpoint.fragment
    assert case["device_id"] == "synthetic-history-device"
    assert case["api_key"] in (
        "sk-api-historyOwnerA.localSetupSuffix",
        "sk-api-historyOwnerB.localSetupSuffix",
    )


def command(language, rust_binary):
    if language == "python":
        return [sys.executable, str(Path(__file__)), "--case"]
    if language == "npm":
        return [
            "node",
            "--experimental-strip-types",
            str(ROOT / "tests/sdk-conformance/runners/sdk-api-key-history.mjs"),
            "--case",
        ]
    binary = Path(rust_binary).resolve(strict=True)
    assert binary.is_file()
    return [str(binary), "--case"]


def adapter(argv, case):
    child = subprocess.Popen(
        argv,
        cwd=ROOT,
        stdin=subprocess.PIPE,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        start_new_session=True,
    )
    try:
        out, _err = child.communicate(json.dumps(case).encode(), timeout=DEADLINE)
        assert child.returncode == 0, "history adapter failed"
        assert len(out) <= 1024 * 1024, "history adapter output bound"
        return json.loads(out)
    finally:
        if child.poll() is None:
            os.killpg(child.pid, signal.SIGKILL)
            child.wait(timeout=2)


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--case", action="store_true")
    parser.add_argument("--fixture")
    parser.add_argument("--capability")
    parser.add_argument(
        "--language", choices=("rust", "npm", "python"), default="python"
    )
    parser.add_argument("--rust-executable")
    args = parser.parse_args()
    if args.case:
        raw = sys.stdin.buffer.read(1024 * 1024 + 1)
        assert len(raw) <= 1024 * 1024
        case = json.loads(raw)
        validate_case(case)
        print(json.dumps(python_case(case), ensure_ascii=False))
        return
    assert args.capability == CAPABILITY
    fixture = Path(args.fixture).resolve(strict=True)
    raw = fixture.read_bytes()
    assert len(raw) <= 1024 * 1024
    document = json.loads(raw)
    suite = document["capabilities"][CAPABILITY]
    vectors = suite["vectors"]
    assert 1 <= len(vectors) <= 32 and len({v["id"] for v in vectors}) == len(vectors)
    sys.path.insert(0, str(ROOT / "tests/sdk-conformance"))
    from api_key_history_peer import HistoryPeer

    argv = command(args.language, args.rust_executable)
    results = []
    for vector in vectors:
        peer = HistoryPeer(suite, vector, args.language)
        server = peer.server()
        thread = threading.Thread(
            target=server.serve_forever, kwargs={"poll_interval": 0.02}, daemon=True
        )
        thread.start()
        try:
            case = {
                "endpoint": f"http://127.0.0.1:{server.server_address[1]}",
                "api_key": suite["api_keys"][vector["owner"]],
                "device_id": suite["device_id"],
                "vector": vector,
            }
            observed = adapter(argv, case)
            assert (
                peer.failure is None
                and peer.requests == vector["expected_request_count"]
            ), "history exact wire/no retries"
            if vector["expected_error"]:
                assert (
                    observed["ok"] is False
                    and observed["error"] == vector["expected_error"]
                ), "typed history refusal"
                if args.language != "rust":
                    assert observed["http_status"] == vector["http_status"], (
                        "existing HTTP error status"
                    )
            else:
                assert observed == {"ok": True, "value": vector["expected"]}, (
                    "exact metadata/opaque entry output"
                )
            results.append({"id": vector["id"], "status": "passed"})
        finally:
            server.shutdown()
            server.server_close()
            thread.join(timeout=2)
            assert not thread.is_alive(), "history peer cleanup failed"
    print(
        json.dumps(
            {
                "capability": CAPABILITY,
                "language": args.language,
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
        print("history adapter conformance failed", file=sys.stderr)
        raise SystemExit(1)
