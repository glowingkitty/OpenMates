"""Apple lanes for the isolated GitHub runner (`ci_coordinator.py submit --mode apple-core|apple-build|apple-unit|apple-ui`).

All modes run on a GitHub-hosted `macos-26` arm64 runner with Xcode 26.6 (the
version the release Mac builds with), never on the shared dev host.

  apple-core   target `all`: run the openmates-sdk (packages/openmates-rust) and
               openmates-apple-bindings tests natively on macOS, check the committed
               UniFFI bindings in apple/OpenMatesCore are fresh, build the
               OpenMatesCoreFFI xcframework (iOS, simulator, macOS) and then, as its own
               step, the Watch slices; print the sizes.
  apple-build  target `all`: compile only. `xcodebuild build-for-testing` of the OpenMates_iOS
               scheme (app, embedded Watch app, unit-test and UI-test targets), then, in the
               same job and even when that failed, `xcodebuild build` of the OpenMates_macOS
               scheme. Both keep building after an error, so one run lists the Swift errors of
               every file either build could reach. A target that imports a module which
               failed to compile is not reached.
  apple-unit   targets `all` or `OpenMatesTests[/<Class>[/<test>]]`: generate the design tokens and locales the project
               references, fetch the pinned Whistle link inputs, run the same build step as
               apple-build (a failed build lists all Swift errors and ends the job), then
               `xcodebuild test-without-building` on its products, limited to the
               OpenMatesTests unit target (XCUITest targets are never selected).
  apple-ui     targets `OpenMatesUITests/<Class>[/<test>]` (one or more, never `all`): the same
               generated inputs and build step, then exactly those XCUITests in the
               iOS simulator, serially. The app under test is the Debug build, so tests
               that talk to a server reach the dev backend; the lane passes no secrets,
               so real-account tests skip themselves. The private startup evidence profile
               also admits the exact two read-only selectors in OpenMatesMacUITests.
               A focused run (at most
               MAX_RECORDED_UI_SPECS targets) runs from a patched copy of the built
               .xctestrun that keeps the screen recording of every test,
               passing ones too, so a UI change has its result video; larger runs keep
               only the recordings of failed tests.

Every step records a result row through ci_rust_checks so the coordinator and
`ci_coordinator.py result` show failing excerpts without opening Actions logs.
"""

from __future__ import annotations

import os
import re
import shutil
import sys
import time
from pathlib import Path

ALL = "all"
RUST_TOOLCHAIN = "1.98.1"
SIMULATOR = "iPhone 17"
UNIT_TARGET = "OpenMatesTests"
UNIT_SPEC = re.compile(r"OpenMatesTests(?:/[A-Za-z_][A-Za-z0-9_]*){0,2}")
UI_SPEC = re.compile(r"OpenMatesUITests(?:/[A-Za-z_][A-Za-z0-9_]*){1,2}")
MAX_UI_SPECS = 40
# Focused UI runs keep every screen recording (the result video of a UI change); a large
# run would upload hundreds of megabytes of passing-test video nobody watches.
MAX_RECORDED_UI_SPECS = 12
KEEP_RECORDINGS_STEP = "keep screen recordings of passing tests"
SIGN_MAC_STARTUP_STEP = "sign the private macOS startup test app"
RECORDED_XCTESTRUN = "OpenMates_recorded.xctestrun"
# Attachment lifetimes in an .xctestrun: system attachments and, separately, the automatic
# UI-test screen capture ("On, and keep all" in a test plan).
KEEP_ALL_KEYS = ("SystemAttachmentLifetime", "UITestingScreenshotsLifetime")
STARTUP_BENCHMARK_SPECS = {
    "OpenMatesUITests/ChatFlowRealAccountUITests/testPersonalAccountColdLaunchFirstFrame",
    "OpenMatesUITests/ChatFlowRealAccountUITests/testPersonalAccountColdLaunchToInteractive",
}
MAC_STARTUP_BENCHMARK_SPECS = {
    spec.replace("OpenMatesUITests/", "OpenMatesMacUITests/", 1)
    for spec in STARTUP_BENCHMARK_SPECS
}
PERSONAL_CREDENTIAL_KEYS = tuple(
    f"OPENMATES_PERSONAL_TEST_ACOUNT_{suffix}" for suffix in ("EMAIL", "PASSWORD", "OTP_KEY")
)
# Release optimisation for the private startup benchmark (the Release defaults).
OPTIMIZED_BENCHMARK_SETTINGS = (
    "SWIFT_OPTIMIZATION_LEVEL=-O",
    "SWIFT_COMPILATION_MODE=wholemodule",
    "GCC_OPTIMIZATION_LEVEL=s",
)
# Time Profiler trace of one benchmarked app process: where its main thread
# spends startup. The host `sample` tool records no frames of Simulator apps.
APP_PROFILE_SECONDS = 15
APP_SAMPLE_POLL_SECONDS = 0.1
APP_SAMPLED_PROCESS = 2
APP_PROCESS_PATTERN = r"OpenMates\.app/(Contents/MacOS/)?OpenMates( |$)"
TEST_ALLOWANCE_SECONDS = 300
# Private startup preserves all three process relaunches and their independent
# foreground, sidebar, reconciliation and quiet-process measurements.
STARTUP_TEST_ALLOWANCE_SECONDS = 600
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
MACOS_BUILD_STEP = "xcodebuild build OpenMates_macOS"
BUILD_STEPS = (BUILD_STEP, MACOS_BUILD_STEP)
TEST_SUPPORT_SETTING = "OPENMATES_CORE_TEST_SUPPORT=YES"
TEST_SUPPORT_SWIFT_FLAGS = "OTHER_SWIFT_FLAGS=$(inherited) -DOPENMATES_CORE_TEST_SUPPORT"
# --no-fail-fast: a failing test binary must not hide the results of the others.
RUST_TEST_FLAGS = ["--locked", "--no-fail-fast", "--lib", "--bins", "--tests"]

