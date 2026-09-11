#!/usr/bin/env python3
"""Install and gate the two user-level security reporting timers.

Normal status invocation is read-only.  Installation creates only the reporting
unit files; enabling them additionally requires a recorded current-data receipt.
"""

from __future__ import annotations

import argparse
import json
import os
from pathlib import Path
import subprocess
import tempfile
from typing import Any, Callable


from security_reporting_runner import accepted_test_receipt


UNITS = ("security-reporting-digest.timer", "security-reporting-retry.timer")


def default_reporting_directory() -> Path:
    return Path(os.environ.get("SECURITY_REPORTING_DIR") or Path(os.environ.get("PROJECT_ROOT", ".")) / "logs" / "security-reporting")


def _project_root() -> Path:
    return Path(os.environ.get("PROJECT_ROOT") or Path(__file__).resolve().parents[1]).resolve()


def _units(reporting_directory: Path) -> dict[str, str]:
    root = _project_root()
    command = f"python3 {root}/scripts/security_reporting_runner.py"
    service = f"[Service]\nType=oneshot\nWorkingDirectory={root}\nEnvironment=PROJECT_ROOT={root}\nEnvironment=SECURITY_REPORTING_DIR={reporting_directory.resolve()}\nExecStart={command}"
    return {
        "security-reporting-digest.service": f"{service} digest\n",
        "security-reporting-digest.timer": "[Timer]\nOnCalendar=*-*-* 08:30:00 UTC\nPersistent=true\nUnit=security-reporting-digest.service\n[Install]\nWantedBy=timers.target\n",
        "security-reporting-retry.service": f"{service} retry\n",
        "security-reporting-retry.timer": "[Timer]\nOnBootSec=5min\nOnUnitActiveSec=15min\nUnit=security-reporting-retry.service\n[Install]\nWantedBy=timers.target\n",
    }


def _read_marker(directory: Path) -> dict[str, Any]:
    try:
        value = json.loads((directory / "enabled.json").read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {}
    return value if isinstance(value, dict) else {}


def _write_marker(directory: Path, marker: dict[str, Any]) -> None:
    directory.mkdir(mode=0o700, parents=True, exist_ok=True)
    descriptor, temporary = tempfile.mkstemp(dir=directory, prefix=".enabled-", suffix=".json")
    with os.fdopen(descriptor, "w", encoding="utf-8") as file:
        file.write(json.dumps(marker, sort_keys=True))
    os.chmod(temporary, 0o600)
    Path(temporary).replace(directory / "enabled.json")


def install(*, unit_directory: Path | None = None, reporting_directory: Path | None = None, runner: Callable[[list[str]], int] | None = None) -> dict[str, bool]:
    unit_directory = unit_directory or Path.home() / ".config/systemd/user"
    reporting_directory = reporting_directory or default_reporting_directory()
    unit_directory.mkdir(mode=0o700, parents=True, exist_ok=True)
    for name, content in _units(reporting_directory).items():
        (unit_directory / name).write_text(content, encoding="utf-8")
    result = (runner or (lambda command: subprocess.run(command, check=False).returncode))(["systemctl", "--user", "daemon-reload"])
    if result:
        raise RuntimeError("systemd daemon-reload failed")
    marker = _read_marker(reporting_directory)
    marker["timer_installed"] = True
    _write_marker(reporting_directory, marker)
    return {"installed": True}


def status(*, unit_directory: Path | None = None, reporting_directory: Path | None = None) -> dict[str, bool]:
    unit_directory = unit_directory or Path.home() / ".config/systemd/user"
    reporting_directory = reporting_directory or default_reporting_directory()
    marker = _read_marker(reporting_directory)
    expected = _units(reporting_directory)
    return {"installed": all((unit_directory / name).is_file() and (unit_directory / name).read_text(encoding="utf-8") == expected[name] for name in expected), "enabled": marker.get("enabled") is True,
            "receipt_accepted": marker.get("current_data") is True and accepted_test_receipt(reporting_directory)}


def enable(*, unit_directory: Path | None = None, reporting_directory: Path | None = None, runner: Callable[[list[str]], int] | None = None) -> dict[str, bool]:
    unit_directory = unit_directory or Path.home() / ".config/systemd/user"
    reporting_directory = reporting_directory or default_reporting_directory()
    current = status(unit_directory=unit_directory, reporting_directory=reporting_directory)
    if not current["installed"] or not _read_marker(reporting_directory).get("timer_installed"):
        raise RuntimeError("timer installation must be checked before enable")
    if not current["receipt_accepted"]:
        raise RuntimeError("a labeled current-data test receipt must be accepted before enable")
    if _read_marker(reporting_directory).get("configured_destination") != "container":
        raise RuntimeError("accepted test receipt must record the container destination")
    result = (runner or (lambda command: subprocess.run(command, check=False).returncode))(["systemctl", "--user", "enable", "--now", *UNITS])
    if result:
        raise RuntimeError("systemd timer enable failed")
    marker = _read_marker(reporting_directory)
    marker.update({"enabled": True, "generic_email_suppression": True})
    _write_marker(reporting_directory, marker)
    return {"enabled": True}


def disable(*, reporting_directory: Path | None = None, runner: Callable[[list[str]], int] | None = None) -> dict[str, bool]:
    reporting_directory = reporting_directory or default_reporting_directory()
    result = (runner or (lambda command: subprocess.run(command, check=False).returncode))(["systemctl", "--user", "disable", "--now", *UNITS])
    if result:
        raise RuntimeError("systemd timer disable failed")
    marker = _read_marker(reporting_directory)
    marker.update({"enabled": False, "generic_email_suppression": False})
    _write_marker(reporting_directory, marker)
    return {"enabled": False}


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("command", choices=("status", "install", "enable", "disable"), nargs="?", default="status")
    args = parser.parse_args()
    result = {"status": status, "install": install, "enable": enable, "disable": disable}[args.command]()
    print(json.dumps(result, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
