#!/usr/bin/env python3
"""Cross-SDK speed check: Rust vs npm (TypeScript reference) vs Python on a real backend.

One warmed worker per SDK (Rust `examples/sdk-speed-worker.rs`, npm and Python
`runners/sdk-speed-worker.*`) runs the same API-key operations against the same
backend account. Rounds are interleaved with a rotating arm order, so each round
yields one paired sample per arm. Client CPU comes from /proc/<pid>/task/*/schedstat
(nanoseconds, all threads, startup excluded); wall time is measured around each
request by this process. Results are paired medians with a bootstrap 95% CI of
the median per-round ratio against the npm arm. The npm API-key drafts/history/
wikipedia paths are the maintained TypeScript implementation, so npm is the
TypeScript reference. Policy (.claude/rules/cli-sdk.md): advisory; only a gross
regression (median ratio > 1.25 AND median paired delta > 100 ms) or a leak blocks.

Linux only. Usage: see `--help`; `--perf-entries` writes record_perf_measurement.py input.
"""

from __future__ import annotations

import argparse
import json
import os
import random
import selectors
import statistics
import subprocess
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
HERE = Path(__file__).resolve().parent
ARMS = ("rust", "npm", "python")
REFERENCE = "npm"
GROSS_RATIO, GROSS_DELTA_MS = 1.25, 100.0
LEAK_RSS_KIB = 64 * 1024
# Ratio CI upper bound at or below which Rust is "not worse" (rust_perf_history limits).
NOT_WORSE = {"wallMs": 1.10, "cpuMs": 1.15}
MAX_LINE = 4 * 1024 * 1024


def default_plan(draft_chat_id: str | None) -> list[dict]:
    """Operations per capability. Rates stay under the backend's 60/minute route limits."""
    plan = [
        {"capability": "sdk.drafts", "op": "drafts.list", "args": {}, "per_minute": 240},
        {"capability": "sdk.wikipedia", "op": "wikipedia.search",
         "args": {"query": "Berlin", "language": "en", "limit": 5}, "per_minute": 50},
        {"capability": "sdk.wikipedia", "op": "wikipedia.summary",
         "args": {"title": "Berlin", "language": "en"}, "per_minute": 50},
    ]
    if draft_chat_id:
        plan.insert(1, {"capability": "sdk.drafts", "op": "drafts.get",
                        "args": {"chat_id": draft_chat_id}, "per_minute": 240})
    return plan


def cpu_ns(pid: int) -> int:
    total = 0
    for task in Path(f"/proc/{pid}/task").iterdir():
        try:
            total += int((task / "schedstat").read_text().split()[0])
        except (FileNotFoundError, ProcessLookupError):
            continue  # a thread exited between listing and reading
    return total


def rss_kib(pid: int) -> int:
    for row in Path(f"/proc/{pid}/status").read_text().splitlines():
        if row.startswith("VmRSS:"):
            return int(row.split()[1])
    raise RuntimeError("VmRSS unavailable")


class Worker:
    def __init__(self, name: str, argv: list[str], init: dict, env: dict):
        self.name = name
        self.child = subprocess.Popen(argv, cwd=ROOT, env=env, stdin=subprocess.PIPE, stdout=subprocess.PIPE,
                                      stderr=subprocess.PIPE, bufsize=0)
        self.pending = b""
        self.send(init)
        ready = self.read(120)
        if ready != {"ready": True}:
            raise RuntimeError(f"{name} worker did not become ready: {ready}")

    def send(self, value: dict) -> None:
        self.child.stdin.write((json.dumps(value) + "\n").encode())
        self.child.stdin.flush()

    def read(self, timeout: float) -> dict:
        deadline = time.monotonic() + timeout
        fd = self.child.stdout.fileno()
        os.set_blocking(fd, False)
        with selectors.DefaultSelector() as poll:
            poll.register(fd, selectors.EVENT_READ)
            while b"\n" not in self.pending:
                remaining = deadline - time.monotonic()
                if remaining <= 0 or not poll.select(remaining):
                    raise TimeoutError(f"{self.name} worker timed out")
                try:
                    chunk = os.read(fd, 65536)
                except BlockingIOError:
                    continue
                if not chunk:
                    stderr = self.child.stderr.read(4096).decode(errors="replace")
                    raise RuntimeError(f"{self.name} worker exited: {stderr}")
                self.pending += chunk
                if len(self.pending) > MAX_LINE:
                    raise RuntimeError(f"{self.name} worker output exceeded bound")
        line, self.pending = self.pending.split(b"\n", 1)
        return json.loads(line)

    def measure(self, op: str, args: dict, iterations: int) -> dict:
        pid = self.child.pid
        cpu0, wall0 = cpu_ns(pid), time.monotonic_ns()
        self.send({"op": op, "args": args, "iterations": iterations})
        answer = self.read(300)
        wall, cpu = time.monotonic_ns() - wall0, cpu_ns(pid) - cpu0
        return {"answer": answer, "wallMs": wall / 1e6 / iterations, "cpuMs": cpu / 1e6 / iterations}

    def close(self) -> None:
        try:
            self.child.stdin.close()
            self.child.wait(timeout=10)
        except subprocess.TimeoutExpired:
            self.child.kill()
            self.child.wait(timeout=5)


