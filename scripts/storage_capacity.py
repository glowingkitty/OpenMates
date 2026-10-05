"""Deterministic, zero-inference storage capacity workload and evidence checks.

This runner does not seed product rows. The client command receives a compact
plan and must exercise the isolated application with real client cryptography.
Its result file and the worker replay receipts are independently checked here.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import math
import os
from pathlib import Path
import re
import sqlite3
import subprocess
import sys
from tempfile import TemporaryDirectory
from typing import Any


DEFAULT_USERS = 1000
DEFAULT_ROUNDS = 500
DEFAULT_EMBEDS = 200
DEFAULT_VERSIONS = 1000
DEFAULT_CONCURRENCY = 500
FAILURE_PHASES = frozenset({
    "client_init", "project_create", "round_send", "embed_readback",
    "archive_readback", "version_write", "version_send",
    "version_callback_count", "version_readback",
})
FAILURE_CLASSES = frozenset({
    "Error", "TypeError", "RangeError", "SyntaxError", "ReferenceError", "AggregateError", "AbortError",
})
FAILURE_LOCATION = re.compile(r"storage_capacity_(?:client|version_adapter|page_adapter)\.mjs:(?:[1-9][0-9]{0,4}|unavailable)\Z")


def public_failure(row: dict[str, Any]) -> str:
    """Classify one private failure row without echoing reason or payload."""
    raw_phase, raw_class = row.get("phase"), row.get("error_class")
    phase = raw_phase if isinstance(raw_phase, str) and raw_phase in FAILURE_PHASES else "unknown"
    error_class = raw_class if isinstance(raw_class, str) and raw_class in FAILURE_CLASSES else "Error"
    location = row.get("source_location")
    if not isinstance(location, str) or not FAILURE_LOCATION.fullmatch(location):
        location = "unavailable"
    return f"workload failure at {phase} ({error_class}; {location})"


def payload(seed: str, user: int, kind: str, number: int, size: int) -> str:
    """Stable, poorly compressible synthetic content with no private data."""
    if size < 0:
        raise ValueError("Payload size must be nonnegative")
    label = f"{seed}:{user}:{kind}:{number}".encode()
    blocks = []
    counter = 0
    while len(blocks) * 64 < size:
        blocks.append(hashlib.sha256(label + counter.to_bytes(4, "big")).hexdigest())
        counter += 1
    return "".join(blocks)[:size]


def payload_digest(seed: str, user: int, kind: str, number: int, size: int) -> str:
    return hashlib.sha256(payload(seed, user, kind, number, size).encode()).hexdigest()


def make_plan(args: argparse.Namespace) -> dict[str, Any]:
    for name in ("users", "rounds", "embeds", "versions", "concurrency"):
        if getattr(args, name) <= 0:
            raise ValueError(f"{name} must be positive")
    if args.embeds > args.rounds:
        raise ValueError("embeds per user cannot exceed rounds per user")
    if args.concurrency > args.users:
        raise ValueError("concurrency cannot exceed users")
    if args.profile == "sustained" and args.duration_seconds <= 0:
        raise ValueError("sustained profile needs a positive duration")
    return {
        "schema": 1,
        "seed": args.seed,
        "users": args.users,
        "rounds_per_user": args.rounds,
        "embeds_per_user": args.embeds,
        "versions_per_user": args.versions,
        "peak_concurrency": args.concurrency,
        "profile": args.profile,
        "validation_level": "pilot" if getattr(args, "pilot", False) else "target",
        "duration_seconds": args.duration_seconds if args.profile == "sustained" else None,
        "payload_bytes": {"round": args.round_bytes, "embed": args.embed_bytes, "version": args.version_bytes},
        "expected": {
            "round": args.users * args.rounds,
            "embed": args.users * args.embeds,
            "version": args.users * args.versions,
        },
        "requires": ["signed-live-mock", "network-deny", "no-provider-credentials", "real-client-crypto", "isolated-storage"],
    }


def _read_jsonl(path: Path):
    with path.open(encoding="utf-8") as source:
        for line_number, line in enumerate(source, 1):
            if line.strip():
                try:
                    yield json.loads(line)
                except json.JSONDecodeError as exc:
                    raise ValueError(f"Invalid result JSON at line {line_number}") from exc


def _p95(values: list[float]) -> float | None:
    if not values:
        return None
    values.sort()
    return values[math.ceil(0.95 * len(values)) - 1]


def _receipt_paths(root: Path):
    """Stream old flat receipts and deterministic two-hex-digit receipt shards."""
    with os.scandir(root) as entries:
        for entry in entries:
            if entry.is_file(follow_symlinks=False) and entry.name.endswith(".json"):
                yield Path(entry.path)
            elif entry.is_dir(follow_symlinks=False):
                if len(entry.name) != 2 or any(char not in "0123456789abcdef" for char in entry.name):
                    raise ValueError("Unexpected capacity receipt directory")
                with os.scandir(entry.path) as shard:
                    for receipt in shard:
                        if receipt.is_file(follow_symlinks=False) and receipt.name.endswith(".json"):
                            yield Path(receipt.path)


def verify(plan: dict[str, Any], results_path: Path, receipts_dir: Path) -> dict[str, Any]:
    """Require exact operations and independently generated content digests."""
    expected = plan["expected"]
    seen: set[tuple[str, int, int]] = set()
    counts = {kind: 0 for kind in expected}
    child_completions = 0
    failures: list[str] = []
    uncached_ms: list[float] = []
    warm_ms: list[float] = []
    observed_archive_page_ids: set[str] = set()
    observed_max_concurrency = 0
    elapsed_seconds: float | None = None
    hardware: dict[str, Any] | None = None
    for row in _read_jsonl(results_path):
        kind = row.get("kind")
        if kind == "meta":
            observed_max_concurrency = max(observed_max_concurrency, int(row.get("max_concurrency", 0)))
            duration_ms = row.get("duration_ms")
            if isinstance(duration_ms, (int, float)) and duration_ms > 0:
                elapsed_seconds = float(duration_ms) / 1000
            hardware = row.get("hardware") if isinstance(row.get("hardware"), dict) else None
            continue
        if kind == "archive_page":
            page_ids = row.get("archive_page_ids")
            if (not isinstance(page_ids, list) or not page_ids
                    or any(not isinstance(page_id, str) or not page_id for page_id in page_ids)):
                failures.append("archive page lacks stable page identity")
                continue
            if any(page_id in observed_archive_page_ids for page_id in page_ids):
                failures.append("archive page identity was read previously")
                continue
            observed_archive_page_ids.update(page_ids)
            latency = row.get("ready_ms")
            if not isinstance(latency, (int, float)) or latency < 0:
                failures.append("archive page has no client-ready latency")
            elif row.get("cache") == "cold" and row.get("decrypted") is True and row.get("authorized") is True:
                uncached_ms.append(float(latency))
            elif row.get("cache") == "warm":
                warm_ms.append(float(latency))
            else:
                failures.append("archive page lacks cold authorization/decryption evidence")
            continue
        if kind == "failure":
            failures.append(public_failure(row))
            continue
        if kind not in expected:
            failures.append("unknown result kind")
            continue
        user, number = row.get("user"), row.get("number")
        if type(user) is not int or type(number) is not int or not 0 <= user < plan["users"] or not 0 <= number < expected[kind] // plan["users"]:
            failures.append(f"invalid {kind} operation index")
            continue
        key = (kind, user, number)
        if key in seen:
            failures.append(f"duplicate {kind} operation")
            continue
        seen.add(key)
        if row.get("status") != "persisted" or row.get("client_crypto") is not True:
            failures.append(f"{kind} did not prove encrypted application persistence")
            continue
        size = plan["payload_bytes"][kind]
        expected_digest = payload_digest(plan["seed"], user, kind, number, size)
        if row.get("content_sha256") != expected_digest:
            failures.append(f"{kind} content ledger mismatch")
            continue
        if kind == "version" and row.get("reconstructed_sha256") != expected_digest:
            failures.append("version reconstruction mismatch")
            continue
        if kind == "round":
            child_expected = number % 50 == 10
            if row.get("child_completed") is not child_expected:
                failures.append("child dispatch/completion ledger mismatch")
                continue
            child_completions += int(child_expected)
        counts[kind] += 1

    aggregate = {"cache_hits": 0, "cache_misses": 0, "blocked_provider_calls": 0, "real_provider_calls": 0}
    receipt_count = 0
    server_active = 0
    server_task_peak = 0
    # External sorting keeps millions of processing intervals off the Python heap.
    with TemporaryDirectory(prefix="capacity-edges-", dir=receipts_dir.parent) as scratch:
        with sqlite3.connect(str(Path(scratch) / "events.sqlite3")) as edges:
            edges.execute("CREATE TABLE edges (moment INTEGER NOT NULL, delta INTEGER NOT NULL)")
            pending_edges = []
            for path in _receipt_paths(receipts_dir):
                receipt_count += 1
                receipt = json.loads(path.read_text(encoding="utf-8"))
                if receipt.get("mode") != "mock":
                    failures.append("non-replay receipt")
                for name in aggregate:
                    aggregate[name] += int(receipt.get(name, 0))
                started, finished = receipt.get("started_at_monotonic_ns"), receipt.get("finished_at_monotonic_ns")
                if type(started) is not int or type(finished) is not int or started <= 0 or finished <= started:
                    failures.append("worker receipt lacks valid processing interval")
                else:
                    pending_edges.extend(((started, 1), (finished, -1)))
                    if len(pending_edges) >= 10000:
                        edges.executemany("INSERT INTO edges VALUES (?, ?)", pending_edges)
                        pending_edges.clear()
            if pending_edges:
                edges.executemany("INSERT INTO edges VALUES (?, ?)", pending_edges)
            edges.execute("CREATE INDEX edges_order ON edges (moment, delta)")
            for (delta,) in edges.execute("SELECT delta FROM edges ORDER BY moment, delta"):
                server_active += delta
                server_task_peak = max(server_task_peak, server_active)
    if not receipt_count:
        failures.append("no replay receipts")
    elif receipt_count < counts["round"] + counts["version"] + child_completions:
        failures.append("fewer replay task receipts than completed main, Project and child turns")
    if server_active != 0:
        failures.append("worker processing intervals did not balance")
    if aggregate["real_provider_calls"] != 0:
        failures.append("real provider calls observed")
    if aggregate["cache_misses"] or aggregate["blocked_provider_calls"]:
        failures.append("missing fixture or blocked provider attempt")
    if aggregate["cache_hits"] == 0:
        failures.append("no full-path provider replay observed")
    for kind, target in expected.items():
        if counts[kind] != target:
            failures.append(f"{kind} count {counts[kind]} of {target}")
    expected_children = plan["users"] * len(range(10, plan["rounds_per_user"], 50))
    if child_completions != expected_children:
        failures.append(f"child completions {child_completions} of {expected_children}")
    if observed_max_concurrency < plan["peak_concurrency"]:
        failures.append("peak client in-flight load not reached")
    if server_task_peak < plan["peak_concurrency"]:
        failures.append("peak server task concurrency not reached")
    if elapsed_seconds is None or hardware is None:
        failures.append("duration or reference hardware evidence missing")
    if (plan["profile"] == "sustained" and elapsed_seconds is not None
            and not 0.95 * plan["duration_seconds"] <= elapsed_seconds <= 1.05 * plan["duration_seconds"]):
        failures.append("paced traffic duration was outside declared window")
    cold_p95 = _p95(uncached_ms)
    requires_cold_page = plan.get("validation_level") != "pilot" or plan["rounds_per_user"] >= 30
    if (requires_cold_page and not uncached_ms) or (cold_p95 is not None and cold_p95 > 1000):
        failures.append("uncached archive page p95 gate not met")
    return {
        "passed": not failures,
        "failures": failures[:30],
        "counts": counts,
        "child_completions": child_completions,
        "expected_child_completions": expected_children,
        "target": expected,
        "observed_max_concurrency": observed_max_concurrency,
        "observed_max_client_inflight": observed_max_concurrency,
        "server_task_peak_concurrency": server_task_peak,
        "task_receipt_count": receipt_count,
        "uncached_page_samples": len(uncached_ms),
        "unique_archive_pages": len(observed_archive_page_ids),
        "uncached_page_p95_ms": cold_p95,
        "warm_page_samples": len(warm_ms),
        "warm_page_p95_ms": _p95(warm_ms),
        "provider": aggregate,
        "profile": plan["profile"],
        "validation_level": plan.get("validation_level", "target"),
        "workload_target_met": not failures and plan.get("validation_level") != "pilot" and plan["expected"] == {
            "round": 500000, "embed": 200000, "version": 1000000,
        } and plan["peak_concurrency"] >= 500,
        "target_achieved": False,
        "duration_seconds": plan["duration_seconds"],
        "traffic_evidence": ("paced representative" if plan["profile"] == "sustained"
                             and plan.get("validation_level") == "pilot"
                             else "paced target volume" if plan["profile"] == "sustained"
                             else "accelerated target volume" if plan.get("validation_level") != "pilot"
                             else "accelerated pilot"),
        "measured_duration_seconds": elapsed_seconds,
        "rounds_per_second": counts["round"] / elapsed_seconds if elapsed_seconds else None,
        "versions_per_second": counts["version"] / elapsed_seconds if elapsed_seconds else None,
        "hardware": hardware,
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("command", choices=("plan", "run", "verify"))
    parser.add_argument("--plan", type=Path, required=True)
    parser.add_argument("--results", type=Path)
    parser.add_argument("--receipts", type=Path)
    parser.add_argument("--client-command", nargs="+")
    parser.add_argument("--seed", default="storage-capacity-v1")
    parser.add_argument("--users", type=int, default=DEFAULT_USERS)
    parser.add_argument("--rounds", type=int, default=DEFAULT_ROUNDS)
    parser.add_argument("--embeds", type=int, default=DEFAULT_EMBEDS)
    parser.add_argument("--versions", type=int, default=DEFAULT_VERSIONS)
    parser.add_argument("--concurrency", type=int, default=DEFAULT_CONCURRENCY)
    parser.add_argument("--profile", choices=("accelerated", "sustained", "burst"), default="accelerated")
    parser.add_argument("--pilot", action="store_true", help="Keep a passing small pilot distinct from target acceptance")
    parser.add_argument("--duration-seconds", type=int, default=86400)
    parser.add_argument("--round-bytes", type=int, default=2048)
    parser.add_argument("--embed-bytes", type=int, default=8192)
    parser.add_argument("--version-bytes", type=int, default=4096)
    args = parser.parse_args()
    if args.command == "plan":
        plan = make_plan(args)
        args.plan.write_text(json.dumps(plan, sort_keys=True, indent=2) + "\n", encoding="utf-8")
        print(json.dumps({"plan": str(args.plan), "expected": plan["expected"]}, sort_keys=True))
        return 0
    plan = json.loads(args.plan.read_text(encoding="utf-8"))
    if args.command == "run":
        if not args.client_command or not args.results:
            parser.error("run requires --client-command and --results")
        if os.getenv("OPENMATES_CAPACITY_NETWORK_DENY") != "confirmed" or os.getenv("OPENMATES_CAPACITY_NO_PROVIDER_CREDENTIALS") != "confirmed":
            raise RuntimeError("Isolated network-deny and credential-absence attestations are required")
        client_result = subprocess.run([*args.client_command, str(args.plan), str(args.results)], check=False)
        if not args.results.is_file():
            raise RuntimeError("Capacity client exited without an operation ledger")
    if not args.results or not args.receipts:
        parser.error("verification requires --results and --receipts")
    report = verify(plan, args.results, args.receipts)
    if args.command == "run" and client_result.returncode:
        report["passed"] = False
        report["workload_target_met"] = False
        report["target_achieved"] = False
        report["failures"].append("client workload exited before successful completion")
    print(json.dumps(report, sort_keys=True))
    return 0 if report["passed"] else 1


if __name__ == "__main__":
    sys.exit(main())
