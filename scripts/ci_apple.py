"""Apple lanes for the isolated GitHub runner (`ci_coordinator.py submit --mode apple-core|apple-build|apple-unit|apple-ui`).

All modes run on a GitHub-hosted `macos-26` arm64 runner with Xcode 26.6 (the
version the release Mac builds with), never on the shared dev host.

  apple-core   target `all`: run the openmates-sdk (packages/openmates-rust) and
               openmates-apple-bindings tests natively on macOS, check the committed
               UniFFI bindings in apple/OpenMatesCore are fresh, build the
               OpenMatesCoreFFI xcframework (iOS, simulator, macOS) and then, as its own
               step, the Watch slices; print the sizes.
  apple-build  target `all`: compile only. `xcodebuild build-for-testing` of the OpenMates_iOS
               scheme (app, unit-test and UI-test targets) that keeps building after an error,
               so one run lists the Swift errors of every file it could reach. A target that
               imports a module which failed to compile is not reached.
  apple-unit   targets `all` or `OpenMatesTests[/<Class>[/<test>]]`: generate the design tokens and locales the project
               references, fetch the pinned Whistle link inputs, run the same build step as
               apple-build (a failed build lists all Swift errors and ends the job), then
               `xcodebuild test-without-building` on its products, limited to the
               OpenMatesTests unit target (XCUITest targets are never selected).
  apple-ui     targets `OpenMatesUITests/<Class>[/<test>]` (one or more, never `all`): the same
               generated inputs and build step, then exactly those XCUITests in the
               iOS simulator, serially. The app under test is the Debug build, so tests
               that talk to a server reach the dev backend; the lane passes no secrets,
               so real-account tests skip themselves.

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
UI_SPEC = re.compile(r"OpenMatesUITests(?:/[A-Za-z_][A-Za-z0-9_]*){1,2}")
MAX_UI_SPECS = 40
TEST_ALLOWANCE_SECONDS = 300  # per test; the longest real UI flow waits about 90 s
XCODE_MODES = ("apple-build", "apple-unit", "apple-ui")
RESULT_BUNDLES = {
    "apple-build": "OpenMatesBuild.xcresult",
    "apple-unit": "OpenMatesTests.xcresult",
    "apple-ui": "OpenMatesUITests.xcresult",
}
# Compiler diagnostics of the build lane: `<path>.swift:<line>:<column>: error: <text>`.
SWIFT_ERROR = re.compile(r"^(?P<path>/\S[^:]*\.swift):(?P<line>\d+):(?P<column>\d+): error: (?P<text>.+)$")
MAX_SWIFT_ERRORS = 400
# Core test fixtures: the Rust feature (Xcode phase) and the Swift compilation condition.
BUILD_STEP = "xcodebuild build-for-testing"
TEST_SUPPORT_SETTING = "OPENMATES_CORE_TEST_SUPPORT=YES"
TEST_SUPPORT_SWIFT_FLAGS = "OTHER_SWIFT_FLAGS=$(inherited) -DOPENMATES_CORE_TEST_SUPPORT"
RUST_TEST_FLAGS = ["--locked", "--lib", "--bins", "--tests"]

Step = tuple[str, list[str], dict, str]


def validate_specs(mode: str, specs: list[str]) -> list[str]:
    """Return the admitted selectors for the Apple mode or refuse the request."""
    if mode == "apple-core":
        if specs != [ALL]:
            raise ValueError("apple-core takes exactly one target: 'all'")
        return [ALL]
    if mode == "apple-build":
        if specs != [ALL]:
            raise ValueError("apple-build takes exactly one target: 'all'")
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
    if mode == "apple-ui":
        if (
            not specs
            or len(specs) > MAX_UI_SPECS
            or not all(isinstance(spec, str) and UI_SPEC.fullmatch(spec) for spec in specs)
        ):
            raise ValueError(
                f"apple-ui targets must be 1-{MAX_UI_SPECS} OpenMatesUITests/<Class>[/<test>] selectors"
            )
        return list(specs)
    raise ValueError("Unknown Apple CI mode")


def core_plan(root: Path, results: Path) -> list[Step]:
    """Ordered (name, argv, extra env, skip reason) steps for apple-core."""
    # macOS temp roots sit behind the /var -> /private/var symlink; the SDK's
    # destination checks (correctly) refuse symlinked paths, so tests get the real path.
    toolchain = {
        "RUSTUP_TOOLCHAIN": RUST_TOOLCHAIN,
        "TMPDIR": os.path.realpath(os.environ.get("RUNNER_TEMP", "/tmp")),
    }
    script = "packages/openmates-apple-bindings/build-xcframework.sh"
    framework_dir = results / "framework"
    swift_dir = results / "swift"
    return [
        (
            "openmates-sdk tests (macOS)",
            ["cargo", "test", "-p", "openmates-sdk", *RUST_TEST_FLAGS],
            toolchain,
            "",
        ),
        (
            "openmates-apple-bindings tests (macOS)",
            ["cargo", "test", "-p", "openmates-apple-bindings", "--locked"],
            toolchain,
            "",
        ),
        (
            "apple bindings are fresh",
            ["bash", script, "--check-bindings"],
            {},
            "",
        ),
        (
            "OpenMatesCore xcframework (iOS, simulator, macOS)",
            ["bash", script, "--framework-dir", str(framework_dir), str(swift_dir)],
            {},
            "",
        ),
        (
            "OpenMatesCore xcframework WATCH slices",
            ["bash", script, "--watch", "--framework-dir", str(framework_dir), str(swift_dir)],
            {},
            "",
        ),
        (
            "OpenMatesCore sizes",
            [
                "bash", "-c",
                f'du -sh "{framework_dir}"/*.xcframework && '
                f'find "{framework_dir}"/*.xcframework -name "*.a" -exec du -h {{}} +',
            ],
            {},
            "",
        ),
    ]


def xcode_plan(mode: str, results: Path, specs: list[str]) -> list[Step]:
    """Ordered steps for the Xcode lanes: generated inputs, then the build or the selected tests."""
    build_only = mode == "apple-build"
    only = [] if build_only else [UNIT_TARGET] if specs == [ALL] else specs
    shared = [
        "-project", "apple/OpenMates.xcodeproj",
        "-scheme", "OpenMates_iOS",
        "-destination", f"platform=iOS Simulator,name={SIMULATOR}",
        "-derivedDataPath", str(results / "DerivedData"),
        "-clonedSourcePackagesDirPath", str(results / "SourcePackages"),
        "-skipPackagePluginValidation", "-skipMacroValidation",
    ]
    # The script phases (OpenMatesCore, LocalModelBridge) run cargo and read repository
    # files, which Xcode's script sandbox denies; the TestFlight build passes the same override.
    settings = ["CODE_SIGNING_ALLOWED=NO", "CODE_SIGN_IDENTITY=", "ENABLE_USER_SCRIPT_SANDBOXING=NO"]
    # The runner and its simulators are arm64. Without this the embedded Watch app is also
    # built for the x86_64 simulator, whose Rust core is a tier-3 build-std build (about
    # 14 minutes) that no test uses.
    settings += ["EXCLUDED_ARCHS=x86_64"]
    # Every lane builds the Debug app with the core's test fixtures: the OpenMatesCore phase
    # adds `--features test-support` (build-xcframework.sh refuses it outside Debug), and the
    # Swift condition of the same name compiles the fixture glue that links against it (the UI
    # fixtures seed the core's cached chat list). They are always set together; a Release build
    # with the condition fails to compile. The core and TestFlight lanes never set either.
    settings += [TEST_SUPPORT_SETTING, TEST_SUPPORT_SWIFT_FLAGS]
    # One build per job, for every lane. Xcode's "Continue building after errors" compiles
    # every reachable file, so a failed build lists all Swift errors instead of the first batch.
    build = [
        "xcodebuild", "build-for-testing", *shared,
        "-resultBundlePath", str(results / RESULT_BUNDLES["apple-build"]),
        "-IDEBuildingContinueBuildingAfterErrors=YES", *settings,
    ]
    steps: list[Step] = [(BUILD_STEP, build, {}, "")]
    if not build_only:
        # The tests run on the products of the build above; nothing is compiled twice.
        # A test that never returns (for example audio playback without an output device on
        # the runner) is failed after its allowance instead of stalling the lane.
        test = [
            "xcodebuild", "test-without-building", *shared,
            "-resultBundlePath", str(results / RESULT_BUNDLES[mode]),
            "-test-timeouts-enabled", "YES",
            "-default-test-execution-time-allowance", str(TEST_ALLOWANCE_SECONDS),
            "-maximum-test-execution-time-allowance", str(TEST_ALLOWANCE_SECONDS),
        ]
        if mode == "apple-ui":
            # One simulator, one test at a time: UI tests share the app's on-device state.
            test += ["-parallel-testing-enabled", "NO"]
        for selector in only:
            test += ["-only-testing", selector]
        steps.append((f"xcodebuild test {' '.join(only)}"[:160], test + settings, {}, ""))
    return [
        (
            "design tokens and locales",
            [
                "bash", "-c",
                "cd frontend/packages/ui && node scripts/build-tokens.js && node scripts/build-translations.js",
            ],
            {},
            "",
        ),
        (
            "whistle link inputs",
            ["python3", "apple/WhistleBridge/prepare-build.py", "--fetch"],
            {},
            "",
        ),
        *steps,
    ]


def swift_errors(lines: list[str], root: Path) -> list[str]:
    """Unique Swift compiler errors of a build log, repository-relative, in first-seen order."""
    prefix = f"{root}/"
    seen: dict[str, None] = {}
    for line in lines:
        match = SWIFT_ERROR.match(line.strip())
        if match:
            path = match["path"].removeprefix(prefix)
            seen.setdefault(f"{path}:{match['line']}:{match['column']}: error: {match['text']}"[:300])
    return list(seen)[:MAX_SWIFT_ERRORS]


def run(root: Path, results: list[dict], mode: str, specs: list[str]) -> None:
    import ci_rust_checks as checks

    specs = validate_specs(mode, specs)
    out = root / "test-results" / mode
    out.mkdir(parents=True, exist_ok=True)
    os.environ["RUST_CI_RESULTS"] = str(out / "rows")
    plan = core_plan(root, out) if mode == "apple-core" else xcode_plan(mode, out, specs)
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
        failures = [line[:300] for line in row["excerpt"][:40]]
        if name == BUILD_STEP and code != 0:
            log = out / "rows" / f"{checks.slug(name)}.log"
            found = swift_errors(log.read_text(errors="replace").splitlines(), root) if log.is_file() else []
            if found:
                (out / "swift-errors.txt").write_text("\n".join(found) + "\n")
                print(f"::group::Swift errors ({len(found)})\n" + "\n".join(found) + "\n::endgroup::", flush=True)
                failures = found
        results.append(
            {
                "suite": f"{mode}:{name}", "target": specs[0],
                "command": " ".join(command), "exit_code": code,
                "seconds": row["seconds"], "diagnostics": row["diagnostics"],
                "failures": failures,
            }
        )
        if mode in XCODE_MODES and code != 0:
            break  # the test run cannot proceed without its generated inputs


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
