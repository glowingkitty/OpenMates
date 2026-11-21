"""Tests for deployment/os_maintenance (render per role, reboot decision logic)."""

# contract-test-file: infrastructure
import subprocess
from pathlib import Path

import pytest

DIR = Path(__file__).resolve().parents[2] / "deployment" / "os_maintenance"
INSTALL = DIR / "install.sh"
REBOOT = DIR / "openmates-reboot-if-required"
BASE_ENV = {"PATH": "/usr/bin:/bin"}


def sh(*args, env=None):
    return subprocess.run(["sh", *map(str, args)], capture_output=True, text=True, env=env)


# Spec coverage: security-monitoring.os.reboot-windows
# contract-test: infrastructure
@pytest.mark.parametrize("script", [INSTALL, REBOOT])
def test_syntax(script):
    assert sh("-n", script).returncode == 0


@pytest.mark.parametrize("role,expected", [
    ("core", "OnCalendar=Sun *-*-* 04:30:00 Europe/Berlin"),
    ("upload", "OnCalendar=*-*-* 03:45:00 Europe/Berlin"),
    ("preview", "OnCalendar=*-*-* 03:30:00 Europe/Berlin"),
    ("dev", "OnCalendar=*-*-* 04,05:00,15,30,45:00 Europe/Berlin"),
])
# Spec coverage: security-monitoring.os.reboot-windows
# contract-test: infrastructure
def test_role_calendar(tmp_path, role, expected):
    env = {**BASE_ENV, "OPENMATES_OS_ROOT": str(tmp_path)}
    r = sh(INSTALL, "--role", role, env=env)
    assert r.returncode == 0, r.stderr
    timer = (tmp_path / "etc/systemd/system/openmates-reboot.timer").read_text()
    assert expected in timer and "Persistent=false" in timer
    if role == "dev":
        assert "OnCalendar=*-*-* 06:00:00 Europe/Berlin" in timer
    apt = (tmp_path / "etc/apt/apt.conf.d/52openmates-unattended-upgrades").read_text()
    assert 'Automatic-Reboot "false"' in apt and "-security" in apt
    assert (tmp_path / "etc/openmates/os-maintenance.conf").read_text() == f"ROLE={role}\n"


# Spec coverage: security-monitoring.os.reboot-windows
# contract-test: infrastructure
def test_bad_role_and_uninstall(tmp_path):
    env = {**BASE_ENV, "OPENMATES_OS_ROOT": str(tmp_path)}
    assert sh(INSTALL, "--role", "nope", env=env).returncode == 2
    assert sh(INSTALL, "--role", "core", env=env).returncode == 0
    assert sh(INSTALL, "--role", "core", env=env).returncode == 0  # idempotent
    assert sh(INSTALL, "uninstall", env=env).returncode == 0
    assert not (tmp_path / "etc/systemd/system/openmates-reboot.timer").exists()


def decide(tmp_path, role, *, required=True, procs="", hold=None, flag="--dry-run"):
    (tmp_path / "var/run").mkdir(parents=True, exist_ok=True)
    if required:
        (tmp_path / "var/run/reboot-required").write_text("*** reboot ***\n")
        (tmp_path / "var/run/reboot-required.pkgs").write_text("linux-image-x\n")
    if hold:
        p = tmp_path / hold
        p.parent.mkdir(parents=True, exist_ok=True)
        p.touch()
    (tmp_path / "procs").write_text(procs)
    env = {**BASE_ENV, "OPENMATES_REBOOT_ROOT": str(tmp_path), "OPENMATES_REBOOT_ROLE": role,
           "OPENMATES_REBOOT_PROCLIST": str(tmp_path / "procs")}
    r = sh(REBOOT, flag, env=env)
    assert r.returncode == 0, r.stderr
    return r.stdout


# Spec coverage: security-monitoring.os.reboot-windows
# contract-test: infrastructure
def test_no_reboot_required(tmp_path):
    assert "no reboot required" in decide(tmp_path, "core", required=False)


# Spec coverage: security-monitoring.os.reboot-windows
# contract-test: infrastructure
def test_core_ignores_test_processes(tmp_path):
    assert "WOULD REBOOT" in decide(tmp_path, "core", procs="pytest -q\n")


# Spec coverage: security-monitoring.os.reboot-windows
# contract-test: infrastructure
def test_dev_defers_for_tests(tmp_path):
    assert "deferred: test work" in decide(tmp_path, "dev", procs="node vitest run\n")


# Spec coverage: security-monitoring.os.reboot-windows
# contract-test: infrastructure
@pytest.mark.parametrize("hold", ["run/openmates-no-reboot", "home/superdev/.openmates/no-reboot"])
def test_dev_hold_files(tmp_path, hold):
    assert "deferred: hold" in decide(tmp_path, "dev", hold=hold)


# Spec coverage: security-monitoring.os.reboot-windows
# contract-test: infrastructure
def test_dev_idle_reboots(tmp_path):
    out = decide(tmp_path, "dev", procs="bash\n")
    assert "WOULD REBOOT" in out and "linux-image-x" in out


# Spec coverage: security-monitoring.os.reboot-windows
# contract-test: infrastructure
def test_now_skips_busy_check_and_logs(tmp_path):
    out = decide(tmp_path, "dev", procs="pytest\n", flag="--now")
    assert "rebooting" in out
    assert "linux-image-x" in (tmp_path / "var/log/openmates-reboot.log").read_text()


# Spec coverage: security-monitoring.os.reboot-windows
# contract-test: infrastructure
def test_status(tmp_path):
    assert "reboot_required=yes" in decide(tmp_path, "dev", flag="--status")
