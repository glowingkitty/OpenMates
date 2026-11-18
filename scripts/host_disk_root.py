#!/usr/bin/python3 -I
"""Weekly root-only disk cleanup the user-level disk coordinator cannot do.

Installed by ``scripts/host-disk-root-setup.sh`` as a root-owned copy in
/usr/local/sbin and run by a weekly systemd timer. Three jobs, all rebuildable:

* orphaned Docker overlay2 layers: layer folders that no image layer, container
  mount, container init layer, ``docker inspect`` record or BuildKit database
  names, untouched for ORPHAN_MIN_AGE_DAYS. ``docker system prune`` cannot see
  them (dev host, 2026-11-16: 38 GB of 49 GB in overlay2);
* container json logs above LOG_CAP_BYTES, and then the largest ones until all
  fit in LOGS_TOTAL_CAP_BYTES, are truncated in place (Docker keeps appending to
  the same file). New containers rotate their own logs once the Docker default
  log options from the setup script are active;
* the systemd journal is vacuumed to JOURNAL_CAP.

``report`` (the default) only lists; ``apply`` deletes. Each run writes a JSON
report readable by every user to REPORT_PATH, which the hourly size log
(scripts/host_disk_usage.py) shows. Architecture:
docs/architecture/infrastructure/dev-host-resources.md (section "Disk budgets").
"""

from __future__ import annotations

import argparse
import json
import os
from pathlib import Path
import re
import shutil
import stat
import subprocess
import sys
import time

DOCKER_ROOT = Path("/var/lib/docker")
REPORT_PATH = Path("/var/lib/openmates-host-disk/report.json")
ORPHAN_MIN_AGE_DAYS = 7
LOG_CAP_BYTES = 100 * 1024**2
# All container json logs together (owner budget, TASK-7646): the largest are
# truncated first until the rest fits.
LOGS_TOTAL_CAP_BYTES = 1000**3
JOURNAL_CAP = "1G"
# Docker names layer folders with 64 hex characters (older engines) or 25
# lowercase base-36 characters (current engines), plus "-init" for init layers.
LAYER_PATTERN = r"(?:[0-9a-f]{64}|[0-9a-z]{25})(?:-init)?"
LAYER_NAME = re.compile(rf"^{LAYER_PATTERN}$")
# More orphans than this share of all layer folders means the reference read is
# broken (e.g. a changed Docker storage layout): delete nothing.
MAX_ORPHAN_SHARE = 0.9


def _read(path: Path) -> str:
    try:
        return path.read_text().strip()
    except OSError:
        return ""


def layerdb_references(docker_root: Path) -> set[str]:
    """overlay2 folder names that Docker's layer store records for images and containers."""
    base = docker_root / "image/overlay2/layerdb"
    if not (base / "sha256").is_dir():
        raise RuntimeError(f"Docker layer database not found under {base}")
    found: set[str] = set()
    for sub in ("sha256", "mounts"):
        folder = base / sub
        if not folder.is_dir():
            continue
        for entry in folder.iterdir():
            for name in ("cache-id", "mount-id", "init-id"):
                value = _read(entry / name)
                if value:
                    found.add(value)
    return found


def inspect_references() -> set[str]:
    """overlay2 folder names in the GraphDriver data of every image and container."""
    found: set[str] = set()
    for listing, inspect in ((["docker", "image", "ls", "-aq", "--no-trunc"], "image"),
                             (["docker", "ps", "-aq", "--no-trunc"], "container")):
        ids = subprocess.run(listing, capture_output=True, text=True, timeout=120, check=True).stdout.split()
        if not ids:
            continue
        data = subprocess.run(["docker", inspect, "inspect", "--format", "{{json .GraphDriver.Data}}", *sorted(set(ids))],
                              capture_output=True, text=True, timeout=300, check=True).stdout
        found.update(re.findall(rf"/overlay2/({LAYER_PATTERN})/", data))
    return found


def buildkit_references(docker_root: Path, names: set[str]) -> set[str]:
    """Layer folder names that BuildKit's metadata (databases, executor state) mentions.

    Matched by exact name, since BuildKit's snapshot ids reuse the folder names.
    Content blobs (compressed layer archives) never name folders and are skipped.
    """
    found: set[str] = set()
    base = docker_root / "buildkit"
    for path in sorted(base.rglob("*")):
        if not path.is_file() or path.is_relative_to(base / "content"):
            continue
        try:
            data = path.read_bytes()
        except OSError as error:
            raise RuntimeError(f"Cannot read BuildKit state {path}: {error}") from error
        found.update(name for name in names - found if name.encode() in data)
    return found


def with_lower_layers(docker_root: Path, references: set[str]) -> set[str]:
    """references plus every folder a referenced folder stacks on (its ``lower`` chain)."""
    overlay = docker_root / "overlay2"
    by_short = {}
    for entry in overlay.iterdir():
        short = _read(entry / "link") if entry.is_dir() else ""
        if short:
            by_short[short] = entry.name
    kept, pending = set(references), list(references)
    while pending:
        lower = _read(overlay / pending.pop() / "lower")
        for part in filter(None, lower.split(":")):
            name = by_short.get(part.removeprefix("l/"))
            if name and name not in kept:
                kept.add(name)
                pending.append(name)
    return kept


def _newest_mtime(folder: Path) -> float:
    times = [folder.lstat().st_mtime]
    for child in ("diff", "work", "link", "lower", "merged"):
        path = folder / child
        if os.path.lexists(path):
            times.append(path.lstat().st_mtime)
    return max(times)


