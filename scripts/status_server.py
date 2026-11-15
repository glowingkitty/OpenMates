#!/usr/bin/env python3
"""Operate the external status server (status.openmates.org) from the dev server.

Commands:
  secret status              Show which status-monitor secrets exist in Vault (never values).
  secret set <name>          Ask for one secret without echo and store it in Vault.
  netcup-login               Approve a netcup login in the browser; stores the API token in Vault.
  provision --wipe           Install Debian 13 with our SSH key on the netcup VPS (erases its disk).
  deploy [--host <ip>]       Copy deployment/status_server to the VPS, write its .env, start it.
  watch                      Cross-check from the dev server: alert when the status page is
                             unreachable or stale (run every 5 minutes by a systemd user timer,
                             scripts/status-server-watch-setup.sh).

Secrets live in Vault at kv/data/providers/status_monitor and are read through
the dev api container (same pattern as other host scripts). Nothing secret is
printed, passed on a command line, or written outside the VPS's mode-600 .env.
Spec: specifications/architecture/external-status-monitoring.
"""

from __future__ import annotations

import argparse
import getpass
import json
import os
import secrets
import subprocess
import sys
import time
import urllib.request
from pathlib import Path

SCRIPT_DIR = Path(__file__).resolve().parent
sys.path.insert(0, str(SCRIPT_DIR))
sys.path.insert(0, str(SCRIPT_DIR.parent / "deployment/status_server/agent"))

import _status_server_netcup as netcup  # noqa: E402 - sibling helper, path set above
from status_agent.alerts import CheckResult, CheckSnapshot, OpenAlert, evaluate  # noqa: E402 - agent package, path set above
from status_agent.notify import Channels, deliver  # noqa: E402 - agent package, path set above

GIT_COMMON = subprocess.run(["git", "-C", str(SCRIPT_DIR), "rev-parse", "--path-format=absolute",
                             "--git-common-dir"], capture_output=True, text=True, check=False).stdout.strip()
CANONICAL_ROOT = Path(GIT_COMMON).parent if GIT_COMMON else SCRIPT_DIR.parent
SOURCE_DIR = SCRIPT_DIR.parent / "deployment/status_server"
VAULT_PATH = "kv/data/providers/status_monitor"
SECRET_NAMES = {
    "monitor_api_key": "API key of the dedicated production monitoring account",
    "netcup_refresh_token": "netcup SCP API token (prefer: netcup-login)",
    "probe_token": "shared token marking anonymous monitor probes (auto-generated)",
    "gatus_external_token": "token for pushing probe results into Gatus (auto-generated)",
}
GENERATED = ("probe_token", "gatus_external_token")
CONFIG_PATH = Path.home() / ".config/openmates/status_server.json"
WATCH_STATE = Path.home() / ".local/state/openmates/status_server_watch.json"
SSH_KEY = Path.home() / ".ssh/openmates_status_ed25519"
REMOTE_DIR = "/opt/openmates-status"
DEFAULT_DOMAIN = "status.openmates.org"
STALE_AFTER_S = 10 * 60
WATCH_EVERY_S = 5 * 60

VAULT_SNIPPET = """
import asyncio, json, sys
from backend.core.api.app.utils.secrets_manager import SecretsManager
request = json.load(sys.stdin)
async def main():
    sm = SecretsManager()
    await sm.initialize()
    current = await sm.get_secrets_from_path(request["path"]) or {}
    if request["op"] == "set":
        current.update(request["values"])
        if not await sm.store_secrets_at_path(request["path"], current):
            raise SystemExit("vault write failed")
        print(json.dumps({"stored": sorted(request["values"])}))
    elif request["op"] == "get":
        print(json.dumps(current))
    else:
        print(json.dumps({"present": sorted(k for k, v in current.items() if v)}))
asyncio.run(main())
"""