def bootstrap_median_ci(values: list[float], seed: int, rounds: int = 4000) -> list[float]:
    rng = random.Random(seed)
    medians = sorted(statistics.median(rng.choices(values, k=len(values))) for _ in range(rounds))
    return [round(medians[int(0.025 * rounds)], 4), round(medians[int(0.975 * rounds) - 1], 4)]


def compare(samples: dict[str, list[dict]], arm: str, metric: str, seed: int) -> dict:
    pairs = [(a[metric], r[metric]) for a, r in zip(samples[arm], samples[REFERENCE]) if r[metric] > 0]
    ratios = [a / r for a, r in pairs]
    deltas = [a - r for a, r in pairs]
    ratio, delta = statistics.median(ratios), statistics.median(deltas)
    ci = bootstrap_median_ci(ratios, seed)
    # Percentile bootstrap can exclude the sample median for tiny n; keep the point inside.
    ci = [min(ci[0], round(ratio, 4)), max(ci[1], round(ratio, 4))]
    gross = ratio > GROSS_RATIO and delta > GROSS_DELTA_MS
    verdict = "rust_worse" if gross else "rust_not_worse" if ci[1] <= NOT_WORSE[metric] else "inconclusive"
    return {"n_pairs": len(pairs), "ratio": round(ratio, 4), "ci95": ci, "median_delta_ms": round(delta, 3),
            "arm_median_ms": round(statistics.median(a for a, _ in pairs), 3),
            "reference_median_ms": round(statistics.median(r for _, r in pairs), 3),
            "gross_regression": gross, "verdict": verdict}


