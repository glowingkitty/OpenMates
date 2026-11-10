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


def test_apple_unit_plan_selects_only_the_unit_target():
    command = ci_apple.xcode_plan("apple-unit", Path("/out"), ["all"])[-1][1]
    selected = [command[i + 1] for i, arg in enumerate(command) if arg == "-only-testing"]
    assert selected == ["OpenMatesTests"]
    assert "-parallel-testing-enabled" not in command
    assert "/out/OpenMatesTests.xcresult" in command
    assert "ENABLE_USER_SCRIPT_SANDBOXING=NO" in command