def dotenv(key: str) -> str:
    """Value of ``key`` from the environment or the canonical checkout's .env."""
    if os.environ.get(key):
        return os.environ[key]
    env_file = CANONICAL_ROOT / ".env"
    if env_file.exists():
        for line in env_file.read_text(encoding="utf-8").splitlines():
            if line.startswith(f"{key}="):
                return line.split("=", 1)[1].strip().strip('"')
    return ""


def vault(op: str, values: dict[str, str] | None = None, path: str = VAULT_PATH) -> dict:
    """Run one Vault operation inside the dev api container; payload goes via stdin."""
    command = ["docker", "compose", "--env-file", str(CANONICAL_ROOT / ".env"), "-f",
               str(CANONICAL_ROOT / "backend/core/docker-compose.yml"), "exec", "-T", "api",
               "python3", "-c", VAULT_SNIPPET]
    payload = json.dumps({"op": op, "path": path, "values": values or {}})
    result = subprocess.run(command, input=payload, capture_output=True, text=True, timeout=60,
                            cwd=CANONICAL_ROOT, check=False)
    if result.returncode != 0:
        raise SystemExit(f"Vault {op} failed (api container exit {result.returncode}).")
    return json.loads(result.stdout.strip().splitlines()[-1])


def load_config() -> dict:
    return json.loads(CONFIG_PATH.read_text(encoding="utf-8")) if CONFIG_PATH.exists() else {}


def save_config(config: dict) -> None:
    CONFIG_PATH.parent.mkdir(parents=True, exist_ok=True)
    CONFIG_PATH.write_text(json.dumps(config, indent=2), encoding="utf-8")


def cmd_secret(args: argparse.Namespace) -> int:
    if args.action == "status":
        present = set(vault("status")["present"])
        for name, description in SECRET_NAMES.items():
            print(f"{'set    ' if name in present else 'MISSING'}  {name}: {description}")
        return 0
    if args.name not in SECRET_NAMES:
        raise SystemExit(f"Unknown secret {args.name!r}. Known: {', '.join(SECRET_NAMES)}")
    value = getpass.getpass(f"Paste {SECRET_NAMES[args.name]} (input hidden): ").strip()
    if not value:
        raise SystemExit("Nothing entered; Vault unchanged.")
    vault("set", {args.name: value})
    print(f"Stored {args.name} in Vault ({VAULT_PATH}).")
    return 0


def cmd_netcup_login(_: argparse.Namespace) -> int:
    login = netcup.start_device_login()
    print("Open this link, sign in to netcup and approve the access:")
    print(f"  {login.verification_url}")
    print(f"Code shown there should be: {login.user_code}")
    print("Waiting for your approval…")
    token = netcup.wait_for_refresh_token(login)
    vault("set", {"netcup_refresh_token": token})
    servers = netcup.Client(netcup.access_token(token)).servers()
    print(f"Stored the netcup API token in Vault. netcup shows {len(servers)} server(s):")
    for server in servers:
        print(f"  {server.get('id')}  {server.get('name')}  {server.get('nickname') or ''}")
    return 0


def ensure_ssh_key() -> str:
    if not SSH_KEY.exists():
        SSH_KEY.parent.mkdir(mode=0o700, exist_ok=True)
        subprocess.run(["ssh-keygen", "-q", "-t", "ed25519", "-N", "", "-C", "openmates-status-deploy",
                        "-f", str(SSH_KEY)], check=True)
    return SSH_KEY.with_suffix(".pub").read_text(encoding="utf-8").strip()


def netcup_client() -> netcup.Client:
    token = vault("get").get("netcup_refresh_token")
    if not token:
        raise SystemExit("No netcup token in Vault yet: run `python3 scripts/status_server.py netcup-login`.")
    return netcup.Client(netcup.access_token(token))


