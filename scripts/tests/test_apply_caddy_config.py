#!/usr/bin/env python3
"""
Regression tests for fail-closed Caddy config application.

These tests exercise deployment/apply-caddy-config.sh in a temp sandbox with
fake caddy/systemctl binaries. They prevent config validation overrides or
reload failures from taking Caddy down again.
"""

from __future__ import annotations

import os
import subprocess
from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parents[2]
APPLY_SCRIPT = PROJECT_ROOT / "deployment" / "apply-caddy-config.sh"


def write_executable(path: Path, content: str) -> None:
    path.write_text(content, encoding="utf-8")
    path.chmod(0o755)


def run_apply(source: Path, system_caddyfile: Path, fakebin: Path, extra_env: dict[str, str] | None = None):
    env = os.environ.copy()
    env.update({
        "OPENMATES_CADDY_APPLY_TEST": "1",
        "OPENMATES_SYSTEM_CADDYFILE": str(system_caddyfile),
        "PATH": f"{fakebin}:{env['PATH']}",
    })
    if extra_env:
        env.update(extra_env)

    return subprocess.run(
        ["bash", str(APPLY_SCRIPT), str(source)],
        cwd=PROJECT_ROOT,
        env=env,
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        check=False,
    )


def prepare_fakebin(tmp_path: Path, *, adapt_fails: bool = False, restart_fails_once: bool = False) -> Path:
    fakebin = tmp_path / "fakebin"
    fakebin.mkdir()
    adapt_action = 'echo "module not registered: dns.providers.gandi" >&2; exit 1' if adapt_fails else 'echo "{}"; exit 0'

    write_executable(
        fakebin / "caddy",
        f"""#!/bin/bash
if [ "$1" = "adapt" ]; then
  {adapt_action}
fi
if [ "$1" = "validate" ]; then
  echo "adapted config to JSON"
  exit 0
fi
exit 1
""",
    )
    write_executable(fakebin / "chown", "#!/bin/bash\nexit 0\n")
    write_executable(fakebin / "chmod", "#!/bin/bash\nexit 0\n")

    state_file = tmp_path / "restart-count"
    write_executable(
        fakebin / "systemctl",
        f"""#!/bin/bash
case "$1" in
  is-active)
    exit 1
    ;;
  show)
    echo "ActiveState=failed"
    exit 0
    ;;
  restart)
    count=0
    if [ -f "{state_file}" ]; then
      count=$(cat "{state_file}")
    fi
    count=$((count + 1))
    echo "$count" > "{state_file}"
    if [ "{str(restart_fails_once).lower()}" = "true" ] && [ "$count" = "1" ]; then
      exit 1
    fi
    exit 0
    ;;
  reload)
    exit 0
    ;;
  status)
    echo "fake caddy status"
    exit 0
    ;;
esac
exit 0
""",
    )
    return fakebin


def test_apply_caddy_config_stops_before_copy_when_caddy_adapt_fails(tmp_path: Path):
    source = tmp_path / "candidate.Caddyfile"
    source.write_text("bad config with unsupported dns module\n", encoding="utf-8")
    system_caddyfile = tmp_path / "system.Caddyfile"
    system_caddyfile.write_text("previous working config\n", encoding="utf-8")
    fakebin = prepare_fakebin(tmp_path, adapt_fails=True)

    result = run_apply(source, system_caddyfile, fakebin)

    assert result.returncode == 1
    assert "Caddyfile adaptation failed" in result.stdout
    assert "Nothing was copied" in result.stdout
    assert system_caddyfile.read_text(encoding="utf-8") == "previous working config\n"


def test_apply_caddy_config_restores_previous_file_when_restart_fails(tmp_path: Path):
    source = tmp_path / "candidate.Caddyfile"
    source.write_text("new valid config\n", encoding="utf-8")
    system_caddyfile = tmp_path / "system.Caddyfile"
    system_caddyfile.write_text("previous working config\n", encoding="utf-8")
    fakebin = prepare_fakebin(tmp_path, restart_fails_once=True)

    result = run_apply(source, system_caddyfile, fakebin)

    assert result.returncode == 1
    assert "Failed to restart Caddy" in result.stdout
    assert "Previous Caddy configuration restored" in result.stdout
    assert system_caddyfile.read_text(encoding="utf-8") == "previous working config\n"


def test_check_mode_runs_without_root_and_does_not_copy_or_reload(tmp_path: Path):
    source = tmp_path / "candidate.Caddyfile"
    source.write_text("new valid config\n", encoding="utf-8")
    system_caddyfile = tmp_path / "system.Caddyfile"
    system_caddyfile.write_text("previous working config\n", encoding="utf-8")
    fakebin = prepare_fakebin(tmp_path)
    env = os.environ.copy()
    env.update({
        "OPENMATES_SYSTEM_CADDYFILE": str(system_caddyfile),
        "PATH": f"{fakebin}:{env['PATH']}",
    })

    result = subprocess.run(
        ["bash", str(APPLY_SCRIPT), "--check", str(source)],
        cwd=PROJECT_ROOT,
        env=env,
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        check=False,
    )

    assert result.returncode == 0
    assert "check passed" in result.stdout
    assert "Skipping caddy validate in non-root check mode" in result.stdout
    assert system_caddyfile.read_text(encoding="utf-8") == "previous working config\n"
    assert not (tmp_path / "restart-count").exists()
    assert "/tmp/openmates-caddy-adapted.json" not in APPLY_SCRIPT.read_text(encoding="utf-8")
