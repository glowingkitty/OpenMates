#!/usr/bin/env python3
"""Operate the external status server (status.openmates.org) from the dev server.

Commands:
  secret status              Show which status-monitor secrets exist in Vault (never values).
  secret set <name>          Ask for one secret without echo and store it in Vault.
  ssh-key                    Print the deploy SSH public key to paste when creating the UpCloud
                             server (creates the key on first use).
  publish-config             Put everything the status server needs into Vault: generated tokens,
                             the Discord webhook and alert email from this server's .env.
  setup --host <ip> [--image <ref>]
                             Read the status config from Vault and run the setup script on the VPS
                             (installs Docker and a firewall on first run, pulls the image, writes
                             status.env from stdin, starts it). Updates on the VPS itself:
                             `openmates-status-setup` (pull and restart).
  watch                      Cross-check from the dev server: alert when the status page is
                             unreachable or stale (run every 5 minutes by a systemd user timer,
                             scripts/status-server-watch-setup.sh).

Secrets live in Vault at kv/data/providers/status_monitor. They are read through
the dev api container (read-only token) and written like every provider secret:
SECRET__STATUS_MONITOR__* in the canonical .env, imported by vault-setup. Nothing secret is
printed, passed on a command line, or written outside the VPS's mode-600 status.env.
The status server is one UpCloud Starter server the owner creates by hand (no
provider API token is stored). It runs the published public image
(deployment/status_server/Dockerfile) and nothing else; this script never copies
source code to it.
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

from status_agent.alerts import CheckResult, CheckSnapshot, OpenAlert, evaluate  # noqa: E402 - agent package, path set above
from status_agent.notify import Channels, deliver  # noqa: E402 - agent package, path set above
from status_agent.vault_env import BREVO_PATH, ConfigError, render  # noqa: E402 - agent package, path set above

GIT_COMMON = subprocess.run(["git", "-C", str(SCRIPT_DIR), "rev-parse", "--path-format=absolute",
                             "--git-common-dir"], capture_output=True, text=True, check=False).stdout.strip()
CANONICAL_ROOT = Path(GIT_COMMON).parent if GIT_COMMON else SCRIPT_DIR.parent
SOURCE_DIR = SCRIPT_DIR.parent / "deployment/status_server"
VAULT_PATH = "kv/data/providers/status_monitor"
ENV_PREFIX = "SECRET__STATUS_MONITOR__"
SECRET_NAMES = {
    "monitor_api_key": "API key of the dedicated production monitoring account",
    "probe_token": "shared token marking anonymous monitor probes (auto-generated)",
    "gatus_external_token": "token for pushing probe results into Gatus (auto-generated)",
    "discord_webhook_url": "Discord webhook for alerts (publish-config fills it from .env if unset)",
}
GENERATED = ("probe_token", "gatus_external_token")
CONFIG_PATH = Path.home() / ".config/openmates/status_server.json"
WATCH_STATE = Path.home() / ".local/state/openmates/status_server_watch.json"
SSH_KEY = Path.home() / ".ssh/openmates_status_ed25519"
SETUP_SCRIPT = SOURCE_DIR / "setup.sh"
REMOTE_SETUP = "/usr/local/bin/openmates-status-setup"
REMOTE_SETTINGS = "/opt/openmates-status/settings.env"
DEFAULT_IMAGE = "ghcr.io/glowingkitty/openmates-status:main"
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
    if request["op"] == "get":
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


def vault(op: str, path: str = VAULT_PATH) -> dict:
    """Read Vault inside the dev api container (its token is read-only); request via stdin."""
    command = ["docker", "compose", "--env-file", str(CANONICAL_ROOT / ".env"), "-f",
               str(CANONICAL_ROOT / "backend/core/docker-compose.yml"), "exec", "-T", "api",
               "python3", "-c", VAULT_SNIPPET]
    payload = json.dumps({"op": op, "path": path})
    result = subprocess.run(command, input=payload, capture_output=True, text=True, timeout=60,
                            cwd=CANONICAL_ROOT, check=False)
    if result.returncode != 0:
        raise SystemExit(f"Vault {op} failed (api container exit {result.returncode}).")
    return json.loads(result.stdout.strip().splitlines()[-1])


def store(values: dict[str, str]) -> None:
    """Write status secrets to Vault the way the dev server imports all provider secrets.

    Each value goes into the canonical .env as SECRET__STATUS_MONITOR__<NAME>; the
    vault-setup service copies it to kv/data/providers/status_monitor and replaces
    the .env value with IMPORTED_TO_VAULT. Values never appear on a command line.
    """
    for name, value in values.items():
        if not value or "\n" in value:
            raise SystemExit(f"Refusing to store an empty or multi-line value for {name}.")
    env_file = CANONICAL_ROOT / ".env"
    keys = {f"{ENV_PREFIX}{name.upper()}": value for name, value in values.items()}
    lines = [line for line in env_file.read_text(encoding="utf-8").splitlines()
             if line.split("=", 1)[0] not in keys]
    lines += [f"{key}={value}" for key, value in keys.items()]
    env_file.write_text("\n".join(lines) + "\n", encoding="utf-8")
    restart = ["python3", str(CANONICAL_ROOT / "scripts/sessions.py"), "docker", "run-setup",
               "--service", "vault-setup"]
    if os.environ.get("OPENMATES_SESSION_ID"):
        restart[4:4] = ["--session", os.environ["OPENMATES_SESSION_ID"]]
    subprocess.run(restart, cwd=SCRIPT_DIR.parent, check=True, timeout=900)
    missing = set(values) - set(vault("status")["present"])
    if missing:
        raise SystemExit(f"vault-setup did not import: {', '.join(sorted(missing))}.")


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
    store({args.name: value})
    print(f"Stored {args.name} in Vault ({VAULT_PATH}).")
    return 0


def ensure_ssh_key() -> str:
    if not SSH_KEY.exists():
        SSH_KEY.parent.mkdir(mode=0o700, exist_ok=True)
        subprocess.run(["ssh-keygen", "-q", "-t", "ed25519", "-N", "", "-C", "openmates-status-deploy",
                        "-f", str(SSH_KEY)], check=True)
    return SSH_KEY.with_suffix(".pub").read_text(encoding="utf-8").strip()


def cmd_ssh_key(_: argparse.Namespace) -> int:
    print(ensure_ssh_key())
    return 0


def image_is_public(image: str) -> bool:
    """True when anyone can pull ``image`` (ghcr.io/<owner>/<name>:<tag>) without logging in."""
    repository, _, tag = image.removeprefix("ghcr.io/").rpartition(":")
    try:
        with urllib.request.urlopen(f"https://ghcr.io/token?scope=repository:{repository}:pull", timeout=20) as r:
            token = json.load(r)["token"]
        request = urllib.request.Request(
            f"https://ghcr.io/v2/{repository}/manifests/{tag}", method="HEAD",
            headers={"Authorization": f"Bearer {token}", "Accept": "application/vnd.oci.image.index.v1+json"})
        with urllib.request.urlopen(request, timeout=20) as response:
            return response.status == 200
    except (OSError, ValueError, KeyError):
        return False


def cmd_publish_config(args: argparse.Namespace) -> int:
    """Store everything the status server reads from Vault (values are never printed)."""
    stored = vault("get")
    values = {name: secrets.token_urlsafe(32) for name in GENERATED if not stored.get(name)}
    if not stored.get("discord_webhook_url"):
        discord = (dotenv("STATUS_ALERT_DISCORD_WEBHOOK") or dotenv("DISCORD_WEBHOOK_DEGRADED_SERVICES")
                   or dotenv("DISCORD_WEBHOOK_AGENT_QUESTIONS"))
        if not discord:
            raise SystemExit("No Discord webhook in .env: run `secret set discord_webhook_url`.")
        values["discord_webhook_url"] = discord
    config = load_config()
    values["alert_email_to"] = dotenv("ADMIN_NOTIFY_EMAIL") or dotenv("SERVER_OWNER_EMAIL")
    values["status_domain"] = config.get("domain", DEFAULT_DOMAIN)
    if args.ai_worker_check:
        config["ai_worker_check"] = args.ai_worker_check == "on"
        save_config(config)
    values["ai_worker_check"] = "true" if config.get("ai_worker_check") else "false"
    store(values)
    print(f"Stored in Vault: {', '.join(sorted(values))}. Apply on the VPS with `setup`.")
    return 0


def status_env() -> str:
    """The VPS env file, rendered from Vault with the same code the image uses."""
    stored = vault("get")
    brevo = vault("get", path=BREVO_PATH).get("api_key", "") if stored.get("alert_email_to") else ""
    try:
        return render(stored, brevo)
    except ConfigError as error:
        raise SystemExit(str(error)) from error


def ssh(target: str, command: str, stdin: str | None = None) -> None:
    subprocess.run(["ssh", "-i", str(SSH_KEY), "-o", "StrictHostKeyChecking=accept-new", target, command],
                   input=stdin, text=True, check=True, timeout=1800)


def cmd_setup(args: argparse.Namespace) -> int:
    config = load_config()
    host = args.host or config.get("host")
    if not host:
        raise SystemExit("No host known: pass --host <server IPv4 from the UpCloud control panel>.")
    image = args.image or config.get("image") or DEFAULT_IMAGE
    if not image_is_public(image):
        raise SystemExit(f"{image} cannot be pulled without login. Use a published tag, e.g. "
                         "--image ghcr.io/glowingkitty/openmates-status:sha-<dev commit> before the first "
                         "main release (CI workflow 'Publish Status Image').")
    env_text = status_env()
    ensure_ssh_key()
    target = f"{args.user}@{host}"
    ssh(target, f"umask 022; cat > {REMOTE_SETUP}.new && chmod 755 {REMOTE_SETUP}.new && mv {REMOTE_SETUP}.new {REMOTE_SETUP}",
        stdin=SETUP_SCRIPT.read_text(encoding="utf-8"))
    ssh(target, f"umask 022; mkdir -p {Path(REMOTE_SETTINGS).parent} && cat > {REMOTE_SETTINGS}",
        stdin=f"STATUS_IMAGE={image}\n")
    ssh(target, f"{REMOTE_SETUP} --config-stdin", stdin=env_text)
    domain = config.get("domain", DEFAULT_DOMAIN)
    save_config({**config, "host": host, "image": image, "domain": domain, "deployed_at": int(time.time())})
    print(f"Status server set up on {host} with {image}. Page: https://{domain} "
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
    sub.add_parser("ssh-key").set_defaults(func=cmd_ssh_key)
    publish = sub.add_parser("publish-config")
    publish.add_argument("--ai-worker-check", choices=["on", "off"],
                         help="turn the AI-worker liveness check on once production serves the route")
    publish.set_defaults(func=cmd_publish_config)
    setup = sub.add_parser("setup")
    setup.add_argument("--host", help="public IPv4 of the UpCloud server")
    setup.add_argument("--image", help=f"image to run (default: last used, else {DEFAULT_IMAGE})")
    setup.add_argument("--user", default="root", help="SSH login user (default: root)")
    setup.set_defaults(func=cmd_setup)
    sub.add_parser("watch").set_defaults(func=cmd_watch)
    args = parser.parse_args(argv)
    if args.command == "secret" and args.action == "set" and not args.name:
        parser.error("secret set needs a name")
    return int(args.func(args))


if __name__ == "__main__":
    sys.exit(main())
