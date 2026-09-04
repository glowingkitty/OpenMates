"""Validate the repository's dependency update policy.

The policy separates urgent advisory remediation from quarantined routine
updates and keeps pull requests small enough to review and diagnose. It covers
every package ecosystem that can change executable OpenMates build inputs.
"""

from pathlib import Path

import yaml


ROOT = Path(__file__).resolve().parents[2]
DEPENDABOT_CONFIG = ROOT / ".github" / "dependabot.yml"
REQUIRED_ECOSYSTEMS = {"npm", "pip", "docker", "github-actions"}
MINIMUM_ROUTINE_COOLDOWN_DAYS = 14
MINIMUM_MAJOR_COOLDOWN_DAYS = 30


def _updates() -> list[dict]:
    config = yaml.safe_load(DEPENDABOT_CONFIG.read_text(encoding="utf-8"))
    return config["updates"]


# contract-test: infrastructure
def test_all_executable_dependency_ecosystems_are_covered() -> None:
    assert {entry["package-ecosystem"] for entry in _updates()} == REQUIRED_ECOSYSTEMS


# contract-test: infrastructure
def test_every_python_requirements_directory_is_covered() -> None:
    pip = next(entry for entry in _updates() if entry["package-ecosystem"] == "pip")
    configured_directories = set(pip["directories"])
    required_directories = {
        f"/{path.parent.relative_to(ROOT)}"
        for path in ROOT.glob("**/requirements*.txt")
        if "node_modules" not in path.parts
    }

    assert configured_directories == required_directories


# contract-test: infrastructure
def test_routine_updates_wait_and_major_updates_require_longer_review() -> None:
    for entry in _updates():
        cooldown = entry["cooldown"]
        assert cooldown["default-days"] >= MINIMUM_ROUTINE_COOLDOWN_DAYS
        assert cooldown["semver-minor-days"] >= MINIMUM_ROUTINE_COOLDOWN_DAYS
        assert cooldown["semver-patch-days"] >= MINIMUM_ROUTINE_COOLDOWN_DAYS
        assert cooldown["semver-major-days"] >= MINIMUM_MAJOR_COOLDOWN_DAYS


# contract-test: infrastructure
def test_npm_groups_are_bounded_and_never_match_every_package() -> None:
    npm = next(entry for entry in _updates() if entry["package-ecosystem"] == "npm")
    groups = npm.get("groups", {})

    assert groups
    for group in groups.values():
        assert "*" not in group.get("patterns", [])
        assert "major" not in group.get("update-types", [])


# contract-test: infrastructure
def test_no_update_group_can_automerge_major_releases() -> None:
    for entry in _updates():
        for group in entry.get("groups", {}).values():
            if group.get("applies-to", "version-updates") != "version-updates":
                continue
            assert "major" not in group.get("update-types", [])