def _tree_bytes(path: Path) -> int:
    total, pending = 0, [path]
    while pending:
        current = pending.pop()
        try:
            info = current.lstat()
        except OSError:
            continue
        total += info.st_blocks * 512
        if stat.S_ISDIR(info.st_mode):
            try:
                pending.extend(current.iterdir())
            except OSError:
                continue
    return total


def orphan_layers(docker_root: Path, references: set[str], now: float,
                  min_age_days: float = ORPHAN_MIN_AGE_DAYS) -> tuple[list[dict], int]:
    """(orphans older than the minimum age, number of layer folders)."""
    overlay = docker_root / "overlay2"
    folders = [entry for entry in overlay.iterdir() if entry.name != "l" and entry.is_dir()]
    cutoff = now - min_age_days * 86400
    orphans = []
    for folder in folders:
        if folder.name in references or not LAYER_NAME.match(folder.name):
            continue
        newest = _newest_mtime(folder)
        if newest > cutoff:
            continue
        orphans.append({"name": folder.name, "bytes": _tree_bytes(folder),
                        "age_days": round((now - newest) / 86400, 1)})
    return sorted(orphans, key=lambda item: -item["age_days"]), len(folders)


def remove_layer(docker_root: Path, name: str) -> None:
    folder = docker_root / "overlay2" / name
    short = _read(folder / "link")
    shutil.rmtree(folder)
    if short and "/" not in short:
        link = docker_root / "overlay2/l" / short
        if link.is_symlink() and os.readlink(link).endswith(f"/{name}/diff"):
            link.unlink()


def oversized_logs(docker_root: Path, cap: int | None = None, total_cap: int | None = None) -> list[dict]:
    """Logs to truncate: every one above cap, then the largest until the rest fits in total_cap."""
    cap = LOG_CAP_BYTES if cap is None else cap
    total_cap = LOGS_TOTAL_CAP_BYTES if total_cap is None else total_cap
    logs = sorted(({"path": str(path), "bytes": path.stat().st_size}
                   for path in (docker_root / "containers").glob("*/*-json.log")),
                  key=lambda item: (-item["bytes"], item["path"]))
    total = sum(item["bytes"] for item in logs)
    chosen = []
    for item in logs:
        if item["bytes"] > cap or total > total_cap:
            chosen.append(item)
            total -= item["bytes"]
    return chosen


def run(apply: bool, docker_root: Path = DOCKER_ROOT, now: float | None = None,
        references: set[str] | None = None) -> dict:
    now = time.time() if now is None else now
    names = {entry.name for entry in (docker_root / "overlay2").iterdir()
             if entry.name != "l" and entry.is_dir()}
    if references is None:
        references = layerdb_references(docker_root) | inspect_references()
        references |= buildkit_references(docker_root, names)
    references = with_lower_layers(docker_root, references)
    if not references:
        raise RuntimeError("No referenced Docker layers found; refusing to treat every layer as orphaned")
    orphans, total = orphan_layers(docker_root, references, now)
    unreferenced = len(names - references)
    if total and unreferenced / total > MAX_ORPHAN_SHARE:
        raise RuntimeError(f"{unreferenced} of {total} layer folders look unreferenced; refusing to delete")
    report = {"apply": apply, "at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime(now)),
              "layer_folders": total, "referenced": len(references),
              "orphans": len(orphans), "orphan_bytes": sum(item["bytes"] for item in orphans),
              "removed_layers": 0, "removed_bytes": 0, "failures": [],
              "logs": oversized_logs(docker_root), "journal": None}
    if apply:
        for item in orphans:
            try:
                remove_layer(docker_root, item["name"])
            except OSError as error:
                report["failures"].append({"layer": item["name"], "error": str(error)[:200]})
                continue
            report["removed_layers"] += 1
            report["removed_bytes"] += item["bytes"]
        for item in report["logs"]:
            os.truncate(item["path"], 0)
        journal = subprocess.run(["journalctl", f"--vacuum-size={JOURNAL_CAP}"],
                                 capture_output=True, text=True, timeout=300)
        report["journal"] = {"returncode": journal.returncode, "output": (journal.stderr or journal.stdout)[-300:]}
    report["docker_dirs"] = {name: _tree_bytes(docker_root / name)
                             for name in ("overlay2", "volumes", "containers", "buildkit", "image")
                             if (docker_root / name).is_dir()}
    report["largest_orphans"] = orphans[:10]
    return report


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("command", nargs="?", choices=("report", "apply"), default="report")
    parser.add_argument("--docker-root", type=Path, default=DOCKER_ROOT)
    parser.add_argument("--report", type=Path, default=REPORT_PATH)
    args = parser.parse_args(argv)
    if os.geteuid() != 0:
        print("Must run as root (installed as /usr/local/sbin/openmates-host-disk-root).", file=sys.stderr)
        return 1
    report = run(args.command == "apply", args.docker_root)
    args.report.parent.mkdir(parents=True, exist_ok=True, mode=0o755)
    temporary = args.report.with_suffix(".tmp")
    temporary.write_text(json.dumps(report, indent=1))
    temporary.chmod(0o644)
    temporary.replace(args.report)
    print(json.dumps({key: value for key, value in report.items() if key != "largest_orphans"}, indent=1))
    return 1 if report["failures"] else 0


if __name__ == "__main__":
    sys.exit(main())
