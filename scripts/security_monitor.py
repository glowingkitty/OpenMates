#!/usr/bin/env python3
"""OpenMates automated security monitoring entry point.

Commands:
  hourly                       run the hourly watcher (sources, matching, triage dispatch, fixes, alerts)
  inventory                    regenerate and summarize the asset inventory
  digest                       send the daily monitoring digest and check watcher liveness
  status                       show open incidents, lease and recent runs
  acknowledge <incident-id>    mark an incident acknowledged (no further carry-forward alerts)
  install-schedule --print|--apply   render or install the managed crontab block

DRY_RUN=1 (or --dry-run) sends nothing, writes no state and launches no agent;
it prints the planned actions. --no-agents runs everything except claude chats.
Specification: specifications/architecture/security-monitoring/specification.yml
"""

from __future__ import annotations

import argparse
from datetime import datetime, timezone
import fcntl
import json
from pathlib import Path
import subprocess
import sys
from typing import Sequence

sys.path.insert(0, str(Path(__file__).resolve().parent))

from security_monitoring import dispatch, health  # noqa: E402 - path set above
from security_monitoring.config import Settings, load_settings  # noqa: E402 - path set above
from security_monitoring.state import Store, utc  # noqa: E402 - path set above

BEGIN_MARKER = "# BEGIN OpenMates security monitoring"
END_MARKER = "# END OpenMates security monitoring"


def render_crontab(existing: str, project_root: Path) -> str:
    """Return the crontab with exactly one managed security monitoring block."""
    retained: list[str] = []
    inside = False
    for line in existing.splitlines():
        if line == BEGIN_MARKER:
            inside = True
            continue
        if line == END_MARKER:
            inside = False
            continue
        if not inside:
            retained.append(line)
    while retained and not retained[-1].strip():
        retained.pop()
    root = project_root.resolve()
    log = f"{root}/logs/security-monitoring/cron.log"
    home = Path.home()
    # cron starts with a minimal PATH; triage needs claude, Task creation needs openmates, sources need gh.
    env = f"PATH={home}/.local/bin:{home}/.npm-global/bin:/usr/local/bin:/usr/bin:/bin"
    block = [
        BEGIN_MARKER,
        "# Hourly deterministic advisory watcher (+ triage/fix dispatch) and daily digest.",
        f"20 * * * * cd {root} && {env} /usr/bin/python3 scripts/security_monitor.py hourly >> {log} 2>&1",
        f"40 6 * * * cd {root} && {env} /usr/bin/python3 scripts/security_monitor.py digest >> {log} 2>&1",
        END_MARKER,
    ]
    return "\n".join([*retained, "", *block]).strip() + "\n"


def _current_crontab() -> str:
    result = subprocess.run(["crontab", "-l"], capture_output=True, text=True, check=False)
    if result.returncode not in (0, 1):
        raise RuntimeError("could not read crontab")
    return result.stdout


