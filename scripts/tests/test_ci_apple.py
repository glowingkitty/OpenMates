# contract-test-file: tooling
"""Target admission and command shape for the Apple CI lanes (scripts/ci_apple.py)."""

from pathlib import Path

import pytest

from scripts import ci_apple


def test_apple_ui_admits_only_explicit_ui_test_selectors():
    specs = ["OpenMatesUITests/LandingOnboardingParityUITests", "OpenMatesUITests/A/testB"]
    assert ci_apple.validate_specs("apple-ui", specs) == specs
    for refused in (
        [],
        ["all"],
        ["OpenMatesUITests"],
        ["OpenMatesTests/SomeUnitTests"],
        ["OpenMatesUITests/A/testB/extra"],
        ["OpenMatesUITests/A; rm -rf /"],
        ["OpenMatesUITests/A"] * (ci_apple.MAX_UI_SPECS + 1),
    ):
        with pytest.raises(ValueError):
            ci_apple.validate_specs("apple-ui", refused)


def test_apple_unit_never_admits_ui_test_selectors():
    assert ci_apple.validate_specs("apple-unit", ["all"]) == ["all"]
    with pytest.raises(ValueError):
        ci_apple.validate_specs("apple-unit", ["OpenMatesUITests/A"])


def test_apple_ui_plan_runs_exactly_the_selected_tests_serially():
    specs = ["OpenMatesUITests/A", "OpenMatesUITests/B/testC"]
    plan = ci_apple.xcode_plan("apple-ui", Path("/out"), specs)
    command = plan[-1][1]
    selected = [command[i + 1] for i, arg in enumerate(command) if arg == "-only-testing"]
    assert selected == specs
    assert command[command.index("-parallel-testing-enabled") + 1] == "NO"
    assert "/out/OpenMatesUITests.xcresult" in command
    # The UI fixtures seed the core: Rust feature and Swift condition come together in the build.
    build = next(step[1] for step in plan if step[0] == ci_apple.BUILD_STEP)
    assert "OPENMATES_CORE_TEST_SUPPORT=YES" in build
    assert "OTHER_SWIFT_FLAGS=$(inherited) -DOPENMATES_CORE_TEST_SUPPORT" in build


def test_focused_ui_runs_keep_passing_recordings_before_the_tests():
    plan = ci_apple.xcode_plan("apple-ui", Path("/out"), ["OpenMatesUITests/A"])
    names = [step[0] for step in plan]
    keep = names.index(ci_apple.KEEP_RECORDINGS_STEP)
    assert names.index(ci_apple.BUILD_STEP) < keep < len(names) - 1
    assert plan[keep][1][-2:] == ["keep-recordings", "/out/DerivedData/Build/Products"]
    large = ["OpenMatesUITests/A"] * (ci_apple.MAX_RECORDED_UI_SPECS + 1)
    assert ci_apple.KEEP_RECORDINGS_STEP not in [s[0] for s in ci_apple.xcode_plan("apple-ui", Path("/out"), large)]
    unit = [s[0] for s in ci_apple.xcode_plan("apple-unit", Path("/out"), ["all"])]
    assert ci_apple.KEEP_RECORDINGS_STEP not in unit


def test_keep_recordings_writes_a_patched_copy_for_ui_targets_only(tmp_path):
    import plistlib

    run = {
        "TestConfigurations": [{"TestTargets": [
            {"BlueprintName": "OpenMatesUITests", "IsUITestBundle": True, "SystemAttachmentLifetime": "deleteOnSuccess"},
            {"BlueprintName": "OpenMatesTests", "SystemAttachmentLifetime": "deleteOnSuccess"},
        ]}],
        "__xctestrun_metadata__": {"FormatVersion": 2},
    }
    built = tmp_path / "OpenMates_iOS_iphonesimulator26.0-arm64.xctestrun"
    built.write_bytes(plistlib.dumps(run))
    assert ci_apple.keep_recordings(tmp_path) == 1
    assert plistlib.loads(built.read_bytes()) == run  # Xcode's own file is untouched
    copy = plistlib.loads((tmp_path / ci_apple.RECORDED_XCTESTRUN).read_bytes())
    ui, unit = copy["TestConfigurations"][0]["TestTargets"]
    for key in ci_apple.KEEP_ALL_KEYS:
        assert ui[key] == "keepAlways"
    assert ui["PreferredScreenCaptureFormat"] == "screenRecording"
    assert unit["SystemAttachmentLifetime"] == "deleteOnSuccess"
    assert ci_apple.keep_recordings(tmp_path) == 1  # a rerun ignores its own copy
    with pytest.raises(ValueError):
        ci_apple.keep_recordings(tmp_path / "empty")