Step = tuple[str, list[str], dict, str]


def startup_benchmark_platform(specs: list[str]) -> str | None:
    """Recognize one platform's exact pair of private read-only selectors."""
    if len(specs) != len(STARTUP_BENCHMARK_SPECS) or not all(
        isinstance(spec, str) for spec in specs
    ):
        return None
    if set(specs) == STARTUP_BENCHMARK_SPECS:
        return "iOS"
    if set(specs) == MAC_STARTUP_BENCHMARK_SPECS:
        return "macOS"
    return None


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
        if startup_benchmark_platform(specs) == "macOS":
            return list(specs)
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
            ["cargo", "test", "-p", "openmates-apple-bindings", "--locked", "--no-fail-fast"],
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


def xcode_plan(mode: str, results: Path, specs: list[str], *, benchmark: bool = False) -> list[Step]:
    """Ordered steps for the Xcode lanes: generated inputs, then the build or the selected tests."""
    build_only = mode == "apple-build"
    only = [] if build_only else [UNIT_TARGET] if specs == [ALL] else specs
    startup_platform = startup_benchmark_platform(specs) if benchmark and mode == "apple-ui" else None
    mac_startup = startup_platform == "macOS"
    allowance = STARTUP_TEST_ALLOWANCE_SECONDS if startup_platform else TEST_ALLOWANCE_SECONDS
    scheme = "OpenMates_macOS" if mac_startup else "OpenMates_iOS"
    destination = "platform=macOS" if mac_startup else f"platform=iOS Simulator,name={SIMULATOR}"
    shared = [
        "-project", "apple/OpenMates.xcodeproj",
        "-scheme", scheme,
        "-destination", destination,
        "-derivedDataPath", str(results / "DerivedData"),
        "-clonedSourcePackagesDirPath", str(results / "SourcePackages"),
        "-skipPackagePluginValidation", "-skipMacroValidation",
    ]
    if mac_startup:
        shared += ["-configuration", "Debug"]
    # The script phases (OpenMatesCore, LocalModelBridge) run cargo and read repository
    # files, which Xcode's script sandbox denies; the TestFlight build passes the same override.
    signing = ["CODE_SIGNING_ALLOWED=YES", "CODE_SIGN_IDENTITY=-"] if benchmark else [
        "CODE_SIGNING_ALLOWED=NO", "CODE_SIGN_IDENTITY=",
    ]
    settings = [*signing, "ENABLE_USER_SCRIPT_SANDBOXING=NO"]
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
    if startup_platform:
        # Timings must reflect shipped code: the Release optimizer on the Debug
        # configuration that still compiles the benchmark's timing probes.
        settings += list(OPTIMIZED_BENCHMARK_SETTINGS)
    # One build per job, for every lane. Xcode's "Continue building after errors" compiles
    # every reachable file, so a failed build lists all Swift errors instead of the first batch.
    build = [
        "xcodebuild", "build-for-testing", *shared,
        "-resultBundlePath", str(results / RESULT_BUNDLES["apple-build"]),
        "-IDEBuildingContinueBuildingAfterErrors=YES", *settings,
    ]
    steps: list[Step] = [(BUILD_STEP, build, {}, "")]
    products = results / "DerivedData" / "Build" / "Products"
    if mac_startup:
        steps.append((
            SIGN_MAC_STARTUP_STEP,
            [
                sys.executable, str(Path(__file__).resolve()), "sign-macos-startup",
                str(products / "Debug" / "OpenMates.app"),
            ],
            {},
            "",
        ))
    recorded = mode == "apple-ui" and len(only) <= MAX_RECORDED_UI_SPECS
    if recorded:
        steps.append((
            KEEP_RECORDINGS_STEP,
            [sys.executable, str(Path(__file__).resolve()), "keep-recordings", str(products)],
            {},
            "",
        ))
    if build_only:
        # The macOS app shares most sources but has its own platform branches; the build lane
        # compiles it too, so macOS-only errors arrive in the same round as the iOS ones.
        steps.append((
            MACOS_BUILD_STEP,
            [
                "xcodebuild", "build",
                "-project", "apple/OpenMates.xcodeproj",
                "-scheme", "OpenMates_macOS",
                "-configuration", "Debug",
                "-destination", "platform=macOS",
                "-derivedDataPath", str(results / "DerivedData"),
                "-clonedSourcePackagesDirPath", str(results / "SourcePackages"),
                "-skipPackagePluginValidation", "-skipMacroValidation",
                "-resultBundlePath", str(results / "OpenMatesMacBuild.xcresult"),
                "-IDEBuildingContinueBuildingAfterErrors=YES", *settings,
            ],
            {},
            "",
        ))
    if not build_only:
        # The tests run on the products of the build above; nothing is compiled twice.
        # A test that never returns (for example audio playback without an output device on
        # the runner) is failed after its allowance instead of stalling the lane.
        # A recorded run tests from the patched copy of the built .xctestrun; `-scheme`
        # would run Xcode's own unpatched one.
        source = (
            ["-xctestrun", str(products / RECORDED_XCTESTRUN), "-destination", destination]
            if recorded else shared
        )
        test = [
            "xcodebuild", "test-without-building", *source,
            "-resultBundlePath", str(results / RESULT_BUNDLES[mode]),
            "-test-timeouts-enabled", "YES",
            "-default-test-execution-time-allowance", str(allowance),
            "-maximum-test-execution-time-allowance", str(allowance),
        ]
        if mode == "apple-ui":
            # One simulator, one test at a time: UI tests share the app's on-device state.
            test += ["-parallel-testing-enabled", "NO"]
        for selector in only:
            test += ["-only-testing", selector]
        # Build settings belong to the scheme run; the patched .xctestrun carries the built ones.
        steps.append((f"xcodebuild test {' '.join(only)}"[:160], test + ([] if recorded else settings), {}, ""))
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


