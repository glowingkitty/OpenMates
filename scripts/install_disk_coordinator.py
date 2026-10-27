#!/usr/bin/env python3
"""Install the reviewed host disk owner as one supervised user service."""

import argparse
from pathlib import Path
import shutil
import subprocess
import sys

try:
    from scripts.disk_coordinator import canonical_repository, default_state
except ModuleNotFoundError:
    from disk_coordinator import canonical_repository, default_state


def unit(repository):
    script = canonical_repository(repository) / "scripts/disk_coordinator.py"
    if not script.is_file():
        raise RuntimeError("Deploy disk_coordinator.py to the canonical checkout first")

    def quote(value):
        return (
            '"'
            + str(value).replace("\\", "\\\\").replace('"', '\\"').replace("%", "%%")
            + '"'
        )

    return f"""[Unit]
Description=OpenMates host disk admission and cleanup coordinator

[Service]
Type=simple
ExecStart={quote(sys.executable)} {quote(script)} serve
Restart=on-failure
RestartSec=5
TimeoutStopSec=30
KillMode=control-group
UMask=0077
Nice=10
NoNewPrivileges=true

[Install]
WantedBy=default.target
"""


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--repository", type=Path, default=Path(__file__).resolve().parents[1]
    )
    parser.add_argument("--print", action="store_true", dest="print_only")
    args = parser.parse_args()
    content = unit(args.repository)
    if args.print_only:
        print(content, end="")
        return
    subprocess.run(
        ["systemctl", "--user", "is-active", "--quiet", "default.target"], check=True
    )
    destination = (
        Path.home() / ".config/systemd/user/openmates-disk-coordinator.service"
    )
    destination.parent.mkdir(parents=True, exist_ok=True)
    if destination.exists() and destination.read_text() != content:
        backup = default_state() / "previous-service.unit"
        backup.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
        shutil.copy2(destination, backup)
    destination.write_text(content)
    subprocess.run(["systemctl", "--user", "daemon-reload"], check=True)
    subprocess.run(
        ["systemctl", "--user", "enable", "--now", destination.name], check=True
    )
    print(
        "Installed supervised host disk coordinator; repository cutover remains explicit"
    )


if __name__ == "__main__":
    main()
