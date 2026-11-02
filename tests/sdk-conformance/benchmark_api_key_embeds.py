#!/usr/bin/env python3
"""Matched warmed-process direct SDK CPU + complete-operation latency benchmark.

Linux only. CPU comes from /proc/<pid>/stat while initialized child workers stay
alive, excluding module/runtime startup. Each timed iteration creates a fresh
explicit SDK client, so account key/session/cache conditions match. No product IO.
"""

# contract-test-file: tooling
import argparse
from copy import deepcopy
import json
import os
from pathlib import Path
import selectors
import signal
import statistics
import subprocess
import sys
import threading
import time
from api_key_embeds_peer import EmbedsPeer
from api_key_embeds_family_peer import EmbedsFamilyPeer

ROOT = Path(__file__).resolve().parents[2]
HERE = Path(__file__).resolve().parent


def cpu_ns(pid):
    # comm is parenthesized and may contain spaces; fields 14+15 are CPU ticks.
    fields = Path(f"/proc/{pid}/stat").read_text().rsplit(")", 1)[1].split()
    return (
        (int(fields[11]) + int(fields[12])) * 1_000_000_000 // os.sysconf("SC_CLK_TCK")
    )


MAX_WORKER_LINE = 2 * 1024 * 1024


def line(child, timeout=300):
    # One absolute deadline covers every byte, including a partial JSON line.
    # Never call buffered readline() after readiness: one byte need not include a
    # newline and a stalled worker must remain bounded.
    deadline = time.monotonic() + timeout
    pending = getattr(child, "_sdk_pending_stdout", b"")
    fd = child.stdout.fileno()
    os.set_blocking(fd, False)
    with selectors.DefaultSelector() as poll:
        poll.register(fd, selectors.EVENT_READ)
        while True:
            newline = pending.find(b"\n")
            if newline >= 0:
                assert 0 < newline <= MAX_WORKER_LINE, "bounded worker output"
                child._sdk_pending_stdout = pending[newline + 1 :]
                return json.loads(pending[:newline])
            assert len(pending) <= MAX_WORKER_LINE, "bounded worker output"
            remaining = deadline - time.monotonic()
            assert remaining > 0 and poll.select(remaining), (
                "bounded benchmark worker deadline"
            )
            try:
                chunk = os.read(fd, min(65536, MAX_WORKER_LINE + 1 - len(pending)))
            except BlockingIOError:
                continue
            assert chunk, "worker closed before complete JSON line"
            pending += chunk


class RepeatedPeer:
    def __init__(self, suite, vector, language, family):
        self.factory = EmbedsFamilyPeer if family else EmbedsPeer
        self.suite, self.vector, self.language = suite, vector, language
        self.peer = self.factory(suite, vector, language)
        self.total = 0
        self.failure = None
        self.width = len(self.peer.sequence()) if family else 1

    def dispatch(self, *args):
        if self.width and self.peer.requests == self.width:
            assert self.peer.failure is None, self.peer.failure
            self.peer = self.factory(self.suite, self.vector, self.language)
        self.total += 1
        result = self.peer.dispatch(*args)
        self.failure = self.peer.failure
        return result

    server = EmbedsPeer.server

    def check(self, observed, iterations, family):
        assert self.failure is None, self.failure
        assert self.total == self.width * iterations, (
            "complete workload/no skipped operations"
        )
        assert observed["done"] is True and observed["iterations"] == iterations
        expected_count = iterations if self.vector["operation"] == "share" else 1
        assert len(observed["results"]) == expected_count
        for result in observed["results"]:
            if family:
                self.peer.check(result)
            elif self.vector["expected_error"]:
                assert (
                    result["ok"] is False
                    and result["error"] == self.vector["expected_error"]
                )
            else:
                assert result == {"ok": True, "value": self.vector["response"]}


def run(argv, suite, vector, language, family, iterations):
    peer = RepeatedPeer(suite, vector, language, family)
    server = peer.server()
    thread = threading.Thread(
        target=server.serve_forever, kwargs={"poll_interval": 0.01}, daemon=True
    )
    thread.start()
    case = {
        "endpoint": f"http://127.0.0.1:{server.server_address[1]}",
        "api_key": suite["api_keys"][vector["owner"]],
        "device_id": suite["device_id"],
        "vector": vector,
    }
    child = subprocess.Popen(
        argv,
        cwd=ROOT,
        stdin=subprocess.PIPE,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        bufsize=0,
        start_new_session=True,
    )
    try:
        child.stdin.write(
            (json.dumps({"case": case, "iterations": iterations}) + "\n").encode()
        )
        child.stdin.flush()
        assert line(child) == {"ready": True}
        cpu_start = cpu_ns(child.pid)
        wall_start = time.monotonic_ns()
        child.stdin.write(b"start\n")
        child.stdin.flush()
        observed = line(child)
        wall = time.monotonic_ns() - wall_start
        cpu = cpu_ns(child.pid) - cpu_start
        peer.check(observed, iterations, family)
        child.stdin.write(b"release\n")
        child.stdin.flush()
        assert child.wait(timeout=5) == 0, "direct worker failure"
        return {
            "cpu_ns": cpu,
            "end_to_end_ns": wall,
            "iterations": iterations,
            "requests": peer.total,
            "cpu_resolution_ns": 1_000_000_000 // os.sysconf("SC_CLK_TCK"),
            "output_complete": True,
        }
    finally:
        if child.poll() is None:
            os.killpg(child.pid, signal.SIGKILL)
            child.wait(timeout=2)
        server.shutdown()
        server.server_close()
        thread.join(2)
        assert not thread.is_alive()