def sign_macos_startup_app(root: Path, app: Path) -> None:
    """Apply the existing Personal Team signing recipe to the hosted Debug bundle."""
    import plistlib
    import subprocess

    # Match apple_local_macos.sh. taskgated rejects the ordinary paid-team
    # entitlements when the hosted runner ad-hoc signs without a profile.
    app_entitlements = root / "apple/OpenMates/Resources/OpenMatesMacOSPersonalTeam.entitlements"
    extension_entitlements = root / (
        "apple/OpenMatesShareExtensionMacOS/OpenMatesShareExtensionMacOSPersonalTeam.entitlements"
    )
    allowed = {
        app_entitlements: {
            "com.apple.security.files.user-selected.read-only",
            "com.apple.security.device.camera",
            "com.apple.security.device.audio-input",
        },
        extension_entitlements: {
            "com.apple.security.app-sandbox",
            "com.apple.security.network.client",
        },
    }
    for path, allowed_keys in allowed.items():
        entitlements = plistlib.loads(path.read_bytes())
        if (
            not isinstance(entitlements, dict)
            or entitlements.keys() - allowed_keys
            or any(value is not True for value in entitlements.values())
        ):
            raise ValueError("The hosted macOS ad-hoc signature requires unrestricted entitlements")

    contents = app / "Contents"
    info_path = contents / "Info.plist"
    info = plistlib.loads(info_path.read_bytes())
    if info.get("CFBundleIdentifier") != "org.openmates.app":
        raise ValueError("The hosted macOS startup build did not produce the OpenMates app")
    # An ad-hoc app uses its default Keychain access. Leaving the production
    # override in this copy makes KeychainHelper ask for a group it cannot use.
    if "OpenMatesKeychainAccessGroup" in info:
        del info["OpenMatesKeychainAccessGroup"]
        info_path.write_bytes(plistlib.dumps(info, fmt=plistlib.FMT_BINARY))

    for extension in sorted((contents / "PlugIns").glob("*.appex")):
        subprocess.run(
            ["codesign", "--force", "--sign", "-", "--entitlements", str(extension_entitlements), str(extension)],
            check=True,
        )
    subprocess.run(
        ["codesign", "--force", "--sign", "-", "--entitlements", str(app_entitlements), str(app)], check=True,
    )
    subprocess.run(["codesign", "--verify", "--deep", "--strict", str(app)], check=True)