def run_op(workers: dict[str, Worker], step: dict, pairs: int, iterations: int, seed: int) -> dict:
    op, args = step["op"], step["args"]
    interval = 60.0 * iterations / step["per_minute"]
    last = 0.0

    def paced(worker: Worker, count: int) -> dict:
        nonlocal last
        wait = last + interval * count / iterations - time.monotonic()
        if wait > 0:
            time.sleep(wait)  # rate pacing stays outside the measured window
        sample = worker.measure(op, args, count)
        last = time.monotonic()
        return sample

    warm = {name: paced(worker, 1)["answer"] for name, worker in workers.items()}
    failures = [f"{name}: {answer}" for name, answer in warm.items() if not answer.get("ok")]
    digests = {name: answer.get("digest") for name, answer in warm.items()}
    result = {"capability": step["capability"], "op": op, "iterations": iterations, "digests": digests,
              "digest_equal": len({json.dumps(d, sort_keys=True) for d in digests.values()}) == 1}
    if failures:
        return {**result, "status": "failed", "failures": failures}
    rss_start = {name: rss_kib(w.child.pid) for name, w in workers.items()}
    samples: dict[str, list[dict]] = {name: [] for name in workers}
    for index in range(pairs):
        shift = index % len(ARMS)
        order = list(ARMS[shift:] + ARMS[:shift])
        if (index // len(ARMS)) % 2:
            order.reverse()  # counterbalance position within the rotation
        for name in order:
            sample = paced(workers[name], iterations)
            if not sample["answer"].get("ok"):
                return {**result, "status": "failed", "failures": [f"{name} round {index}: {sample['answer']}"]}
            if json.dumps(sample["answer"].get("digest"), sort_keys=True) != json.dumps(digests[name], sort_keys=True):
                return {**result, "status": "failed", "failures": [f"{name} round {index}: digest changed"]}
            samples[name].append({"wallMs": sample["wallMs"], "cpuMs": sample["cpuMs"]})
    rss_growth = {name: rss_kib(w.child.pid) - rss_start[name] for name, w in workers.items()}
    comparisons = {arm: {metric: compare(samples, arm, metric, seed) for metric in ("wallMs", "cpuMs")}
                   for arm in ARMS if arm != REFERENCE}
    leak = rss_growth["rust"] > LEAK_RSS_KIB
    return {**result, "status": "measured", "samples": samples, "rss_growth_kib": rss_growth,
            "rust_leak_suspected": leak, "comparisons": comparisons}


def perf_entries(report: dict, ci_job: str | None, source: str | None) -> list[dict]:
    entries = []
    for row in report["operations"]:
        if row["status"] != "measured":
            continue
        for metric, flow in (("wallMs", "sdkWall"), ("cpuMs", "sdkCpu")):
            c = row["comparisons"]["rust"][metric]
            py = row["comparisons"]["python"][metric]
            entries.append({
                "flow": flow, "metric": f"{row['capability']}:{row['op']}:{metric}", "value_kind": "ratio",
                "value": c["ratio"], "ci95": c["ci95"], "n_pairs": c["n_pairs"], "verdict": c["verdict"],
                "verdict_basis": "reported", "ci_job": ci_job, "source_commit": source,
                "ts_value": c["reference_median_ms"], "confidence": "traced" if (ci_job or source) else "uncertain",
                "evidence": (f"tests/sdk-conformance/benchmark_sdk_speed.py via sdk-speed-check.spec.ts; Rust median "
                             f"{c['arm_median_ms']} ms vs npm/TypeScript {c['reference_median_ms']} ms per op; "
                             f"paired median delta {c['median_delta_ms']} ms; bootstrap CI of median ratio"),
                "notes": (f"Real isolated backend, API-key auth, warmed workers, {row['iterations']} ops/sample. "
                          f"Python/TS ratio {py['ratio']} {py['ci95']}. Advisory 2026-11-07 policy: gross only if "
                          f">+25% and >+100 ms; gross={c['gross_regression']}, rust RSS growth "
                          f"{row['rss_growth_kib']['rust']} KiB."),
            })
    return entries


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--api-url", required=True)
    parser.add_argument("--api-key-env", default="OPENMATES_API_KEY", help="environment variable holding the key")
    parser.add_argument("--rust-worker", required=True, type=Path)
    parser.add_argument("--device-prefix", default="sdk-speed")
    parser.add_argument("--draft-chat-id")
    parser.add_argument("--pairs", type=int, default=12)
    parser.add_argument("--iterations", type=int, default=2)
    parser.add_argument("--only", action="append", help="limit to these operation names")
    parser.add_argument("--seed", type=int, default=20261108)
    parser.add_argument("--output", required=True, type=Path)
    parser.add_argument("--perf-entries", type=Path)
    parser.add_argument("--ci-job")
    parser.add_argument("--source-commit")
    args = parser.parse_args()
    if sys.platform != "linux" or not 3 <= args.pairs <= 60 or not 1 <= args.iterations <= 50:
        raise SystemExit("Linux only; 3-60 pairs; 1-50 iterations")
    key = os.environ.get(args.api_key_env, "")
    if not key.startswith("sk-api-"):
        raise SystemExit(f"{args.api_key_env} must hold an OpenMates API key")
    env = {k: v for k, v in os.environ.items() if k != args.api_key_env}
    commands = {
        "rust": [str(args.rust_worker.resolve(strict=True))],
        "npm": ["node", str(HERE / "runners/sdk-speed-worker.mjs")],
        "python": [sys.executable, str(HERE / "runners/sdk-speed-worker.py")],
    }
    plan = [s for s in default_plan(args.draft_chat_id) if not args.only or s["op"] in args.only]
    report = {"schemaVersion": 1, "status": "running", "api_url": args.api_url, "reference": REFERENCE,
              "policy": {"gross_ratio": GROSS_RATIO, "gross_delta_ms": GROSS_DELTA_MS, "leak_rss_kib": LEAK_RSS_KIB},
              "pairs": args.pairs, "operations": [], "errors": []}
    workers: dict[str, Worker] = {}
    try:
        for name in ARMS:
            init = {"api_url": args.api_url, "api_key": key, "device_id": f"{args.device_prefix}-{name}"}
            workers[name] = Worker(name, commands[name], init, env)
        for step in plan:
            row = run_op(workers, step, args.pairs, args.iterations, args.seed)
            report["operations"].append(row)
            print(json.dumps({k: row.get(k) for k in ("capability", "op", "status", "comparisons", "failures")}),
                  flush=True)
        failed = [r for r in report["operations"] if r["status"] != "measured" or not r["digest_equal"]]
        gross = [r for r in report["operations"] if r["status"] == "measured" and (r["rust_leak_suspected"] or any(
            c["gross_regression"] for c in r["comparisons"]["rust"].values()))]
        report["status"] = "failed" if failed else "gross_regression" if gross else "passed"
    except (RuntimeError, TimeoutError, OSError, ValueError) as error:
        report["status"] = "incomplete"
        report["errors"].append(str(error))
    finally:
        for worker in workers.values():
            worker.close()
        args.output.write_text(json.dumps(report, indent=2) + "\n")
        if args.perf_entries:
            args.perf_entries.write_text(json.dumps(perf_entries(report, args.ci_job, args.source_commit), indent=2) + "\n")
    return 0 if report["status"] == "passed" else 1


if __name__ == "__main__":
    raise SystemExit(main())