def cmd_provision(args: argparse.Namespace) -> int:
    client = netcup_client()
    servers = client.servers()
    if args.server:
        servers = [s for s in servers if args.server in (str(s.get("id")), s.get("name"), s.get("nickname"))]
    if len(servers) != 1:
        raise SystemExit(f"Expected exactly one netcup server, found {len(servers)}; pass --server <id>.")
    server = servers[0]
    ipv4 = client.ipv4_addresses(int(server["id"]))
    print(f"Server {server['id']} ({server.get('name')}), IPv4 {', '.join(ipv4) or 'none'}.")
    if not args.wipe:
        print("Dry run. Re-run with --wipe to install Debian 13 with our SSH key (erases the disk).")
        return 0
    user_id = netcup.user_id_from_token(client.token)
    key_id = client.ensure_ssh_key(user_id, "openmates-status-deploy", ensure_ssh_key())
    flavour = client.debian_flavour(int(server["id"]))
    print(f"Installing {flavour['name']} …")
    client.wait_task(client.install_image(int(server["id"]), int(flavour["id"]), key_id, "status-openmates"))
    save_config({**load_config(), "host": ipv4[0] if ipv4 else "", "server_id": server["id"]})
    print("Done. Next: add the DNS record, then run `python3 scripts/status_server.py deploy`.")
    return 0


def build_env(stored: dict[str, str]) -> dict[str, str]:
    """The VPS .env: tokens from Vault, delivery settings from the dev server."""
    brevo = vault("get", path="kv/data/providers/brevo").get("api_key", "")
    discord = (dotenv("STATUS_ALERT_DISCORD_WEBHOOK") or dotenv("DISCORD_WEBHOOK_DEGRADED_SERVICES")
               or dotenv("DISCORD_WEBHOOK_AGENT_QUESTIONS"))
    return {
        "GATUS_EXTERNAL_TOKEN": stored["gatus_external_token"],
        "MONITOR_PROBE_TOKEN": stored["probe_token"],
        "MONITOR_API_KEY": stored.get("monitor_api_key", ""),
        "AI_WORKER_CHECK_ENABLED": "true" if load_config().get("ai_worker_check") else "false",
        "DISCORD_WEBHOOK_URL": discord,
        "BREVO_API_KEY": brevo,
        "ALERT_EMAIL_TO": dotenv("ADMIN_NOTIFY_EMAIL") or dotenv("SERVER_OWNER_EMAIL"),
        "ALERT_EMAIL_FROM": "noreply@openmates.org",
        "STATUS_DOMAIN": load_config().get("domain", DEFAULT_DOMAIN),
        "STATUS_PAGE_URL": f"https://{load_config().get('domain', DEFAULT_DOMAIN)}",
        "PROD_API_URL": "https://api.openmates.org",
    }


def ssh(host: str, command: str, stdin: str | None = None) -> None:
    subprocess.run(["ssh", "-i", str(SSH_KEY), "-o", "StrictHostKeyChecking=accept-new",
                    f"root@{host}", command], input=stdin, text=True, check=True, timeout=1800)


BOOTSTRAP = ("set -e; export DEBIAN_FRONTEND=noninteractive; apt-get update -q; "
             "apt-get install -y -q docker.io docker-compose rsync ufw unattended-upgrades; "
             "ufw allow 22/tcp; ufw allow 80/tcp; ufw allow 443/tcp; ufw --force enable; "
             "systemctl enable --now docker; mkdir -p " + REMOTE_DIR)


def cmd_deploy(args: argparse.Namespace) -> int:
    config = load_config()
    host = args.host or config.get("host")
    if not host:
        raise SystemExit("No host known: pass --host <ip> (or run provision first).")
    stored = vault("get")
    missing = [name for name in GENERATED if not stored.get(name)]
    if missing:
        vault("set", {name: secrets.token_urlsafe(32) for name in missing})
        stored = vault("get")
    ensure_ssh_key()
    ssh(host, BOOTSTRAP)
    subprocess.run(["rsync", "-a", "--delete", "--exclude", ".env", "-e",
                    f"ssh -i {SSH_KEY} -o StrictHostKeyChecking=accept-new",
                    f"{SOURCE_DIR}/", f"root@{host}:{REMOTE_DIR}/"], check=True, timeout=600)
    env_text = "".join(f"{key}={value}\n" for key, value in build_env(stored).items())
    ssh(host, f"umask 077; cat > {REMOTE_DIR}/.env", stdin=env_text)
    ssh(host, f"cd {REMOTE_DIR} && {{ docker compose version >/dev/null 2>&1 && C='docker compose' || C=docker-compose; }}"
               " && $C up -d --build --remove-orphans")
    save_config({**config, "host": host, "domain": config.get("domain", DEFAULT_DOMAIN),
                 "deployed_at": int(time.time())})
    print(f"Deployed to {host}. Page: https://{config.get('domain', DEFAULT_DOMAIN)} "
          "(TLS appears once DNS points there). The dev-server watch is now active.")
    return 0


