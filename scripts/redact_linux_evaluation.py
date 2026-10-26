#!/usr/bin/env python3
"""Engineering-only supervisor for the synthetic Redact Linux evaluation.

No model load/inference occurs without --run and the parent's explicit web gate.
Pin-verified asset download is optional and uses only the public Hugging Face repo.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
from pathlib import Path
import signal
import subprocess
import time
import urllib.request

ROOT = Path(__file__).resolve().parents[1]
REVISION = "3ed5033aeb544f454ebde77dc76fd7b7e76cc572"
ASSETS = {
    "redact.tflite": (24529472, "ee36727f07e3237569e71427bfe661463a82e526f7e97e92b0fa583cad16ed27"),
    "redact_tokenizer.bin": (391416, "81bc354dc99285e05b8f70edca9df3afbd83dfa4b0cea18d0448ab17ce58aae2"),
    "labels.json": (3842, "fe76679736d86b47a45fe03a94994aa292fc6203"),
}


def verify_asset(name, data):
    size, expected = ASSETS[name]
    digest = (hashlib.sha1(f"blob {len(data)}\0".encode() + data).hexdigest()
              if name == "labels.json" else hashlib.sha256(data).hexdigest())
    if len(data) != size or digest != expected:
        raise ValueError(f"Pinned asset integrity failed: {name}")


def prepare_assets(directory):
    """No install, mutable revision, secret or user content is sent."""
    directory.mkdir(parents=True, exist_ok=True)
    for name, (size, _) in ASSETS.items():
        destination = directory / name
        if destination.exists():
            verify_asset(name, destination.read_bytes())
            continue
        request = urllib.request.Request(
            f"https://huggingface.co/desert-ant-labs/redact/resolve/{REVISION}/{name}",
            headers={"User-Agent": "OpenMates-Redact-Synthetic-Evaluation/1.0"})
        with urllib.request.urlopen(request, timeout=60) as response:
            data = response.read(size + 1)
        verify_asset(name, data)
        temporary = destination.with_suffix(destination.suffix + ".partial")
        temporary.write_bytes(data)
        temporary.replace(destination)


def rss_bytes(pid):
    try:
        for line in Path(f"/proc/{pid}/status").read_text().splitlines():
            if line.startswith("VmRSS:"):
                return int(line.split()[1]) * 1024
    except FileNotFoundError:
        pass
    return 0


def supervise(command, cpus, max_rss_mib, timeout_seconds, env):
    """Bound the whole child process, including its existing/future native threads."""
    if not 1 <= len(cpus) <= 2:
        raise ValueError("Evaluation requires one or two CPUs")

    def bounds():
        os.nice(10)
        os.sched_setaffinity(0, cpus)

    started = time.monotonic()
    peak = 0
    stopped = None
    # Native/SDK output is discarded: synthetic inputs/predictions are retained
    # only in structured split-string evidence, never raw terminal logs.
    child = subprocess.Popen(command, cwd=ROOT, env=env, preexec_fn=bounds,
                             start_new_session=True, stdout=subprocess.DEVNULL,
                             stderr=subprocess.DEVNULL)
    while child.poll() is None:
        peak = max(peak, rss_bytes(child.pid))
        if peak > max_rss_mib * 1024**2:
            stopped = "rss-limit"
        if time.monotonic() - started > timeout_seconds:
            stopped = "wall-time-limit"
        if stopped:
            os.killpg(child.pid, signal.SIGKILL)
            break
        time.sleep(0.1)
    return {"returncode": child.wait(), "stopped_by_supervisor": stopped,
            "wall_seconds": time.monotonic() - started,
            "sampled_peak_rss_bytes": peak, "rss_sample_interval_seconds": 0.1,
            "rss_limit_mib": max_rss_mib, "wall_limit_seconds": timeout_seconds,
            "affinity_cpus": cpus, "niceness_increment": 10}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--directory", required=True, type=Path)
    parser.add_argument("--output", required=True, type=Path)
    parser.add_argument("--run", action="store_true")
    parser.add_argument("--download", action="store_true")
    parser.add_argument("--cores", type=int, choices=[1, 2], default=2)
    parser.add_argument("--cpu-offset", type=int, default=0)
    parser.add_argument("--repeats", type=int, choices=range(3, 16), default=7)
    parser.add_argument("--latency-only", action="store_true")
    parser.add_argument("--latency-units", type=int, nargs="+", choices=[32, 256, 1024, 4096], default=[32, 256, 1024, 4096])
    parser.add_argument("--max-rss-mib", type=int, default=1536)
    parser.add_argument("--timeout-seconds", type=int, default=300)
    args = parser.parse_args()
    # Gate even asset acquisition: this dependency must precede the native trial.
    if (args.run or args.download) and os.environ.get("OPENMATES_REDACT_EVALUATION_GO") != "web-trial-passed":
        parser.error("Parent confirmation of successful web trial is required before download or inference")
    if not 128 <= args.max_rss_mib <= 3072 or not 1 <= args.timeout_seconds <= 600 or args.cpu_offset < 0:
        parser.error("Resource limits outside bounded evaluation range")
    if args.output.exists() or args.output.with_suffix(".supervisor.json").exists():
        parser.error("Choose a fresh evidence output path; preserve previous attempts")
    available = sorted(os.sched_getaffinity(0))
    cpus = available[args.cpu_offset:args.cpu_offset + args.cores]
    if len(cpus) != args.cores:
        parser.error("Not enough available CPUs at requested offset")
    if args.download:
        prepare_assets(args.directory)
    command = ["node", "--max-old-space-size=256", "--experimental-strip-types", "--loader",
               str(ROOT / "frontend/packages/openmates-cli/tests/loader.mjs"),
               str(ROOT / "scripts/redact_linux_evaluation.mjs"),
               "--run" if args.run else "--inspect", str(args.directory.resolve()),
               str(args.output.resolve()), str(args.repeats),
               "latency-only" if args.latency_only else "all", ",".join(map(str, args.latency_units))]
    env = {**os.environ, "OMP_NUM_THREADS": str(args.cores), "OPENBLAS_NUM_THREADS": str(args.cores),
           "UV_THREADPOOL_SIZE": str(args.cores)}
    # Required SDK telemetry is untouched, including endpoint and license state.
    if "DAL_LICENSE_ENDPOINT" in env or env.get("DAL_HTTP_DEBUG"):
        parser.error("Use normal SDK license endpoint without raw HTTP debug logging")
    result = supervise(command, cpus, args.max_rss_mib, args.timeout_seconds, env)
    receipt = {"status": "complete" if result["returncode"] == 0 else "failed",
               "result_file": args.output.name, "supervisor": result,
               "stdout_stderr": "discarded to prevent raw fixture/prediction logs"}
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.with_suffix(".supervisor.json").write_text(json.dumps(receipt, indent=2) + "\n")
    print(json.dumps({"status": receipt["status"], "evidence": str(args.output),
                      "supervisor_stop": result["stopped_by_supervisor"]}))
    raise SystemExit(0 if result["returncode"] == 0 else 1)


if __name__ == "__main__":
    main()