class RunLock:
    """Non-blocking process lock so overlapping hourly runs never stack."""

    def __init__(self, settings: Settings):
        self.path = settings.state_dir / "hourly.lock"
        self.handle = None

    def __enter__(self) -> bool:
        self.path.parent.mkdir(parents=True, mode=0o700, exist_ok=True)
        self.handle = open(self.path, "a", encoding="utf-8")
        try:
            fcntl.flock(self.handle, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError:
            return False
        return True

    def __exit__(self, *exc: object) -> None:
        if self.handle is not None:
            self.handle.close()


def cmd_hourly(settings: Settings) -> int:
    if settings.dry_run:
        report = dispatch.run_hourly(settings)
    else:
        with RunLock(settings) as acquired:
            if not acquired:
                print(json.dumps({"outcome": "skipped", "reason": "previous hourly run still active"}))
                return 0
            report = dispatch.run_hourly(settings)
    print(json.dumps({"run_id": report.run_id, "outcome": report.outcome, "dry_run": settings.dry_run,
                      "no_agents": settings.no_agents, **report.summary(), "planned": report.planned}, indent=1, sort_keys=True))
    return 0 if report.outcome in {"complete", "incomplete"} else 1


def cmd_inventory(settings: Settings) -> int:
    deps = dispatch.default_deps()
    now = datetime.now(timezone.utc)
    reports = deps.load_host_reports(settings.hosts_dir)
    inventory = deps.build_inventory(settings.project_root, reports, now)
    by_kind: dict[str, int] = {}
    for asset in inventory.assets:
        by_kind[asset.kind] = by_kind.get(asset.kind, 0) + 1
    print(json.dumps({"generated_at": inventory.generated_at, "complete": inventory.complete, "assets": len(inventory.assets),
                      "by_kind": by_kind, "not_used": sum(1 for a in inventory.assets if a.usage == "not_used"),
                      "incomplete_sources": list(inventory.incomplete_sources), "stale_hosts": list(inventory.stale_hosts)},
                     indent=1, sort_keys=True))
    return 0


def cmd_digest(settings: Settings) -> int:
    store = Store.open(settings.state_db, dry_run=settings.dry_run)
    try:
        result = health.run_digest(settings, store, dispatch.build_notifier(settings, store))
    finally:
        store.close()
    print(json.dumps(result, indent=1, sort_keys=True))
    return 0 if result.get("digest") in {"accepted", "queued", "dry_run"} else 2


def cmd_status(settings: Settings) -> int:
    store = Store.open(settings.state_db, dry_run=True)
    try:
        now = datetime.now(timezone.utc)
        data = health.digest_data(store, now)
        data["triage_lease_holder"] = store.lease_holder(now)
        data["queued_dispatches"] = len(store.dispatches_with_status("queued"))
    finally:
        store.close()
    print(json.dumps(data, indent=1, sort_keys=True))
    return 0


def cmd_acknowledge(settings: Settings, incident_id: str) -> int:
    store = Store.open(settings.state_db, dry_run=settings.dry_run)
    try:
        changed = store.acknowledge(incident_id, datetime.now(timezone.utc))
    finally:
        store.close()
    print(json.dumps({"incident_id": incident_id, "acknowledged": changed, "dry_run": settings.dry_run, "at": utc(datetime.now(timezone.utc))}))
    return 0 if changed else 1


def cmd_install_schedule(settings: Settings, *, apply: bool) -> int:
    existing = _current_crontab()
    rendered = render_crontab(existing, settings.project_root)
    if not apply or settings.dry_run:
        print(rendered, end="")
        return 0
    (settings.state_dir).mkdir(parents=True, mode=0o700, exist_ok=True)
    result = subprocess.run(["crontab", "-"], input=rendered, text=True, capture_output=True, check=False)
    if result.returncode != 0:
        raise RuntimeError("could not install crontab")
    print("Installed OpenMates security monitoring schedule.")
    return 0


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--dry-run", action="store_true", help="same as DRY_RUN=1")
    parser.add_argument("--no-agents", action="store_true", help="never launch claude triage or fix chats")
    commands = parser.add_subparsers(dest="command", required=True)
    commands.add_parser("hourly")
    commands.add_parser("inventory")
    commands.add_parser("digest")
    commands.add_parser("status")
    acknowledge = commands.add_parser("acknowledge")
    acknowledge.add_argument("incident_id")
    schedule = commands.add_parser("install-schedule")
    mode = schedule.add_mutually_exclusive_group(required=True)
    mode.add_argument("--print", action="store_true")
    mode.add_argument("--apply", action="store_true")
    args = parser.parse_args(argv)
    settings = load_settings(dry_run=True if args.dry_run else None, no_agents=args.no_agents)
    if args.command == "hourly":
        return cmd_hourly(settings)
    if args.command == "inventory":
        return cmd_inventory(settings)
    if args.command == "digest":
        return cmd_digest(settings)
    if args.command == "status":
        return cmd_status(settings)
    if args.command == "acknowledge":
        return cmd_acknowledge(settings, args.incident_id)
    return cmd_install_schedule(settings, apply=args.apply)


if __name__ == "__main__":
    raise SystemExit(main())