def page_is_fresh(url: str, now: float) -> bool:
    """True when the public status data is reachable and the agent wrote it recently."""
    try:
        with urllib.request.urlopen(url, timeout=20) as response:
            data = json.load(response)
    except (OSError, ValueError):
        return False
    return isinstance(data, dict) and now - float(data.get("generated_at", 0)) <= STALE_AFTER_S


def cmd_watch(_: argparse.Namespace) -> int:
    config = load_config()
    if not config.get("deployed_at"):
        print("Status server not deployed yet; nothing to watch.")
        return 0
    domain = config.get("domain", DEFAULT_DOMAIN)
    now = time.time()
    state = json.loads(WATCH_STATE.read_text(encoding="utf-8")) if WATCH_STATE.exists() else {}
    results = [CheckResult(*r) for r in state.get("results", [])]
    results.append(CheckResult(now, page_is_fresh(f"https://{domain}/data/status.json", now)))
    results = results[-10:]
    alerts = {k: OpenAlert.from_json(v) for k, v in state.get("alerts", {}).items()}
    snapshot = CheckSnapshot("status-page", f"Status page {domain}", tuple(results), WATCH_EVERY_S * 3)
    evaluation = evaluate([snapshot], alerts, now)
    if evaluation.notifications:
        try:
            brevo = vault("get", path="kv/data/providers/brevo").get("api_key", "")
        except SystemExit:
            brevo = ""
        channels = Channels(dotenv("DISCORD_WEBHOOK_AGENT_QUESTIONS") or dotenv("DISCORD_WEBHOOK_DEV_NIGHTLY"),
                            brevo, dotenv("ADMIN_NOTIFY_EMAIL") or dotenv("SERVER_OWNER_EMAIL"),
                            "noreply@openmates.org", "Dev server cross-check", f"https://{domain}")
        for failure in deliver(evaluation.notifications, channels):
            print(f"delivery problem: {failure}", file=sys.stderr)
    WATCH_STATE.parent.mkdir(parents=True, exist_ok=True)
    WATCH_STATE.write_text(json.dumps({
        "results": [[r.timestamp, r.success] for r in results],
        "alerts": {k: v.to_json() for k, v in evaluation.state.items()}}), encoding="utf-8")
    print(f"status page {'ok' if results[-1].success else 'FAILED'}; open alerts: {len(evaluation.state)}")
    return 0


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = parser.add_subparsers(dest="command", required=True)
    secret = sub.add_parser("secret")
    secret.add_argument("action", choices=["status", "set"])
    secret.add_argument("name", nargs="?")
    secret.set_defaults(func=cmd_secret)
    sub.add_parser("netcup-login").set_defaults(func=cmd_netcup_login)
    provision = sub.add_parser("provision")
    provision.add_argument("--server")
    provision.add_argument("--wipe", action="store_true")
    provision.set_defaults(func=cmd_provision)
    deploy = sub.add_parser("deploy")
    deploy.add_argument("--host")
    deploy.set_defaults(func=cmd_deploy)
    sub.add_parser("watch").set_defaults(func=cmd_watch)
    args = parser.parse_args(argv)
    if args.command == "secret" and args.action == "set" and not args.name:
        parser.error("secret set needs a name")
    return int(args.func(args))


if __name__ == "__main__":
    sys.exit(main())
