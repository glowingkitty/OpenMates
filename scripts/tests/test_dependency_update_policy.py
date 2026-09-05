"""Validate the repository's dependency update policy.

The policy separates urgent advisory remediation from quarantined routine
updates and keeps pull requests small enough to review and diagnose. It covers
every package ecosystem that can change executable OpenMates build inputs.
"""

from datetime import date, timedelta
import fcntl
import os
from pathlib import Path
import shutil
import subprocess

import yaml


ROOT = Path(__file__).resolve().parents[2]
DEPENDABOT_CONFIG = ROOT / ".github" / "dependabot.yml"
DEPENDENCY_SECURITY_WORKFLOW = ROOT / ".github" / "workflows" / "dependency-security.yml"
TRIVY_IGNORE = ROOT / ".trivyignore.yaml"
DEPENDENCY_SECURITY_SCRIPTS = (
    ROOT / "scripts" / "check-dependabot-daily.sh",
    ROOT / "scripts" / "check-eu-vulns-daily.sh",
)
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


# contract-test: infrastructure
def test_security_workflow_runs_for_dev_pushes() -> None:
    workflow = DEPENDENCY_SECURITY_WORKFLOW.read_text(encoding="utf-8")

    assert "  push:\n    branches: [dev]" in workflow


# contract-test: infrastructure
def test_host_scanners_do_not_import_the_complete_secret_environment() -> None:
    for script in DEPENDENCY_SECURITY_SCRIPTS:
        contents = script.read_text(encoding="utf-8")
        assert 'source "$PROJECT_ROOT/.env"' not in contents


# contract-test: infrastructure
def test_dependabot_runtime_state_does_not_dirty_the_source_tree() -> None:
    scanner = (ROOT / "scripts" / "check-dependabot-daily.sh").read_text(encoding="utf-8")

    assert 'TRACKING_SEED="$SCRIPT_DIR/dependabot-processed.json"' in scanner
    assert 'TRACKING_FILE="$PROJECT_ROOT/logs/dependabot-processed.json"' in scanner
    assert 'export TRACKING_FILE_PATH="$TRACKING_FILE"' in scanner


def _copied_dependabot_scanner(tmp_path: Path) -> tuple[Path, Path]:
    script_dir = tmp_path / "scripts"
    script_dir.mkdir()
    for name in ("check-dependabot-daily.sh", "dependabot-processed.json", "_nightly_report.py"):
        shutil.copy2(ROOT / "scripts" / name, script_dir / name)
    return script_dir / "check-dependabot-daily.sh", script_dir / "dependabot-processed.json"


def _fake_gh_environment(tmp_path: Path) -> dict[str, str]:
    fake_bin = tmp_path / "bin"
    fake_bin.mkdir()
    fake_gh = fake_bin / "gh"
    fake_gh.write_text(
        "#!/usr/bin/env bash\n"
        "if [[ $1 == auth ]]; then exit 0; fi\n"
        "if [[ $1 == api ]]; then printf '[]'; exit 0; fi\n"
        "exit 1\n",
        encoding="utf-8",
    )
    fake_gh.chmod(0o755)
    return {**os.environ, "GITHUB_REPO": "example/openmates", "PATH": f"{fake_bin}:{os.environ['PATH']}"}


def _run_zero_alert_scanner(script: Path, environment: dict[str, str], *args: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        ["bash", str(script), *args],
        cwd=script.parent.parent,
        env=environment,
        text=True,
        capture_output=True,
        check=False,
    )


def _copied_eu_scanner(tmp_path: Path) -> Path:
    script_dir = tmp_path / "scripts"
    script_dir.mkdir()
    for name in ("check-eu-vulns-daily.sh", "dependabot-processed.json"):
        shutil.copy2(ROOT / "scripts" / name, script_dir / name)
    return script_dir / "check-eu-vulns-daily.sh"


def _fake_python_environment(tmp_path: Path) -> dict[str, str]:
    fake_bin = tmp_path / "bin"
    fake_bin.mkdir()
    fake_python = fake_bin / "python3"
    fake_python.write_text("#!/usr/bin/env bash\nexit 0\n", encoding="utf-8")
    fake_python.chmod(0o755)
    return {**os.environ, "PATH": f"{fake_bin}:{os.environ['PATH']}"}


