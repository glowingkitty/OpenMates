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