def test_recorded_runs_test_from_the_patched_xctestrun():
    command = ci_apple.xcode_plan("apple-ui", Path("/out"), ["OpenMatesUITests/A"])[-1][1]
    assert command[command.index("-xctestrun") + 1] == f"/out/DerivedData/Build/Products/{ci_apple.RECORDED_XCTESTRUN}"
    assert "-scheme" not in command and "-project" not in command
    assert command[command.index("-destination") + 1] == f"platform=iOS Simulator,name={ci_apple.SIMULATOR}"
    large = ["OpenMatesUITests/A"] * (ci_apple.MAX_RECORDED_UI_SPECS + 1)
    unrecorded = ci_apple.xcode_plan("apple-ui", Path("/out"), large)[-1][1]
    assert "-xctestrun" not in unrecorded and "-scheme" in unrecorded


def test_apple_unit_plan_selects_only_the_unit_target():
    command = ci_apple.xcode_plan("apple-unit", Path("/out"), ["all"])[-1][1]
    selected = [command[i + 1] for i, arg in enumerate(command) if arg == "-only-testing"]
    assert selected == ["OpenMatesTests"]
    assert "-parallel-testing-enabled" not in command
    assert "/out/OpenMatesTests.xcresult" in command
    assert "ENABLE_USER_SCRIPT_SANDBOXING=NO" in command
    assert "OPENMATES_CORE_TEST_SUPPORT=YES" in command
    assert "OTHER_SWIFT_FLAGS=$(inherited) -DOPENMATES_CORE_TEST_SUPPORT" in command
    assert command[command.index("-test-timeouts-enabled") + 1] == "YES"
    assert command[command.index("-maximum-test-execution-time-allowance") + 1] == "300"


def test_apple_core_plan_builds_core_and_the_watch_as_its_own_late_step():
    plan = ci_apple.core_plan(Path("/src"), Path("/out"))
    names = [name for name, *_ in plan]
    commands = {name: " ".join(cmd) for name, cmd, *_ in plan}
    joined = " ".join(commands.values())
    assert "PairOpaque" not in joined and "swift test" not in joined
    assert commands["openmates-apple-bindings tests (macOS)"].endswith("-p openmates-apple-bindings --locked --no-fail-fast")
    assert "--check-bindings" in commands["apple bindings are fresh"]
    watch = [n for n in names if "WATCH" in n]
    assert len(watch) == 1 and "--watch" in commands[watch[0]]
    assert names.index(watch[0]) > names.index("OpenMatesCore xcframework (iOS, simulator, macOS)")
    assert "--watch" not in commands["OpenMatesCore xcframework (iOS, simulator, macOS)"]
    assert all(not skip for *_, skip in plan)


def test_the_core_lane_never_builds_test_fixtures():
    joined = " ".join(" ".join(cmd) for _, cmd, *_ in ci_apple.core_plan(Path("/src"), Path("/out")))
    assert "test-support" not in joined and "OPENMATES_CORE_TEST_SUPPORT" not in joined


