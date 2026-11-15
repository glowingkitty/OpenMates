"""Packaging and setup of the status server: config from Vault, nothing secret in the repo.

Covers deployment/status_server (vault_env, Dockerfile, compose file, setup.sh)
without network access or Docker.
"""

from __future__ import annotations

import ipaddress
import re
import sys
from pathlib import Path

import pytest
import yaml

ROOT = Path(__file__).resolve().parents[2]
SERVER = ROOT / "deployment/status_server"
sys.path.insert(0, str(SERVER / "agent"))

from status_agent import vault_env  # noqa: E402 - path set up above

CONFIG = "external-status-monitoring.deploy.config-from-vault"
PACKAGE = "external-status-monitoring.deploy.one-image-one-command"

STATUS = {"gatus_external_token": "g-token", "discord_webhook_url": "https://discord.example.org/hook",
          "probe_token": "p-token", "monitor_api_key": "m-key", "alert_email_to": "ops@example.org",
          "netcup_refresh_token": "never-exported", "ai_worker_check": "true"}


def _env(text: str) -> dict[str, str]:
    return dict(line.split("=", 1) for line in text.splitlines())


# contract-test: direct surface=tooling assertions=external-status-monitoring.deploy.config-from-vault
def test_env_file_has_only_allowlisted_values() -> None:
    env = _env(vault_env.render(STATUS, "brevo-key"))
    assert env["GATUS_EXTERNAL_TOKEN"] == "g-token" and env["BREVO_API_KEY"] == "brevo-key"
    assert env["AI_WORKER_CHECK_ENABLED"] == "true"
    assert env["STATUS_DOMAIN"] == "status.openmates.org"
    assert "never-exported" not in "\n".join(env.values())
    assert not any("NETCUP" in name for name in env)


# contract-test: direct surface=tooling assertions=external-status-monitoring.deploy.config-from-vault
def test_incomplete_or_unsafe_config_stops_setup() -> None:
    with pytest.raises(vault_env.ConfigError, match="discord_webhook_url"):
        vault_env.render({"gatus_external_token": "g"}, "")
    with pytest.raises(vault_env.ConfigError, match="brevo"):
        vault_env.render(STATUS, "")
    with pytest.raises(vault_env.ConfigError, match="line break"):
        vault_env.render(dict(STATUS, probe_token="a\nEVIL=1"), "k")


# contract-test: direct surface=tooling assertions=external-status-monitoring.deploy.config-from-vault
def test_vault_reads_status_secret_and_brevo_key_only_when_email_is_on() -> None:
    reads: list[str] = []

    def fetch(addr: str, token: str, path: str) -> dict:
        reads.append(path)
        return {vault_env.STATUS_PATH: dict(STATUS, alert_email_to=""), vault_env.BREVO_PATH: {"api_key": "b"}}[path]

    env = _env(vault_env.build_from_vault("http://vault.example.org", "t", fetch))
    assert reads == [vault_env.STATUS_PATH] and env["BREVO_API_KEY"] == ""
    with pytest.raises(vault_env.ConfigError, match="publish-config"):
        vault_env.build_from_vault("http://vault.example.org", "t", lambda *_: {})


# contract-test: direct surface=tooling assertions=external-status-monitoring.deploy.config-from-vault
def test_repository_files_hold_no_addresses_or_secrets() -> None:
    files = [p for p in SERVER.rglob("*")
             if p.is_file() and "__pycache__" not in p.parts and p.suffix != ".svg"]
    files.append(ROOT / ".github/workflows/publish-status-image.yml")
    allowed_ips = {"127.0.0.1", "0.0.0.0"}
    for path in files:
        text = path.read_text(encoding="utf-8", errors="ignore")
        ips = {ip for ip in re.findall(r"(?<![\d.])(?:\d{1,3}\.){3}\d{1,3}(?![\d.])", text)
               if ip not in allowed_ips and not ipaddress.ip_address(ip).is_private}
        assert not ips, f"{path}: {ips}"
        values = re.findall(r"(?i)(?:token|key|password|secret)\w*\s*[:=]\s*['\"]?([A-Za-z0-9_\-]{20,})", text)
        assert not [v for v in values if sum(ch.isdigit() for ch in v) >= 4], path
        assert "hooks/" not in text or "discord.example.org" in text, path


# contract-test: direct surface=tooling assertions=external-status-monitoring.deploy.one-image-one-command
def test_compose_runs_the_published_image_with_gatus_on_loopback() -> None:
    compose = yaml.safe_load((SERVER / "docker-compose.yml").read_text(encoding="utf-8"))
    assert list(compose["services"]) == ["status"]
    service = compose["services"]["status"]
    assert "build" not in service
    assert service["image"].startswith("${STATUS_IMAGE:-ghcr.io/glowingkitty/openmates-status:")
    assert service["env_file"] == "status.env"
    gatus_ports = [p for p in service["ports"] if p.endswith(":8080")]
    assert gatus_ports and all(p.startswith("127.0.0.1:") for p in gatus_ports)


# contract-test: direct surface=tooling assertions=external-status-monitoring.deploy.one-image-one-command
def test_image_ships_compose_and_setup_and_runs_unprivileged() -> None:
    dockerfile = (SERVER / "Dockerfile").read_text(encoding="utf-8")
    assert "COPY docker-compose.yml setup.sh /app/deploy/" in dockerfile
    assert re.search(r"^USER status$", dockerfile, re.M)
    assert 'CMD ["python", "-m", "status_agent.supervise"]' in dockerfile
    setup = (SERVER / "setup.sh").read_text(encoding="utf-8")
    for step in ("docker pull", "--config-stdin", "status_agent.vault_env", "/app/deploy/docker-compose.yml",
                 "up -d --remove-orphans"):
        assert step in setup, step
    workflow = yaml.safe_load((ROOT / ".github/workflows/publish-status-image.yml").read_text(encoding="utf-8"))
    assert workflow["env"]["IMAGE"] == "ghcr.io/glowingkitty/openmates-status"
