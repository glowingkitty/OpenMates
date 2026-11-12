"""Rust check lane for the isolated GitHub runner (`ci_coordinator.py submit --mode rust-check`).

Runs cargo tests and compile checks on the exact candidate source so Rust never
builds on the shared dev host. One target per job:

  all              workspace tests (lib, bins, tests; examples excluded like
                   rust.yml), the SDK-only `openmates` build and a wasm32 check
                   of `openmates-browser-bindings`
  <crate>          `cargo test -p <crate>` (lib, bins, tests)
  <crate>::<name>  the same, restricted to tests whose path contains <name>

Every step keeps its bounded log and a failure excerpt (the first failing
tests, panics and compiler errors) in the result rows, so `ci_coordinator.py
result` shows the failures without opening the Actions log.
"""

from __future__ import annotations

import os
import re
from pathlib import Path

CRATE = re.compile(r"[a-z][a-z0-9_-]{0,63}")
FILTER = re.compile(r"[A-Za-z0-9_]+(?:::[A-Za-z0-9_]+)*")
ALL = "all"
MAX_FAILURE_LINES = 40
MAX_LINE = 300
TEST_FLAGS = ["--locked", "--lib", "--bins", "--tests"]
# Features a single-crate run must enable so it compiles what the shipping
# binaries compile: the CLI builds the SDK with `workflow-yaml`, which gates the
# remote-access host modules and their tests.
CRATE_FEATURES = {"openmates-sdk": ["workflow-yaml"]}


def validate_specs(specs: list[str]) -> list[str]:
    """Return the single admitted target or refuse the request."""
    if not isinstance(specs, list) or len(specs) != 1 or not isinstance(specs[0], str):
        raise ValueError("Rust check requires exactly one target: 'all' or '<crate>[::<test-filter>]'")
    target = specs[0]
    if target == ALL:
        return [ALL]
    crate, separator, test_filter = target.partition("::")
    if not CRATE.fullmatch(crate) or (separator and not FILTER.fullmatch(test_filter)):
        raise ValueError("Rust check target must be 'all', '<crate>' or '<crate>::<test-filter>'")
    return [target]


def plan(target: str) -> list[tuple[str, list[str]]]:
    """Ordered (step name, argv) pairs; every step runs even if an earlier one fails."""
    if target == ALL:
        return [
            ("workspace test", ["cargo", "test", "--workspace", *TEST_FLAGS]),
            (
                "openmates sdk-only check",
                ["cargo", "check", "--locked", "-p", "openmates", "--no-default-features", "--lib"],
            ),
            (
                "browser-bindings wasm32 check",
                [
                    "cargo", "check", "--locked", "-p", "openmates-browser-bindings",
                    "--target", "wasm32-unknown-unknown", "--lib",
                ],
            ),
        ]
    crate, separator, test_filter = target.partition("::")
    command = ["cargo", "test", "-p", crate, *TEST_FLAGS]
    features = CRATE_FEATURES.get(crate)
    if features:
        command += ["--features", ",".join(features)]
    if separator:
        command += ["--", test_filter]
    return [(f"{crate} test" + (f" ({test_filter})" if separator else ""), command)]


def run(root: Path, results: list[dict], specs: list[str]) -> None:
    import ci_rust_checks as checks

    (target,) = validate_specs(specs)
    out = root / "test-results" / "rust-check"
    out.mkdir(parents=True, exist_ok=True)
    os.environ["RUST_CI_RESULTS"] = str(out)
    for name, command in plan(target):
        code = checks.run(name, command, blocking=True, cwd=str(root))
        # run() persists the row it just wrote; the newest file is this step.
        row = checks.load_rows()[-1]
        results.append(
            {
                "suite": f"rust-check:{name}",
                "target": target,
                "command": " ".join(command),
                "exit_code": code,
                "seconds": row["seconds"],
                "diagnostics": row["diagnostics"],
                "failures": [line[:MAX_LINE] for line in row["excerpt"][:MAX_FAILURE_LINES]],
            }
        )