def _run_eu_scanner(script: Path, environment: dict[str, str], *args: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        ["bash", str(script), *args],
        cwd=script.parent.parent,
        env=environment,
        text=True,
        capture_output=True,
        check=False,
    )


# contract-test: infrastructure
def test_dependabot_zero_alert_real_run_initializes_only_runtime_state(tmp_path: Path) -> None:
    script, seed = _copied_dependabot_scanner(tmp_path)
    seed_before = seed.read_bytes()

    result = _run_zero_alert_scanner(script, _fake_gh_environment(tmp_path))

    tracking = tmp_path / "logs" / "dependabot-processed.json"
    assert result.returncode == 0, result.stderr
    assert "No open Dependabot alerts" in result.stdout
    assert tracking.is_file()
    assert seed.read_bytes() == seed_before


# contract-test: infrastructure
def test_dependabot_zero_alert_dry_run_without_runtime_state_is_nonpersistent(tmp_path: Path) -> None:
    script, seed = _copied_dependabot_scanner(tmp_path)
    seed_before = seed.read_bytes()

    result = _run_zero_alert_scanner(script, _fake_gh_environment(tmp_path), "--dry-run")

    assert result.returncode == 0, result.stderr
    assert "No open Dependabot alerts" in result.stdout
    assert seed.read_bytes() == seed_before
    assert not (tmp_path / "logs").exists()


# contract-test: infrastructure
def test_dependabot_zero_alert_dry_run_preserves_runtime_state(tmp_path: Path) -> None:
    script, _ = _copied_dependabot_scanner(tmp_path)
    tracking = tmp_path / "logs" / "dependabot-processed.json"
    tracking.parent.mkdir()
    tracking.write_text('{"last_run":"before","processed":[]}\n', encoding="utf-8")
    tracking_before = tracking.read_bytes()

    result = _run_zero_alert_scanner(script, _fake_gh_environment(tmp_path), "--dry-run")

    assert result.returncode == 0, result.stderr
    assert tracking.read_bytes() == tracking_before


# contract-test: infrastructure
def test_dependabot_lock_contention_skips_before_runtime_initialization(tmp_path: Path) -> None:
    script, _ = _copied_dependabot_scanner(tmp_path)
    lock = tmp_path / "logs" / "dependabot-scanner.lock"
    lock.parent.mkdir()
    with lock.open("w") as lock_handle:
        fcntl.flock(lock_handle, fcntl.LOCK_EX | fcntl.LOCK_NB)
        result = _run_zero_alert_scanner(script, _fake_gh_environment(tmp_path))

    assert result.returncode == 0, result.stderr
    assert "Another instance is already running" in result.stdout
    assert not (tmp_path / "logs" / "dependabot-processed.json").exists()


# contract-test: infrastructure
def test_eu_dry_run_and_summary_do_not_create_runtime_logs(tmp_path: Path) -> None:
    script = _copied_eu_scanner(tmp_path)
    environment = _fake_python_environment(tmp_path)

    dry_run = _run_eu_scanner(script, environment, "--dry-run")
    summary = _run_eu_scanner(script, environment, "--summary")

    assert dry_run.returncode == 0, dry_run.stderr
    assert summary.returncode == 0, summary.stderr
    assert not (tmp_path / "logs").exists()


# contract-test: infrastructure
def test_container_policy_enforces_findings_with_bounded_path_exceptions() -> None:
    workflow = DEPENDENCY_SECURITY_WORKFLOW.read_text(encoding="utf-8")
    config = yaml.safe_load(TRIVY_IGNORE.read_text(encoding="utf-8"))
    exceptions = config["misconfigurations"]

    assert 'exit-code: "1"' in workflow
    assert "trivyignores: .trivyignore.yaml" in workflow
    assert len(exceptions) == 1
    assert exceptions[0]["id"] == "AVD-DS-0002"
    assert exceptions[0]["statement"]
    assert date.today() <= exceptions[0]["expired_at"] <= date.today() + timedelta(days=31)
    assert all((ROOT / path).is_file() for path in exceptions[0]["paths"])
