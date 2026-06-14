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


def run_apply(
    source: Path,
    system_caddyfile: Path,
    fakebin: Path,
    extra_env: dict[str, str] | None = None,
    input_text: str | None = None,
):
    service_env_file = system_caddyfile.parent / "openmates-gandi.env"
    service_dropin = system_caddyfile.parent / "caddy.service.d" / "openmates-gandi-token.conf"
    env = os.environ.copy()
    env.update({
        "OPENMATES_CADDY_APPLY_TEST": "1",
        "OPENMATES_SYSTEM_CADDYFILE": str(system_caddyfile),
        "OPENMATES_CADDY_SERVICE_ENV_FILE": str(service_env_file),
        "OPENMATES_CADDY_SERVICE_DROPIN": str(service_dropin),
        "PATH": f"{fakebin}:{env['PATH']}",
    })
    if extra_env:
        env.update(extra_env)

    return subprocess.run(
        ["bash", str(APPLY_SCRIPT), str(source)],
        cwd=PROJECT_ROOT,
        env=env,
        text=True,
        input=input_text,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        check=False,
    )


def prepare_fakebin(
    tmp_path: Path,
    *,
    adapt_fails: bool = False,
    restart_fails_once: bool = False,
    has_gandi_module: bool = False,
    with_fake_go: bool = False,
) -> Path:
    fakebin = tmp_path / "fakebin"
    fakebin.mkdir()
    adapt_action = 'echo "module not registered: dns.providers.gandi" >&2; exit 1' if adapt_fails else 'echo "{}"; exit 0'
    modules_action = 'echo "dns.providers.gandi"; exit 0' if has_gandi_module else 'exit 0'

    write_executable(
        fakebin / "caddy",
        f"""#!/bin/bash
if [ "$1" = "version" ]; then
  echo "v2.8.4 h1:fake"
  exit 0
fi
if [ "$1" = "list-modules" ]; then
  {modules_action}
fi
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
    if with_fake_go:
        write_executable(
            fakebin / "go",
            """#!/bin/bash
set -e
if [ "$1" = "install" ]; then
  mkdir -p "$GOBIN"
  cat > "$GOBIN/xcaddy" <<'EOF'
#!/bin/bash
set -e
output=""
while [ "$#" -gt 0 ]; do
  if [ "$1" = "--output" ]; then
    shift
    output="$1"
  fi
  shift || true
done
cat > "$output" <<'EOF_CADDY'
#!/bin/bash
if [ "$1" = "version" ]; then
  echo "v2.8.4 h1:fake"
  exit 0
fi
if [ "$1" = "list-modules" ]; then
  echo "dns.providers.gandi"
  exit 0
fi
if [ "$1" = "adapt" ]; then
  echo "{}"
  exit 0
fi
if [ "$1" = "validate" ]; then
  echo "adapted config to JSON"
  exit 0
fi
exit 1
EOF_CADDY
/bin/chmod +x "$output"
EOF
  /bin/chmod +x "$GOBIN/xcaddy"
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
    if [ -f "{state_file}" ]; then
      exit 0
    fi
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


def test_gandi_dns_config_prompts_and_stores_token_when_missing(tmp_path: Path):
    source = tmp_path / "candidate.Caddyfile"
    source.write_text("*.example.test {\n  tls {\n    dns gandi {env.GANDI_BEARER_TOKEN}\n  }\n}\n", encoding="utf-8")
    system_caddyfile = tmp_path / "system.Caddyfile"
    system_caddyfile.write_text("previous working config\n", encoding="utf-8")
    fakebin = prepare_fakebin(tmp_path, has_gandi_module=True)
    service_env_file = tmp_path / "openmates-gandi.env"
    service_dropin = tmp_path / "caddy.service.d" / "openmates-gandi-token.conf"

    result = run_apply(source, system_caddyfile, fakebin, extra_env={"GANDI_BEARER_TOKEN": ""}, input_text="prompt-token\n")

    assert result.returncode == 0
    assert "Enter the Gandi bearer token" in result.stdout
    assert "Stored Gandi token for the Caddy service" in result.stdout
    assert service_env_file.read_text(encoding="utf-8") == "GANDI_BEARER_TOKEN=prompt-token\n"
    assert service_dropin.read_text(encoding="utf-8") == f"[Service]\nEnvironmentFile={service_env_file}\n"
    assert system_caddyfile.read_text(encoding="utf-8") == source.read_text(encoding="utf-8")


def test_gandi_dns_config_uses_existing_service_token_without_prompt(tmp_path: Path):
    source = tmp_path / "candidate.Caddyfile"
    source.write_text("*.example.test {\n  tls {\n    dns gandi {env.GANDI_BEARER_TOKEN}\n  }\n}\n", encoding="utf-8")
    system_caddyfile = tmp_path / "system.Caddyfile"
    system_caddyfile.write_text("previous working config\n", encoding="utf-8")
    service_env_file = tmp_path / "openmates-gandi.env"
    service_env_file.write_text("GANDI_BEARER_TOKEN=existing-token\n", encoding="utf-8")
    fakebin = prepare_fakebin(tmp_path, has_gandi_module=True)

    result = run_apply(source, system_caddyfile, fakebin, extra_env={"GANDI_BEARER_TOKEN": ""})

    assert result.returncode == 0
    assert "already has a Gandi token configured" in result.stdout
    assert "Enter the Gandi bearer token" not in result.stdout
    assert service_env_file.read_text(encoding="utf-8") == "GANDI_BEARER_TOKEN=existing-token\n"
    assert system_caddyfile.read_text(encoding="utf-8") == source.read_text(encoding="utf-8")


def test_gandi_dns_check_mode_warns_without_prompt_or_secret_write(tmp_path: Path):
    source = tmp_path / "candidate.Caddyfile"
    source.write_text("*.example.test {\n  tls {\n    dns gandi {env.GANDI_BEARER_TOKEN}\n  }\n}\n", encoding="utf-8")
    system_caddyfile = tmp_path / "system.Caddyfile"
    system_caddyfile.write_text("previous working config\n", encoding="utf-8")
    fakebin = prepare_fakebin(tmp_path, has_gandi_module=True)
    service_env_file = tmp_path / "openmates-gandi.env"
    env = os.environ.copy()
    env.update({
        "GANDI_BEARER_TOKEN": "",
        "OPENMATES_SYSTEM_CADDYFILE": str(system_caddyfile),
        "OPENMATES_CADDY_SERVICE_ENV_FILE": str(service_env_file),
        "OPENMATES_CADDY_SERVICE_DROPIN": str(tmp_path / "caddy.service.d" / "openmates-gandi-token.conf"),
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
    assert "no existing Caddy service Gandi token was detected" in result.stdout
    assert "Apply mode will request and store the real token" in result.stdout
    assert "Enter the Gandi bearer token" not in result.stdout
    assert not service_env_file.exists()
    assert system_caddyfile.read_text(encoding="utf-8") == "previous working config\n"


def test_gandi_dns_check_mode_fails_when_module_missing(tmp_path: Path):
    source = tmp_path / "candidate.Caddyfile"
    source.write_text("*.example.test {\n  tls {\n    dns gandi {env.GANDI_BEARER_TOKEN}\n  }\n}\n", encoding="utf-8")
    system_caddyfile = tmp_path / "system.Caddyfile"
    system_caddyfile.write_text("previous working config\n", encoding="utf-8")
    fakebin = prepare_fakebin(tmp_path)
    env = os.environ.copy()
    env.update({
        "GANDI_BEARER_TOKEN": "fake-token",
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

    assert result.returncode == 1
    assert "installed Caddy binary does not include it" in result.stdout
    assert system_caddyfile.read_text(encoding="utf-8") == "previous working config\n"


def test_apply_mode_installs_gandi_module_before_copy(tmp_path: Path):
    source = tmp_path / "candidate.Caddyfile"
    source.write_text("*.example.test {\n  tls {\n    dns gandi {env.GANDI_BEARER_TOKEN}\n  }\n}\n", encoding="utf-8")
    system_caddyfile = tmp_path / "system.Caddyfile"
    system_caddyfile.write_text("previous working config\n", encoding="utf-8")
    fakebin = prepare_fakebin(tmp_path, with_fake_go=True)

    result = run_apply(source, system_caddyfile, fakebin, extra_env={"GANDI_BEARER_TOKEN": "fake-token"})

    assert result.returncode == 0
    assert "building and installing a compatible binary" in result.stdout
    assert "Installed Caddy with dns.providers.gandi" in result.stdout
    assert system_caddyfile.read_text(encoding="utf-8") == source.read_text(encoding="utf-8")
