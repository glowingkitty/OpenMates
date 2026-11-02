#!/usr/bin/env python3
"""Actual three-library conformance against one independent Python cryptography peer.
Worker subprocesses are test harness adapters only; product SDKs never launch them.
"""

# contract-test-file: tooling
from __future__ import annotations
import argparse
import copy
import hashlib
import json
import os
from pathlib import Path
import selectors
import signal
import subprocess
import sys
import time

ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(ROOT / "tests/sdk-conformance"))
from remote_crypto_peer import IndependentPeer, decode, encode  # noqa: E402 - import follows sys.path setup for sibling runner modules

CAPABILITY = "protocol.project-remote-crypto.v1"
COMMANDS = {
    "rust": [
        "cargo",
        "run",
        "--quiet",
        "--locked",
        "--manifest-path",
        "packages/openmates-session-bindings/Cargo.toml",
        "--example",
        "project-remote-crypto-worker",
        "--",
    ],
    "npm": ["node", "tests/sdk-conformance/runners/project-remote-crypto-worker.mjs"],
    "python": [
        sys.executable,
        "tests/sdk-conformance/runners/project-remote-crypto-worker.py",
    ],
}
CANCELLED = False
TOTAL_SECONDS = 480
STARTUP_SECONDS = 180
RESPONSE_SECONDS = 15
MAX_REQUEST_BYTES = 1024 * 1024
MAX_RESPONSE_BYTES = 1024 * 1024
MAX_STDOUT_BYTES = 8 * 1024 * 1024
MAX_STDERR_BYTES = 65536


def cancelled(_signal, _frame):
    global CANCELLED
    CANCELLED = True


class Worker:
    """Bounded interactive owned test process. No wire data enters diagnostics."""

    def __init__(self, language):
        if CANCELLED:
            raise ValueError("owner cancelled")
        self.process = None
        self.closed = False
        self.streams = selectors.DefaultSelector()
        try:
            self.process = subprocess.Popen(
                COMMANDS[language],
                cwd=ROOT,
                stdin=subprocess.PIPE,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                start_new_session=True,
            )
            self.streams.register(self.process.stdout, selectors.EVENT_READ, "stdout")
            self.streams.register(self.process.stderr, selectors.EVENT_READ, "stderr")
            self.output = bytearray()
            self.stdout_bytes = 0
            self.stderr_bytes = 0
            self.sequence = 0
            self.deadline = time.monotonic() + TOTAL_SECONDS
        except BaseException:
            self.close()
            raise

    def close(self):
        if self.closed:
            return
        self.closed = True
        if self.process is None:
            self.streams.close()
            return
        try:
            try:
                os.killpg(self.process.pid, signal.SIGTERM)
            except ProcessLookupError:
                pass
            time.sleep(0.15)
            try:
                os.killpg(self.process.pid, signal.SIGKILL)
            except ProcessLookupError:
                pass
            self.process.wait(timeout=1)
        finally:
            self.streams.close()
            self.process.stdin.close()
            self.process.stdout.close()
            self.process.stderr.close()

    def call(self, item):
        self.sequence += 1
        wire = (
            json.dumps(
                {**item, "sequence": self.sequence},
                ensure_ascii=True,
                separators=(",", ":"),
            ).encode()
            + b"\n"
        )
        if len(wire) > MAX_REQUEST_BYTES or self.output:
            raise ValueError("worker protocol bound")
        response_deadline = min(
            self.deadline,
            time.monotonic()
            + (STARTUP_SECONDS if self.sequence == 1 else RESPONSE_SECONDS),
        )
        os.set_blocking(self.process.stdin.fileno(), False)
        self.streams.register(self.process.stdin, selectors.EVENT_WRITE, "stdin")
        offset = 0
        try:
            while True:
                if CANCELLED:
                    raise ValueError("owner cancelled")
                if time.monotonic() >= self.deadline:
                    raise ValueError("worker deadline")
                if time.monotonic() >= response_deadline:
                    raise ValueError("worker response deadline")
                # Keep the owned leader unreaped until group cleanup; inherited
                # pipes cannot make an exited library worker appear alive.
                if (
                    os.waitid(
                        os.P_PID, self.process.pid, os.WEXITED | os.WNOHANG | os.WNOWAIT
                    )
                    is not None
                ):
                    raise ValueError("worker exited")
                for key, _ in self.streams.select(
                    min(0.05, max(0, response_deadline - time.monotonic()))
                ):
                    if key.data == "stdin":
                        try:
                            offset += os.write(key.fd, wire[offset : offset + 65536])
                        except BlockingIOError:
                            continue
                        if offset == len(wire):
                            self.streams.unregister(self.process.stdin)
                        continue
                    chunk = os.read(key.fd, 4096)
                    if not chunk:
                        raise ValueError("worker pipe closed")
                    if key.data == "stderr":
                        self.stderr_bytes += len(chunk)
                        if self.stderr_bytes > MAX_STDERR_BYTES:
                            raise ValueError("worker diagnostic bound")
                    else:
                        self.stdout_bytes += len(chunk)
                        if self.stdout_bytes > MAX_STDOUT_BYTES:
                            raise ValueError("worker output bound")
                        self.output.extend(chunk)
                        if len(self.output) > MAX_RESPONSE_BYTES:
                            raise ValueError("worker response bound")
                if b"\n" in self.output:
                    line, rest = self.output.split(b"\n", 1)
                    if rest or offset != len(wire):
                        raise ValueError("worker response ordering")
                    self.output.clear()
                    result = json.loads(line)
                    if (
                        not isinstance(result, dict)
                        or type(result.get("ok")) is not bool
                        or result.pop("sequence", None) != self.sequence
                    ):
                        raise ValueError("worker response shape/order")
                    return result
        finally:
            try:
                self.streams.unregister(self.process.stdin)
            except KeyError:
                pass