def workloads():
    read = json.loads((HERE / "fixtures/sdk-api-key-embeds.json").read_text())[
        "capabilities"
    ]["sdk.embeds"]
    for size in (1024, 65536, 1048576):
        for op in ("show", "versions", "version"):
            v = deepcopy(read["vectors"][0])
            v.update(id=f"{op}-{size}-ciphertext-bytes", operation=op)
            data = {
                "encrypted_content": "x" * size,
                "unknown": {"preserve": [None, True, 7]},
                "key_epoch": 7,
            }
            v["response"] = (
                {"versions": [data]}
                if op == "versions"
                else {
                    "embed": data,
                    "embed_keys": read["vectors"][0]["response"]["embed_keys"],
                }
            )
            v["expected"] = v["response"]
            yield read, v, False
    family = json.loads((HERE / "fixtures/sdk-api-key-embeds-family.json").read_text())[
        "capabilities"
    ]["sdk.embeds.family"]
    for v in family["vectors"]:
        yield family, v, True


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--rust-executable", required=True, type=Path)
    parser.add_argument("--iterations", type=int, default=100)
    parser.add_argument("--rounds", type=int, default=3)
    parser.add_argument("--output", required=True, type=Path)
    parser.add_argument("--iteration-overrides", type=Path)
    args = parser.parse_args()
    assert (
        sys.platform == "linux"
        and 100 <= args.iterations <= 1000000
        and 1 <= args.rounds <= 10
    )
    binary = args.rust_executable.resolve(strict=True)
    assert binary.is_file()
    overrides = (
        json.loads(args.iteration_overrides.read_text())
        if args.iteration_overrides
        else {}
    )
    assert isinstance(overrides, dict) and all(
        isinstance(v, int) and 100 <= v <= 1000000 for v in overrides.values()
    )
    commands = {
        "rust": [str(binary)],
        "npm": [
            "node",
            "--experimental-strip-types",
            str(HERE / "runners/sdk-api-key-embeds-benchmark.mjs"),
        ],
    }
    report = {
        "status": "running",
        "scope": "actual direct SDK fresh client/cache per call, warmed runtime/module, complete outputs",
        "network": "synthetic loopback only",
        "cpu": "whole process ticks excluding startup; server CPU excluded",
        "measurements": [],
        "failures": [],
    }
    try:
        for suite, vector, family in workloads():
            samples = {"rust": [], "npm": []}
            for round in range(args.rounds):
                # Alternate ordering so a fixed first/second process gets no advantage.
                for language in ("rust", "npm") if round % 2 == 0 else ("npm", "rust"):
                    sample = run(
                        commands[language],
                        suite,
                        vector,
                        language,
                        family,
                        overrides.get(vector["id"], args.iterations),
                    )
                    samples[language].append(sample)
                    report["measurements"].append(
                        {
                            "id": vector["id"],
                            "round": round,
                            "language": language,
                            **sample,
                        }
                    )
            cpu = {
                k: statistics.median(s["cpu_ns"] for s in v) for k, v in samples.items()
            }
            wall = {
                k: statistics.median(s["end_to_end_ns"] for s in v)
                for k, v in samples.items()
            }
            resolution = samples["rust"][0]["cpu_resolution_ns"]
            if min(cpu.values()) < 10 * resolution:
                report["failures"].append(
                    {
                        "id": vector["id"],
                        "reason": "insufficient CPU resolution; increase iterations, no performance pass",
                    }
                )
            elif cpu["rust"] > cpu["npm"] or wall["rust"] > wall["npm"]:
                report["failures"].append(
                    {
                        "id": vector["id"],
                        "reason": "Rust slower than TypeScript baseline",
                        "median_cpu_ns": cpu,
                        "median_end_to_end_ns": wall,
                    }
                )
        report["status"] = "failed" if report["failures"] else "passed"
    except Exception as error:
        report["status"] = "incomplete"
        report["failures"].append({"reason": str(error)})
    finally:
        args.output.write_text(json.dumps(report, indent=2) + "\n")
    return 0 if report["status"] == "passed" else 1


if __name__ == "__main__":
    raise SystemExit(main())