def keep_recordings(products: Path) -> int:
    """Write RECORDED_XCTESTRUN: the built .xctestrun with passing-test recordings kept.

    The .xctestrun that build-for-testing wrote deletes system attachments (screen
    recordings) of passing tests. The copy sits beside it, so its __TESTROOT__ paths stay
    valid, and the recorded test step runs it with `-xctestrun`. Returns the number of UI
    test targets changed and raises when there is no single built .xctestrun or no UI test
    target in it, so a missing video is a failed step rather than a silent gap.
    """
    import plistlib

    built = [p for p in sorted(products.glob("*.xctestrun")) if p.name != RECORDED_XCTESTRUN]
    if len(built) != 1:
        raise ValueError(f"expected one built .xctestrun under {products}, found {len(built)}")
    data = plistlib.loads(built[0].read_bytes())
    if "TestConfigurations" in data:
        targets = [t for c in data["TestConfigurations"] for t in c.get("TestTargets", [])]
    else:  # format version 1: one top-level dictionary per test target
        targets = [v for v in data.values() if isinstance(v, dict) and "TestBundlePath" in v]
    ui = [t for t in targets if t.get("IsUITestBundle")]
    if not ui:
        raise ValueError(f"no UI test target in {built[0].name}")
    for target in ui:
        # The key names, so a run shows which lifetime settings this Xcode writes.
        print(f"{target.get('BlueprintName', '?')} keys: {', '.join(sorted(target))}", flush=True)
        for key in KEEP_ALL_KEYS:
            target[key] = "keepAlways"
        target["PreferredScreenCaptureFormat"] = "screenRecording"
    (products / RECORDED_XCTESTRUN).write_bytes(plistlib.dumps(data))
    print(f"screen recordings kept for {len(ui)} UI test target(s) in {RECORDED_XCTESTRUN}", flush=True)
    return len(ui)


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


def run_private_benchmark(root: Path, command: list[str], output: Path, credentials: dict[str, str]) -> int:
    """Never stream real-account XCTest output to the public Actions log."""
    import subprocess

    credential_file = root / "apple/.openmates-live-test-account.env"
    if any("\n" in value or "\r" in value for value in credentials.values()):
        raise ValueError("Invalid personal benchmark credential format")
    with os.fdopen(os.open(credential_file, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600), "w") as handle:
        handle.writelines(f"{key}={value}\n" for key, value in credentials.items())
    import threading

    stop = threading.Event()
    sampler = threading.Thread(target=sample_app_process, args=(output / "private-samples", stop), daemon=True)
    sampler.start()
    try:
        with (output / "private-xcode.log").open("w") as log:
            return subprocess.run(command, cwd=root, stdout=log, stderr=subprocess.STDOUT, check=False).returncode
    finally:
        stop.set()
        sampler.join(timeout=APP_PROFILE_SECONDS + 240)
        credential_file.unlink()