def test_apple_build_plan_compiles_all_targets_and_keeps_going():
    assert ci_apple.validate_specs("apple-build", ["all"]) == ["all"]
    with pytest.raises(ValueError):
        ci_apple.validate_specs("apple-build", ["OpenMatesTests/A"])
    plan = ci_apple.xcode_plan("apple-build", Path("/out"), ["all"])
    name, command, *_ = plan[-2]
    assert name == "xcodebuild build-for-testing"
    assert command[:2] == ["xcodebuild", "build-for-testing"]
    assert "-IDEBuildingContinueBuildingAfterErrors=YES" in command
    assert "-only-testing" not in command and "-test-timeouts-enabled" not in command
    assert "/out/OpenMatesBuild.xcresult" in command
    # Same build inputs as the test lanes, so a green build means the test lanes compile.
    assert "OPENMATES_CORE_TEST_SUPPORT=YES" in command
    assert "OTHER_SWIFT_FLAGS=$(inherited) -DOPENMATES_CORE_TEST_SUPPORT" in command
    # The arm64 runner never builds the x86_64 Watch simulator core (tier-3, about 14 minutes).
    assert "EXCLUDED_ARCHS=x86_64" in command
    # The same job also compiles the macOS app, keeping going after errors as well.
    mac_name, mac, *_ = plan[-1]
    assert mac_name == ci_apple.MACOS_BUILD_STEP
    assert mac[:2] == ["xcodebuild", "build"]
    assert mac[mac.index("-scheme") + 1] == "OpenMates_macOS"
    assert mac[mac.index("-destination") + 1] == "platform=macOS"
    assert "-IDEBuildingContinueBuildingAfterErrors=YES" in mac
    assert "OPENMATES_CORE_TEST_SUPPORT=YES" in mac


@pytest.mark.parametrize(
    "mode,specs", [("apple-unit", ["all"]), ("apple-ui", ["OpenMatesUITests/A"])]
)
def test_test_lanes_build_once_then_test_on_those_products(mode, specs):
    build_only = ci_apple.xcode_plan("apple-build", Path("/out"), ["all"])[-2]
    plan = [s for s in ci_apple.xcode_plan(mode, Path("/out"), specs) if s[0] != ci_apple.KEEP_RECORDINGS_STEP]
    build, test = plan[-2], plan[-1]
    # The compile step is the build lane's, so every test job lists all Swift errors itself.
    assert build[:2] == build_only[:2]
    assert test[1][:2] == ["xcodebuild", "test-without-building"]
    assert "-IDEBuildingContinueBuildingAfterErrors=YES" not in test[1]
    derived = build[1][build[1].index("-derivedDataPath") + 1]
    if "-xctestrun" in test[1]:  # a recorded run uses the products' patched .xctestrun
        assert test[1][test[1].index("-xctestrun") + 1].startswith(f"{derived}/Build/Products/")
    else:
        assert test[1][test[1].index("-derivedDataPath") + 1] == derived
    assert sum(1 for _, command, *_ in plan if command[:2] == ["xcodebuild", "build-for-testing"]) == 1


def test_only_private_startup_uses_the_multi_relaunch_allowance():
    plans = [
        (ci_apple.STARTUP_BENCHMARK_SPECS, True, "600"),
        (ci_apple.MAC_STARTUP_BENCHMARK_SPECS, True, "600"),
        (ci_apple.STARTUP_BENCHMARK_SPECS, False, "300"),
        ({"OpenMatesUITests/A"}, False, "300"),
    ]
    for specs, private, allowance in plans:
        command = ci_apple.xcode_plan("apple-ui", Path("/out"), sorted(specs), benchmark=private)[-1][1]
        for flag in ("default", "maximum"):
            option = f"-{flag}-test-execution-time-allowance"
            assert command[command.index(option) + 1] == allowance


def test_private_mac_startup_uses_hosted_macos_and_preserves_recordings():
    specs = sorted(ci_apple.MAC_STARTUP_BENCHMARK_SPECS)
    assert ci_apple.validate_specs("apple-ui", specs) == specs
    plan = ci_apple.xcode_plan("apple-ui", Path("/out"), specs, benchmark=True)
    build = next(command for name, command, *_ in plan if name == ci_apple.BUILD_STEP)
    assert build[build.index("-scheme") + 1] == "OpenMates_macOS"
    assert build[build.index("-destination") + 1] == "platform=macOS"
    assert "CODE_SIGNING_ALLOWED=YES" in build
    assert build[build.index("-configuration") + 1] == "Debug"
    names = [name for name, *_ in plan]
    signing = names.index(ci_apple.SIGN_MAC_STARTUP_STEP)
    assert names.index(ci_apple.BUILD_STEP) < signing < names.index(ci_apple.KEEP_RECORDINGS_STEP)
    assert plan[signing][1][-2:] == [
        "sign-macos-startup", "/out/DerivedData/Build/Products/Debug/OpenMates.app",
    ]
    ios = ci_apple.xcode_plan("apple-ui", Path("/out"), sorted(ci_apple.STARTUP_BENCHMARK_SPECS), benchmark=True)
    release_build = ci_apple.xcode_plan("apple-build", Path("/out"), ["all"])
    assert all(name != ci_apple.SIGN_MAC_STARTUP_STEP for name, *_ in ios + release_build)
    test = plan[-1][1]
    assert test[test.index("-destination") + 1] == "platform=macOS"
    assert {test[index + 1] for index, field in enumerate(test) if field == "-only-testing"} == set(specs)


