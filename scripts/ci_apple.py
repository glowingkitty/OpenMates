"""Apple lanes for the isolated GitHub runner (`ci_coordinator.py submit --mode apple-core|apple-unit`).

Both modes run on a GitHub-hosted `macos-26` arm64 runner with Xcode 26.2 (the
version apple/project.yml pins), never on the shared dev host.

  apple-core   target `all`: build PairOpaqueBridge for the iOS simulator slice
               with the Xcode build-phase semantics, run the Rust workspace and
               PairOpaqueBridge test suites natively on macOS, and test the
               Swift package apple/OpenMatesCore when it exists.
  apple-unit   targets `all` or `OpenMatesTests[/<Class>[/<test>]]`: fetch the
               pinned Whistle link inputs, then `xcodebuild test` the
               OpenMates_iOS scheme limited to the OpenMatesTests unit target
               (XCUITest targets are never selected).

Every step records a result row through ci_rust_checks so the coordinator and
`ci_coordinator.py result` show failing excerpts without opening Actions logs.
"""

from __future__ import annotations

import os
import re
from pathlib import Path

ALL = "all"
RUST_TOOLCHAIN = "1.98.1"
SIMULATOR = "iPhone 17"
UNIT_TARGET = "OpenMatesTests"
UNIT_SPEC = re.compile(r"OpenMatesTests(?:/[A-Za-z_][A-Za-z0-9_]*){0,2}")
RUST_TEST_FLAGS = ["--locked", "--lib", "--bins", "--tests"]

Step = tuple[str, list[str], dict, str]


def validate_specs(mode: str, specs: list[str]) -> list[str]:
    """Return the admitted selectors for the Apple mode or refuse the request."""
    if mode == "apple-core":
        if specs != [ALL]:
            raise ValueError("apple-core takes exactly one target: 'all'")
        return [ALL]
    if mode == "apple-unit":
        if not specs or not all(
            isinstance(spec, str) and (spec == ALL or UNIT_SPEC.fullmatch(spec))
            for spec in specs
        ):
            raise ValueError(
                "apple-unit targets must be 'all' or OpenMatesTests/<Class>[/<test>]"
            )
        if ALL in specs and len(specs) > 1:
            raise ValueError("apple-unit target 'all' cannot be combined with others")
        return list(specs)
    raise ValueError("Unknown Apple CI mode")


def core_plan(root: Path, results: Path) -> list[Step]:
    """Ordered (name, argv, extra env, skip reason) steps for apple-core."""
    bridge_env = {
        "PLATFORM_NAME": "iphonesimulator",
        "ARCHS": "arm64",
        "DERIVED_FILE_DIR": str(results / "derived"),
    }
    toolchain = {"RUSTUP_TOOLCHAIN": RUST_TOOLCHAIN}
    has_package = (root / "apple" / "OpenMatesCore" / "Package.swift").is_file()
    return [
        (
            "pair-opaque bridge (iphonesimulator arm64)",
            ["bash", "apple/PairOpaqueBridge/build-apple.sh"],
            bridge_env,
            "",
        ),
        (
            "pair-opaque bridge tests (macOS)",
            ["cargo", "test", "--manifest-path", "apple/PairOpaqueBridge/Cargo.toml", "--locked"],
            toolchain,
            "",
        ),
        (
            "openmates-rust tests (macOS)",
            ["cargo", "test", "--workspace", *RUST_TEST_FLAGS],
            toolchain,
            "",
        ),
        (
            "OpenMatesCore swift tests",
            ["swift", "test", "--package-path", "apple/OpenMatesCore"],
            {},
            ""
            if has_package
            else "apple/OpenMatesCore is absent in this source; Swift package tests skipped",
        ),
    ]


