"""Render the status server's environment file from Vault.

The status server keeps no configuration in the repository or the image. At
setup time this module reads the status monitor secret (plus the Brevo API key
for email alerts) from Vault and prints ``KEY=value`` lines for docker
compose's env file. Only allowlisted keys are written; everything else in the
secret stays in Vault.

Usage (inside the image): ``python -m status_agent.vault_env`` with
``VAULT_ADDR`` and ``VAULT_TOKEN`` (or ``VAULT_TOKEN_FILE``) set.
"""

from __future__ import annotations

import json
import os
import sys
import urllib.error
import urllib.request
from pathlib import Path
from typing import Callable, Mapping

STATUS_PATH = "kv/data/providers/status_monitor"
BREVO_PATH = "kv/data/providers/brevo"
DEFAULT_DOMAIN = "status.openmates.org"

# Vault key -> env name. Required keys stop the setup when missing.
REQUIRED = {"gatus_external_token": "GATUS_EXTERNAL_TOKEN", "discord_webhook_url": "DISCORD_WEBHOOK_URL"}
OPTIONAL = {"probe_token": "MONITOR_PROBE_TOKEN", "monitor_api_key": "MONITOR_API_KEY",
            "alert_email_to": "ALERT_EMAIL_TO"}

Fetch = Callable[[str, str, str], dict]


class ConfigError(Exception):
    """The Vault secret is missing or incomplete; the message says what to do."""


def render(status: Mapping[str, str], brevo_api_key: str) -> str:
    """The env file text for docker compose, from the status secret and the Brevo key."""
    missing = [key for key in REQUIRED if not status.get(key)]
    if missing:
        raise ConfigError(f"Vault {STATUS_PATH} lacks {', '.join(missing)}: "
                          "run `python3 scripts/status_server.py publish-config` on the dev server.")
    if status.get("alert_email_to") and not brevo_api_key:
        raise ConfigError(f"alert_email_to is set but Vault {BREVO_PATH} has no api_key.")
    domain = status.get("status_domain") or DEFAULT_DOMAIN
    env = {name: status[key] for key, name in REQUIRED.items()}
    env.update({name: status.get(key, "") for key, name in OPTIONAL.items()})
    env.update({
        "BREVO_API_KEY": brevo_api_key if status.get("alert_email_to") else "",
        "AI_WORKER_CHECK_ENABLED": "true" if status.get("ai_worker_check") == "true" else "false",
        # Real chat and skill probes stay off until production knows the probe token
        # and the monitoring account; otherwise they would count as normal usage.
        "SYNTHETIC_PROBES": "on" if status.get("synthetic_probes") == "on" else "off",
        "STATUS_DOMAIN": domain,
        "STATUS_PAGE_URL": f"https://{domain}",
    })
    for name, value in env.items():
        if any(ch in value for ch in "\r\n\0"):
            raise ConfigError(f"{name} contains a line break; fix the value in Vault.")
    return "".join(f"{name}={value}\n" for name, value in env.items())


def fetch_secret(addr: str, token: str, path: str) -> dict:
    """One KV v2 secret's data; an empty dict when the path does not exist."""
    request = urllib.request.Request(f"{addr.rstrip('/')}/v1/{path}", headers={"X-Vault-Token": token})
    try:
        with urllib.request.urlopen(request, timeout=15) as response:
            return json.load(response).get("data", {}).get("data", {}) or {}
    except urllib.error.HTTPError as error:
        if error.code == 404:
            return {}
        raise ConfigError(f"Vault refused {path}: HTTP {error.code} (check the token's policy).") from error
    except urllib.error.URLError as error:
        raise ConfigError(f"Vault not reachable at {addr}: {error.reason}") from error


def build_from_vault(addr: str, token: str, fetch: Fetch = fetch_secret) -> str:
    status = fetch(addr, token, STATUS_PATH)
    if not status:
        raise ConfigError(f"Vault has no {STATUS_PATH}: run `python3 scripts/status_server.py publish-config` "
                          "on the dev server.")
    brevo = fetch(addr, token, BREVO_PATH).get("api_key", "") if status.get("alert_email_to") else ""
    return render({k: str(v) for k, v in status.items()}, brevo)


def main() -> int:
    addr = os.environ.get("VAULT_ADDR", "")
    token = os.environ.get("VAULT_TOKEN", "")
    token_file = os.environ.get("VAULT_TOKEN_FILE", "")
    if not token and token_file:
        token = Path(token_file).read_text(encoding="utf-8").strip()
    if not addr or not token:
        print("VAULT_ADDR and VAULT_TOKEN (or VAULT_TOKEN_FILE) are required.", file=sys.stderr)
        return 2
    try:
        sys.stdout.write(build_from_vault(addr, token))
    except ConfigError as error:
        print(f"status config: {error}", file=sys.stderr)
        return 2
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