def test_private_mac_signing_replaces_profile_bound_app_signature(tmp_path, monkeypatch):
    import plistlib
    import subprocess

    root = Path(__file__).resolve().parents[2]
    app = tmp_path / "OpenMates.app"
    contents = app / "Contents"
    extension = contents / "PlugIns" / "Share.appex"
    extension.mkdir(parents=True)
    plist = contents / "Info.plist"
    plist.write_bytes(plistlib.dumps({
        "CFBundleIdentifier": "org.openmates.app",
        "OpenMatesKeychainAccessGroup": "TEAM.example.keychain",
    }))
    calls = []
    monkeypatch.setattr(subprocess, "run", lambda arguments, *, check: calls.append((arguments, check)))

    ci_apple.sign_macos_startup_app(root, app)

    assert plistlib.loads(plist.read_bytes()) == {"CFBundleIdentifier": "org.openmates.app"}
    assert [Path(arguments[-1]) for arguments, _ in calls] == [extension, app, app]
    for arguments, check in calls[:2]:
        assert check and arguments[:5] == ["codesign", "--force", "--sign", "-", "--entitlements"]
        entitlements = plistlib.loads(Path(arguments[5]).read_bytes())
        assert "com.apple.security.application-groups" not in entitlements
        assert "keychain-access-groups" not in entitlements
        assert "com.apple.developer.associated-domains" not in entitlements
    assert calls[-1] == (["codesign", "--verify", "--deep", "--strict", str(app)], True)


@pytest.mark.parametrize("restricted", [
    "keychain-access-groups",
    "com.apple.security.application-groups",
    "com.apple.developer.associated-domains",
])
def test_private_mac_signing_rejects_entitlements_from_a_profile_bound_build(tmp_path, restricted):
    import plistlib

    app_entitlements = tmp_path / "apple/OpenMates/Resources/OpenMatesMacOSPersonalTeam.entitlements"
    app_entitlements.parent.mkdir(parents=True)
    app_entitlements.write_bytes(plistlib.dumps({restricted: ["TEAM.example.group"]}))

    # Fail before any codesign call or mutation of the built app. The hosted
    # app was rejected by taskgated when ad-hoc signed with its normal settings.
    with pytest.raises(ValueError, match="requires unrestricted entitlements"):
        ci_apple.sign_macos_startup_app(tmp_path, tmp_path / "OpenMates.app")


def test_mac_startup_rejects_unencrypted_execution_and_mixed_platforms(monkeypatch, tmp_path):
    monkeypatch.delenv("CI_APPLE_PRIVATE_STARTUP", raising=False)
    specs = sorted(ci_apple.MAC_STARTUP_BENCHMARK_SPECS)
    with pytest.raises(ValueError, match="requires private evidence"):
        ci_apple.run(tmp_path, [], "apple-ui", specs)
    for refused in (specs[:1], [specs[0], sorted(ci_apple.STARTUP_BENCHMARK_SPECS)[1]]):
        with pytest.raises(ValueError, match="apple-ui targets"):
            ci_apple.validate_specs("apple-ui", refused)


def test_swift_errors_are_unique_relative_and_complete():
    log = [
        "/w/subject/apple/A.swift:3:5: error: cannot find 'x' in scope",
        "    let y = x",
        "/w/subject/apple/A.swift:3:5: error: cannot find 'x' in scope",
        "/w/subject/apple/B.swift:10:1: warning: unused",
        "/w/subject/apple/Tests/C.swift:7:9: error: missing argument",
    ]
    assert ci_apple.swift_errors(log, Path("/w/subject")) == [
        "apple/A.swift:3:5: error: cannot find 'x' in scope",
        "apple/Tests/C.swift:7:9: error: missing argument",
    ]