def unit_plan(root: Path, results: Path, specs: list[str]) -> list[Step]:
    """Ordered steps for apple-unit: fetch link inputs, then unit tests only."""
    only = [UNIT_TARGET] if specs == [ALL] else specs
    command = [
        "xcodebuild", "test",
        "-project", "apple/OpenMates.xcodeproj",
        "-scheme", "OpenMates_iOS",
        "-destination", f"platform=iOS Simulator,name={SIMULATOR}",
        "-derivedDataPath", str(results / "DerivedData"),
        "-clonedSourcePackagesDirPath", str(results / "SourcePackages"),
        "-resultBundlePath", str(results / "OpenMatesTests.xcresult"),
        "-skipPackagePluginValidation", "-skipMacroValidation",
    ]
    for selector in only:
        command += ["-only-testing", selector]
    command += ["CODE_SIGNING_ALLOWED=NO", "CODE_SIGN_IDENTITY="]
    return [
        (
            "whistle link inputs",
            ["python3", "apple/WhistleBridge/prepare-build.py", "--fetch"],
            {},
            "",
        ),
        (f"xcodebuild test {' '.join(only)}", command, {}, ""),
    ]


def run(root: Path, results: list[dict], mode: str, specs: list[str]) -> None:
    import ci_rust_checks as checks

    specs = validate_specs(mode, specs)
    out = root / "test-results" / mode
    out.mkdir(parents=True, exist_ok=True)
    os.environ["RUST_CI_RESULTS"] = str(out / "rows")
    plan = core_plan(root, out) if mode == "apple-core" else unit_plan(root, out, specs)
    for name, command, extra_env, skip in plan:
        if skip:
            print(f"::notice title={name}::{skip}", flush=True)
            results.append(
                {
                    "suite": f"{mode}:{name}", "target": specs[0],
                    "command": " ".join(command), "exit_code": 0, "seconds": 0,
                    "skipped": skip, "diagnostics": 0, "failures": [],
                }
            )
            continue
        saved = {key: os.environ.get(key) for key in extra_env}
        os.environ.update(extra_env)
        try:
            code = checks.run(name, command, blocking=True, cwd=str(root))
        finally:
            for key, value in saved.items():
                if value is None:
                    os.environ.pop(key, None)
                else:
                    os.environ[key] = value
        row = checks.load_rows()[-1]
        results.append(
            {
                "suite": f"{mode}:{name}", "target": specs[0],
                "command": " ".join(command), "exit_code": code,
                "seconds": row["seconds"], "diagnostics": row["diagnostics"],
                "failures": [line[:300] for line in row["excerpt"][:40]],
            }
        )
        if mode == "apple-unit" and code != 0:
            break  # the unit run cannot proceed without its link inputs


def main() -> None:
    """Runner entrypoint: execute the mode and write the coordinator's ci-results.json."""
    import json
    import subprocess

    root = Path.cwd()
    mode = os.environ["CI_TEST_MODE"]
    results: list[dict] = []
    error = None
    try:
        run(root, results, mode, json.loads(os.environ["CI_SPECS_JSON"]))
    except (ValueError, OSError, subprocess.SubprocessError) as exc:
        error = str(exc)  # reported in the result payload, never swallowed
    payload = {
        "source_commit": subprocess.check_output(
            ["git", "rev-parse", "HEAD"], cwd=root, text=True
        ).strip(),
        "run_id": os.environ["GITHUB_RUN_ID"],
        "environment": "github-isolated",
        "harness_commit": os.environ.get("CI_HARNESS_COMMIT"),
        "runtime_profile": mode,
        "case_title": "",
        "coverage_scope": "full-spec",
        "artifact_shared_dev_rejected": False,
        "proof_dimensions": None,
        "proof_profile": "",
        "results": results,
        "error": error,
        "success": bool(results)
        and not error
        and all(r["exit_code"] == 0 for r in results),
    }
    (root / "test-results").mkdir(exist_ok=True)
    (root / "test-results" / "ci-results.json").write_text(json.dumps(payload, indent=2))
    raise SystemExit(0 if payload["success"] else 1)


if __name__ == "__main__":
    main()