def sample_app_process(folder: Path, stop) -> None:
    """Record a Time Profiler trace of exactly one launched OpenMates app process.

    The macOS app and the iOS Simulator app are both host processes. Only the
    second distinct process (the first cached relaunch after sign-in) is
    profiled, so the other launches keep undisturbed timings; that launch is
    left out of the medians. The trace and its exported time-profile table
    stay in the private evidence; failures are logged beside them.
    """
    import subprocess

    folder.mkdir(parents=True, exist_ok=True)
    seen: list[str] = []
    while not stop.wait(APP_SAMPLE_POLL_SECONDS):
        # The app is launched with test arguments after its executable path.
        found = subprocess.run(["pgrep", "-n", "-f", APP_PROCESS_PATTERN],
                               capture_output=True, text=True, check=False).stdout.split()
        if not found:
            continue
        if found[0] not in seen:
            seen.append(found[0])
        if len(seen) < APP_SAMPLED_PROCESS:
            continue
        trace = folder / f"launch-pid{found[0]}.trace"
        steps = [
            ["xcrun", "xctrace", "record", "--template", "Time Profiler", "--attach", found[0],
             "--time-limit", f"{APP_PROFILE_SECONDS}s", "--output", str(trace), "--no-prompt"],
            ["xcrun", "xctrace", "export", "--input", str(trace), "--toc",
             "--output", str(folder / "toc.xml")],
            ["xcrun", "xctrace", "export", "--input", str(trace), "--xpath",
             '/trace-toc/run[@number="1"]/data/table[@schema="time-profile"]',
             "--output", str(folder / "time-profile.xml")],
        ]
        with (folder / "sampler.log").open("a") as log:
            for step in steps:
                done = subprocess.run(step, capture_output=True, text=True, check=False,
                                      timeout=APP_PROFILE_SECONDS + 120)
                log.write(f"{step[2]} exit {done.returncode}\n{done.stderr[-2000:]}\n")
        # The exported table holds every sampled stack; the raw bundle is large.
        shutil.rmtree(trace, ignore_errors=True)
        return


def run(root: Path, results: list[dict], mode: str, specs: list[str]) -> None:
    specs = validate_specs(mode, specs)
    benchmark = os.environ.get("CI_APPLE_PRIVATE_STARTUP") == "1"
    credentials = {key: os.environ.pop(key, "") for key in PERSONAL_CREDENTIAL_KEYS}
    benchmark_platform = startup_benchmark_platform(specs)
    if benchmark and (mode != "apple-ui" or benchmark_platform is None):
        raise ValueError("Private Apple startup runs require both exact benchmark selectors for one platform")
    if benchmark_platform == "macOS" and not benchmark:
        raise ValueError("The macOS startup benchmark requires private evidence")
    if benchmark and not all(credentials.values()):
        raise ValueError("The private Apple startup lane requires repository test credentials")

    import ci_rust_checks as checks

    out = root / "test-results" / mode
    out.mkdir(parents=True, exist_ok=True)
    os.environ["RUST_CI_RESULTS"] = str(out / "rows")
    plan = core_plan(root, out) if mode == "apple-core" else xcode_plan(mode, out, specs, benchmark=benchmark)
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
        if benchmark and command[:2] == ["xcodebuild", "test-without-building"]:
            started = time.monotonic()
            code = run_private_benchmark(root, command, out, credentials)
            results.append({
                "suite": f"{mode}:private startup", "target": specs[0],
                "command": "xcodebuild test-without-building", "exit_code": code,
                "seconds": round(time.monotonic() - started, 1), "diagnostics": 0, "failures": [],
            })
            break
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
        if name in BUILD_STEPS and code != 0:
            log = out / "rows" / f"{checks.slug(name)}.log"
            found = swift_errors(log.read_text(errors="replace").splitlines(), root) if log.is_file() else []
            if found:
                with (out / "swift-errors.txt").open("a") as errors:
                    errors.write("\n".join(found) + "\n")
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
        if mode in XCODE_MODES and code != 0 and not (mode == "apple-build" and name == BUILD_STEP):
            break  # the test run cannot proceed without its generated inputs or its build


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
    if sys.argv[1:2] == ["keep-recordings"]:
        keep_recordings(Path(sys.argv[2]))
    elif sys.argv[1:2] == ["sign-macos-startup"]:
        sign_macos_startup_app(Path.cwd(), Path(sys.argv[2]))
    else:
        main()
