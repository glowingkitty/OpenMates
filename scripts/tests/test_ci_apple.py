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
    # The UI fixtures seed the core: Rust feature and Swift condition come together.
    assert "OPENMATES_CORE_TEST_SUPPORT=YES" in command
    assert "OTHER_SWIFT_FLAGS=$(inherited) -DOPENMATES_CORE_TEST_SUPPORT" in command


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
    assert commands["openmates-apple-bindings tests (macOS)"].endswith("-p openmates-apple-bindings --locked")
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
    plan = ci_apple.xcode_plan(mode, Path("/out"), specs)
    build, test = plan[-2], plan[-1]
    # The compile step is the build lane's, so every test job lists all Swift errors itself.
    assert build[:2] == build_only[:2]
    assert test[1][:2] == ["xcodebuild", "test-without-building"]
    assert "-IDEBuildingContinueBuildingAfterErrors=YES" not in test[1]
    derived = build[1][build[1].index("-derivedDataPath") + 1]
    assert test[1][test[1].index("-derivedDataPath") + 1] == derived
    assert sum(1 for _, command, *_ in plan if command[:2] == ["xcodebuild", "build-for-testing"]) == 1


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