def success(worker, **item):
    result = worker.call(item)
    if result.get("ok") is not True:
        raise ValueError("actual library operation refused")
    return result.get("value")


def refusal(worker, code="crypto", **item):
    result = worker.call(item)
    if result != {"ok": False, "code": code}:
        raise ValueError("actual library typed refusal mismatch")


def exchange(worker, suite, case, *, identity=None, key=None):
    identity = (
        copy.deepcopy(suite["identities"][case["context"]])
        if identity is None
        else identity
    )
    key = decode(suite["project_key"]) if key is None else key
    role = case["role"]
    peer = IndependentPeer(
        decode(suite["project_key"]),
        suite["identities"][case["context"]],
        "source" if role == "requester" else "requester",
    )
    handshake = success(worker, op="new", key=encode(key), identity=identity, role=role)
    return peer, handshake


def connected(worker, suite, case):
    peer, handshake = exchange(worker, suite, case)
    peer.accept(handshake)
    success(worker, op="finish", remote=peer.handshake)
    return peer


def run_case(worker, suite, case):
    mode = case["mode"]
    rid = suite["request_id"]
    text = suite["request_text"].encode()
    reply = suite["result_text"].encode()
    if mode.endswith("-interop"):
        peer = connected(worker, suite, case)
        outgoing = success(worker, op="seal", id=rid, plaintext=encode(text))
        if peer.open(rid, outgoing) != text:
            raise ValueError("independent peer plaintext mismatch")
        incoming = peer.seal(rid, reply)
        if decode(success(worker, op="open", id=rid, envelope=incoming)) != reply:
            raise ValueError("actual library plaintext mismatch")
    elif mode in {
        "bad-handshake-tag-consumes-state",
        "wrong-identity",
        "wrong-project-key",
        "wrong-role-version",
    }:
        identity = copy.deepcopy(suite["identities"][case["context"]])
        key = decode(suite["project_key"])
        if mode == "wrong-identity":
            identity["ownerId"] = "different-owner"
        if mode == "wrong-project-key":
            key = bytes([key[0] ^ 1]) + key[1:]
        peer, handshake = exchange(worker, suite, case, identity=identity, key=key)
        if mode in {"wrong-identity", "wrong-project-key"}:
            try:
                peer.accept(handshake)
            except ValueError:
                pass
            else:
                raise ValueError("independent peer accepted wrong identity/key")
        remote = copy.deepcopy(peer.handshake)
        if mode == "bad-handshake-tag-consumes-state":
            remote["authenticationTag"] = encode(
                bytes([decode(remote["authenticationTag"])[0] ^ 1])
                + decode(remote["authenticationTag"])[1:]
            )
        if mode == "wrong-role-version":
            remote["role"] = case["role"]
        refusal(worker, op="finish", remote=remote)
        refusal(worker, op="finish", remote=peer.handshake)
        if mode == "wrong-role-version":
            peer, handshake = exchange(worker, suite, case)
            remote = {**peer.handshake, "version": 2 if peer.version == 1 else 1}
            refusal(worker, op="finish", remote=remote)
    elif mode == "tamper-routing-replay":
        peer = connected(worker, suite, case)
        original = peer.seal(rid, reply)
        for mutation in ("tag", "request", "nonce", "version"):
            changed = copy.deepcopy(original)
            request = rid
            if mutation == "tag":
                payload = decode(changed["ciphertext"])
                changed["ciphertext"] = encode(bytes([payload[0] ^ 1]) + payload[1:])
            elif mutation == "request":
                request = "wrong-request"
            elif mutation == "nonce":
                changed["nonce"] += "="
            else:
                changed["version"] = 99
            refusal(worker, op="open", id=request, envelope=changed)
        reflection = success(worker, op="seal", id=rid, plaintext=encode(text))
        refusal(worker, op="open", id=rid, envelope=reflection)
        if decode(success(worker, op="open", id=rid, envelope=original)) != reply:
            raise ValueError("failed auth poisoned inbound history")
        refusal(worker, op="open", id=rid, envelope=original)
    elif mode == "json-invalid-retry-and-lossless-text":
        peer = connected(worker, suite, case)
        malformed = peer.seal(rid, b"not JSON")
        refusal(
            worker, code="protocol", op="open_json_text", id=rid, envelope=malformed
        )
        if (
            decode(success(worker, op="open", id=rid, envelope=malformed))
            != b"not JSON"
        ):
            raise ValueError("JSON failure consumed authenticated nonce")
        lossless = peer.seal(rid, b'{"n":9007199254740993,"z":[true,null]}')
        result = success(worker, op="open_json_text", id=rid, envelope=lossless)
        if json.loads(result) != json.loads('{"n":9007199254740993,"z":[true,null]}'):
            raise ValueError("Core JSON text precision changed")
        refusal(worker, op="open_json_text", id=rid, envelope=lossless)
    elif mode == "close-handles":
        peer, handshake = exchange(worker, suite, case)
        success(worker, op="close_handshake")
        success(worker, op="close_handshake")
        refusal(worker, op="handshake")
        refusal(worker, op="finish", remote=peer.handshake)
        peer = connected(worker, suite, case)
        incoming = peer.seal(rid, reply)
        success(worker, op="close_session")
        success(worker, op="close_session")
        refusal(worker, op="seal", id=rid, plaintext=encode(text))
        refusal(worker, op="open", id=rid, envelope=incoming)
        refusal(worker, op="open_json_text", id=rid, envelope=incoming)
    elif mode == "metadata-key-bounds":
        base = suite["identities"][case["context"]]
        for field, value in [
            ("ownerId", "x" * 129),
            ("ownerId", "😀" * 65),
            ("keyEpoch", 0),
            ("keyEpoch", 9007199254740992),
        ]:
            identity = {**base, field: value}
            refusal(
                worker,
                op="new",
                key=suite["project_key"],
                identity=identity,
                role=case["role"],
            )
        refusal(
            worker, op="new", key=encode(b"x" * 31), identity=base, role=case["role"]
        )
        refusal(
            worker, op="new", key=suite["project_key"], identity=base, role="invalid"
        )
    elif mode == "payload-envelope-bounds":
        peer = connected(worker, suite, case)
        maximum = b"x" * (200 * 1024)
        envelope = success(worker, op="seal", id=rid, plaintext=encode(maximum))
        if peer.open(rid, envelope) != maximum:
            raise ValueError("maximum supported plaintext altered")
        refusal(worker, op="seal", id=rid, plaintext=encode(maximum + b"x"))
        refusal(worker, op="seal", id="x" * 129, plaintext=encode(text))
        oversized = peer.seal(rid, maximum + b"x")
        refusal(worker, op="open", id=rid, envelope=oversized)
        valid = peer.seal(rid, reply)
        if decode(success(worker, op="open", id=rid, envelope=valid)) != reply:
            raise ValueError("bounds refusal poisoned session")
    elif mode == "nonce-capacity":
        peer = connected(worker, suite, case)
        for index in range(4096):
            outgoing = success(worker, op="seal", id=rid, plaintext=encode(b"x"))
            if peer.open(rid, outgoing) != b"x":
                raise ValueError("outbound history interop mismatch")
        refusal(worker, op="seal", id=rid, plaintext=encode(b"x"))
        peer = connected(worker, suite, case)
        for index in range(4096):
            if (
                decode(
                    success(worker, op="open", id=rid, envelope=peer.seal(rid, b"x"))
                )
                != b"x"
            ):
                raise ValueError("inbound history interop mismatch")
        refusal(worker, op="open", id=rid, envelope=peer.seal(rid, b"x"))
    else:
        raise ValueError("unknown shared vector")
    return {"id": case["id"], "status": "passed"}


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--fixture", type=Path, required=True)
    parser.add_argument("--capability", choices=[CAPABILITY], required=True)
    parser.add_argument("--language", choices=list(COMMANDS), required=True)
    args = parser.parse_args()
    raw = args.fixture.read_bytes()
    if len(raw) > 1024 * 1024:
        raise ValueError("bounded fixture required")
    suite = json.loads(raw)["capabilities"][CAPABILITY]
    cases = suite["vectors"]
    if len(cases) != 14 or len({item["id"] for item in cases}) != 14:
        raise ValueError("complete shared fixture required")
    previous = {
        kind: signal.getsignal(kind)
        for kind in (signal.SIGTERM, signal.SIGHUP, signal.SIGINT)
    }
    worker = None
    try:
        for kind in previous:
            signal.signal(kind, cancelled)
        worker = Worker(args.language)
        results = [run_case(worker, suite, item) for item in cases]
        success(worker, op="close_session")
        success(worker, op="close_handshake")
        worker.close()
        worker = None
        if CANCELLED:
            raise ValueError("owner cancelled")
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
    finally:
        try:
            if worker is not None:
                worker.close()
        finally:
            for kind, handler in previous.items():
                signal.signal(kind, handler)


if __name__ == "__main__":
    try:
        main()
    except Exception:
        print("Remote crypto library conformance failed", file=sys.stderr)
        raise SystemExit(1)
