#!/usr/bin/env python3
"""Run Rust crate checks in GitHub Actions and make their failures readable.

Used by .github/workflows/rust.yml (per-crate fmt/clippy/test/build steps) and by
.github/workflows/isolated-tests.yml (failure explanation for Rust lanes).

  run      Execute one command, stream its output to the log, keep a bounded
           copy, record a result row and, on failure, print a collapsed
           failure excerpt plus an ::error:: (blocking) or ::warning::
           (report-only) annotation. Exits with the command's code only when
           the check is blocking.
  summary  Render all recorded rows as a Markdown table with failure excerpts
           into $GITHUB_STEP_SUMMARY. Exits 1 when a blocking check failed.
  explain  Print the failing stage/code of isolated Rust lane receipts and the
           bounded cargo tails they retained, to the log and step summary.
"""

from __future__ import annotations

import argparse
import json
import os
import re
import subprocess
import sys
import time
from collections import deque
from pathlib import Path

ANSI = re.compile(r"\x1b\[[0-9;?]*[ -/]*[@-~]")
# Lines that carry the actual reason a cargo/rustc/test/fmt step failed.
SIGNAL = re.compile(
    r"^(error(\[E\d+\])?:|warning: unused|Diff in |test .+ \.\.\. FAILED$|"
    r"---- .+ stdout ----$|thread '.+' panicked at|test result: FAILED|"
    r"failures:$|\s+--> |error: (could not compile|test failed|failed to))"
)
CONTEXT_AFTER = 4
EXCERPT_LINES = 80
TAIL_LINES = 60
LOG_LIMIT = 8 * 1024**2
# Scalar receipt fields that classify a failure without exposing private data.
RECEIPT_FIELDS = (
    "suite",
    "status",
    "stage",
    "phase",
    "code",
    "failed_stage",
    "failure_code",
    "exit_code",
    "reason",
    "category",
    "error",
)
RECEIPTS = (
    "test-results/ci-results.json",
    "test-results/ci-sdk-conformance.json",
    "test-results/ci-sdk-lockfiles.json",
    "test-results/ci-rust-wasm.json",
    "test-results/ci-native-dev.json",
    "test-results/ci-native-release-build.json",
)
CARGO_TAILS = (
    "test-results/ci-rust-wasm-private/cargo-tail.log",
    "test-results/native-release-build/release/process.log",
    "test-results/native-release-build/fetch/process.log",
)


def results_dir() -> Path:
    default = Path(os.environ.get("RUNNER_TEMP", "/tmp")) / "rust-ci"
    return Path(os.environ.get("RUST_CI_RESULTS", default))


def slug(name: str) -> str:
    return re.sub(r"[^A-Za-z0-9]+", "-", name).strip("-").lower() or "check"


def excerpt(lines: list[str]) -> list[str]:
    """Return the failure-relevant lines, or the tail when nothing matched."""
    picked: list[str] = []
    remaining = 0
    for line in lines:
        if SIGNAL.search(line):
            picked.append(line)
            remaining = CONTEXT_AFTER
        elif remaining:
            picked.append(line)
            remaining -= 1
        if len(picked) >= EXCERPT_LINES:
            picked.append("... (excerpt truncated; full output is in the step log)")
            break
    return picked or lines[-TAIL_LINES:]


def annotation(kind: str, title: str, message: str) -> str:
    def escape(value: str) -> str:
        return value.replace("%", "%25").replace("\r", "%0D").replace("\n", "%0A")

    return f"::{kind} title={escape(title).replace(',', '%2C').replace(':', '%3A')}::{escape(message)}"


def run(name: str, command: list[str], *, blocking: bool, cwd: str | None) -> int:
    if not command:
        raise SystemExit("run: command required after --")
    out = results_dir()
    out.mkdir(parents=True, exist_ok=True)
    log_path = out / f"{slug(name)}.log"
    started = time.monotonic()
    tail: deque[str] = deque(maxlen=20000)
    written = 0
    print(f"$ {' '.join(command)}", flush=True)
    try:
        process = subprocess.Popen(
            command,
            cwd=cwd,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            text=True,
            errors="replace",
        )
    except OSError as error:
        code, lines = 127, [f"failed to start: {error}"]
        print(lines[0], flush=True)
    else:
        assert process.stdout is not None
        with log_path.open("w") as log:
            for raw in process.stdout:
                sys.stdout.write(raw)
                line = ANSI.sub("", raw.rstrip("\n"))
                tail.append(line)
                if written < LOG_LIMIT:
                    log.write(line + "\n")
                    written += len(line) + 1
        code = process.wait()
        lines = list(tail)
    seconds = round(time.monotonic() - started, 1)
    failed = code != 0
    picked = excerpt(lines) if failed else []
    row = {
        "name": name,
        "command": command,
        "blocking": blocking,
        "exit_code": code,
        "seconds": seconds,
        "diagnostics": sum(
            1 for line in lines if re.match(r"^(warning|error)(\[\w+\])?: ", line)
        ),
        "excerpt": picked,
    }
    (out / f"{time.time_ns()}-{slug(name)}.json").write_text(json.dumps(row))
    if failed:
        print(f"::group::Failure excerpt: {name}")
        print("\n".join(picked))
        print("::endgroup::")
        first = next((line for line in picked if line.strip()), f"exit code {code}")
        kind = "error" if blocking else "warning"
        suffix = "" if blocking else " (report-only)"
        print(annotation(kind, f"{name} failed{suffix}", first), flush=True)
    return code if blocking else 0