def test_apple_build_compiles_macos_even_when_the_ios_build_fails(tmp_path, monkeypatch):
    import sys
    import types

    rows: list[dict] = []
    logs = {
        ci_apple.BUILD_STEP: f"{tmp_path}/apple/A.swift:1:2: error: ios only\n",
        ci_apple.MACOS_BUILD_STEP: f"{tmp_path}/apple/B.swift:3:4: error: mac only\n",
    }
    fake = types.ModuleType("ci_rust_checks")
    fake.slug = lambda name: name.replace(" ", "-")

    def run(name, command, *, blocking, cwd):
        code = 65 if name in logs else 0
        if name in logs:
            log = tmp_path / "test-results" / "apple-build" / "rows" / f"{fake.slug(name)}.log"
            log.parent.mkdir(parents=True, exist_ok=True)
            log.write_text(logs[name])
        rows.append({"excerpt": [], "seconds": 1, "diagnostics": 0})
        return code

    fake.run = run
    fake.load_rows = lambda: rows
    monkeypatch.setitem(sys.modules, "ci_rust_checks", fake)
    results: list[dict] = []
    ci_apple.run(tmp_path, results, "apple-build", ["all"])
    names = [row["suite"] for row in results]
    assert names[-2:] == [f"apple-build:{ci_apple.BUILD_STEP}", f"apple-build:{ci_apple.MACOS_BUILD_STEP}"]
    assert results[-2]["failures"] == ["apple/A.swift:1:2: error: ios only"]
    assert results[-1]["failures"] == ["apple/B.swift:3:4: error: mac only"]
    errors = (tmp_path / "test-results" / "apple-build" / "swift-errors.txt").read_text().splitlines()
    assert errors == ["apple/A.swift:1:2: error: ios only", "apple/B.swift:3:4: error: mac only"]


def test_only_private_startup_builds_with_the_release_optimizer():
    for specs in (sorted(ci_apple.STARTUP_BENCHMARK_SPECS), sorted(ci_apple.MAC_STARTUP_BENCHMARK_SPECS)):
        build = ci_apple.xcode_plan("apple-ui", Path("/out"), specs, benchmark=True)[2][1]
        assert all(setting in build for setting in ci_apple.OPTIMIZED_BENCHMARK_SETTINGS)
    ordinary = ci_apple.xcode_plan("apple-ui", Path("/out"), ["OpenMatesUITests/A/testB"])[2][1]
    assert not any(setting in ordinary for setting in ci_apple.OPTIMIZED_BENCHMARK_SETTINGS)


def test_profiler_traces_only_the_first_cached_relaunch(tmp_path, monkeypatch):
    import json
    import subprocess

    pids = iter(["11", "11", "22", "33"])
    commands: list[list[str]] = []

    class Stop:
        def wait(self, _seconds):
            return False

    def fake_run(command, **_kwargs):
        if command[0] == "pgrep":
            return subprocess.CompletedProcess(command, 0, stdout=next(pids) + "\n")
        if command[0] == "ps":
            return subprocess.CompletedProcess(
                command, 0, stdout="/Users/x/Library/Developer/CoreSimulator/Devices/D/OpenMates.app/OpenMates -x\n")
        if command[:3] == ["xcrun", "simctl", "list"]:
            return subprocess.CompletedProcess(command, 0, stdout=json.dumps(
                {"devices": {"ios": [{"udid": "SIM-1", "state": "Booted"}, {"udid": "SIM-2", "state": "Shutdown"}]}}))
        commands.append(command)
        return subprocess.CompletedProcess(command, 0, stderr="")

    monkeypatch.setattr(subprocess, "run", fake_run)
    ci_apple.sample_app_process(tmp_path / "samples", Stop())
    assert [command[2] for command in commands] == ["record", "export", "export"]
    assert commands[0][commands[0].index("--attach") + 1] == "22"
    assert commands[0][commands[0].index("--device") + 1] == "SIM-1"
    assert (tmp_path / "samples" / "sampler.log").read_text().count("exit 0") == 3