def load_rows() -> list[dict]:
    directory = results_dir()
    if not directory.is_dir():
        return []
    return [json.loads(path.read_text()) for path in sorted(directory.glob("*.json"))]


def summary() -> int:
    rows = load_rows()
    table = ["## Rust crate checks", "", "| Check | Mode | Result | Duration |", "|---|---|---|---|"]
    details = []
    blocking_failures = 0
    for row in rows:
        failed = row["exit_code"] != 0
        mode = "blocking" if row["blocking"] else "report-only"
        if failed and row["blocking"]:
            blocking_failures += 1
            result = f"FAILED ({row['exit_code']})"
        elif failed:
            result = f"failing ({row['diagnostics']} diagnostics)"
        else:
            result = "passed"
        minutes = row["seconds"] / 60
        table.append(f"| `{row['name']}` | {mode} | {result} | {minutes:.1f} min |")
        if failed:
            body = "\n".join(row["excerpt"]).replace("```", "'''")
            details.append(
                f"<details><summary>{row['name']}</summary>\n\n```text\n{body}\n```\n</details>"
            )
    if not rows:
        table.append("| (no checks recorded) | | | |")
    text = "\n".join(table + [""] + details) + "\n"
    print(text)
    target = os.environ.get("GITHUB_STEP_SUMMARY")
    if target:
        with open(target, "a") as stream:
            stream.write(text)
    if blocking_failures:
        print(annotation("error", "Rust checks", f"{blocking_failures} blocking check(s) failed"))
    return 1 if blocking_failures or not rows else 0


def receipt_rows(value, depth=0):
    """Yield whitelisted scalar classification fields from nested receipts."""
    if depth > 3:
        return
    if isinstance(value, dict):
        picked = {
            key: str(value[key])[:300]
            for key in RECEIPT_FIELDS
            if key in value and (value[key] is None or isinstance(value[key], (str, int, float, bool)))
        }
        quiet = (None, "None", "passed", "0", "")
        if any(picked.get(key) not in quiet for key in ("status", "exit_code", "error")):
            yield picked
        for child in value.values():
            if isinstance(child, (dict, list)):
                yield from receipt_rows(child, depth + 1)
    elif isinstance(value, list):
        for child in value[:50]:
            yield from receipt_rows(child, depth + 1)


def explain(root: Path) -> int:
    sections = ["## Rust lane failure explanation", ""]
    for name in RECEIPTS:
        path = root / name
        if not path.is_file() or path.stat().st_size > LOG_LIMIT:
            continue
        try:
            document = json.loads(path.read_text())
        except (OSError, ValueError) as error:
            sections.append(f"- `{name}`: unreadable ({type(error).__name__})")
            continue
        for row in list(receipt_rows(document))[:20]:
            sections.append(f"- `{name}`: " + ", ".join(f"{k}={v}" for k, v in row.items()))
    for name in CARGO_TAILS:
        path = root / name
        if path.is_file():
            lines = ANSI.sub("", path.read_text(errors="replace")).splitlines()
            body = "\n".join(excerpt(lines)).replace("```", "'''")
            sections.append(f"\n<details><summary>{name}</summary>\n\n```text\n{body}\n```\n</details>")
    if len(sections) == 2:
        sections.append("No Rust lane receipt or cargo output was written before the failure.")
    text = "\n".join(sections) + "\n"
    print("::group::Rust lane failure explanation")
    print(text)
    print("::endgroup::")
    target = os.environ.get("GITHUB_STEP_SUMMARY")
    if target:
        with open(target, "a") as stream:
            stream.write(text)
    return 0


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    sub = parser.add_subparsers(dest="command", required=True)
    run_parser = sub.add_parser("run")
    run_parser.add_argument("--name", required=True)
    run_parser.add_argument("--report-only", action="store_true")
    run_parser.add_argument("--cwd")
    run_parser.add_argument("argv", nargs=argparse.REMAINDER)
    sub.add_parser("summary")
    explain_parser = sub.add_parser("explain")
    explain_parser.add_argument("--root", default=".")
    args = parser.parse_args(argv)
    if args.command == "run":
        command = args.argv[1:] if args.argv[:1] == ["--"] else args.argv
        return run(args.name, command, blocking=not args.report_only, cwd=args.cwd)
    if args.command == "summary":
        return summary()
    return explain(Path(args.root))


if __name__ == "__main__":
    sys.exit(main())
