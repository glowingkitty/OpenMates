#!/usr/bin/env python3
"""Hourly size log of the dev host disk, per category (TASK-7646).

``record`` measures every category, appends one line to
``logs/host-disk/usage.jsonl`` and keeps the last RETENTION_HOURS lines; the
``openmates-host-disk-usage.timer`` user timer (scripts/host-disk-usage-setup.sh)
runs it every hour at idle IO priority. ``status`` prints the newest record with
each category's budget and its growth over the last 24 h. The host-resources
guard (scripts/host_resources.py) names the largest growers in its 75% and 85%
disk alerts through :func:`growth_summary`.

Categories are measured in order; a path that lies inside a path of an earlier
category is subtracted from the later one (a worktree's ``target/`` counts as
rust, not as worktree). ``other`` is what the filesystem reports used minus all
measured categories. Docker numbers come from ``docker system df`` and, for what
only root can see (orphaned layers, container logs), from the weekly root report
of scripts/host_disk_root.py. Architecture:
docs/architecture/infrastructure/dev-host-resources.md (section "Disk budgets").
"""

from __future__ import annotations

import argparse
from collections.abc import Callable
from dataclasses import dataclass
import glob
import json
import os
from pathlib import Path
import re
import subprocess
import sys
import time

GB = 1000**3
GIB = 1024**3
HOME = Path.home()
SCRIPTS = Path(__file__).resolve().parent
RETENTION_HOURS = 24 * 60
DU_TIMEOUT = 900
ROOT_REPORT = Path("/var/lib/openmates-host-disk/report.json")


@dataclass(frozen=True)
class Category:
    """One budgeted disk category: where it lives and its approved cap (bytes, None = no cap)."""

    name: str
    label: str
    patterns: tuple[str, ...]
    cap: int | None
    exclude: tuple[str, ...] = ()
    finder: Callable[[], list[str]] | None = None


# Folders never searched for nested cargo targets (large, and never hold one).
PRUNE_NAMES = frozenset({"node_modules", ".git", ".svelte-kit", ".venv", "venv", "__pycache__", ".pnpm-store"})
CARGO_MARKERS = ("CACHEDIR.TAG", ".rustc_info.json")


def is_cargo_target(path: str, files: list[str] | None = None) -> bool:
    """Cargo writes .rustc_info.json and (newer versions) a CACHEDIR.TAG naming cargo into a target dir.

    ruff and pytest write CACHEDIR.TAG too, so the tag only counts when it names cargo.
    """
    files = os.listdir(path) if files is None else files
    if ".rustc_info.json" in files:
        return True
    if "CACHEDIR.TAG" not in files:
        return False
    try:
        with open(os.path.join(path, "CACHEDIR.TAG"), "rb") as tag:
            return b"created by cargo" in tag.read(512)
    except OSError:
        return False


def cargo_targets(roots: list[str], max_depth: int = 5) -> list[str]:
    """Cargo target folders under roots, at any depth up to max_depth."""
    found: list[str] = []
    for root in roots:
        base = root.rstrip("/").count("/")
        for current, dirs, files in os.walk(root):
            if current != root.rstrip("/") and any(marker in files for marker in CARGO_MARKERS) \
                    and is_cargo_target(current, files):
                found.append(current)
                dirs[:] = []
                continue
            if current.count("/") - base >= max_depth:
                dirs[:] = []
                continue
            dirs[:] = [name for name in dirs if name not in PRUNE_NAMES and not os.path.islink(os.path.join(current, name))]
    return sorted(found)


def worktree_roots(projects: Path) -> list[str]:
    repo = projects / "OpenMates"
    return sorted(glob.glob(f"{repo}/.openmates-agent-worktrees/*") + glob.glob(f"{repo}/.claude/worktrees/*"))


def rust_paths(projects: Path) -> list[str]:
    """Every Rust build output folder: shared caches, and cargo targets in checkouts and /tmp."""
    repo = projects / "OpenMates"
    caches = glob.glob(f"{HOME}/.cache/openmates-rust-*") + glob.glob(f"{HOME}/.cache/*-target")
    tmp = [path for path in glob.glob("/tmp/*") if os.path.isdir(path) and not os.path.islink(path)
           and os.stat(path).st_uid == os.getuid()]
    return sorted(set(caches) | set(cargo_targets([str(repo), *worktree_roots(projects)], 6))
                  | set(cargo_targets(tmp, 4)))


def projects_root() -> Path:
    """The folder that holds the canonical checkout and the shared runtime folders."""
    common = subprocess.run(["git", "-C", str(SCRIPTS), "rev-parse", "--path-format=absolute", "--git-common-dir"],
                            capture_output=True, text=True, check=True).stdout.strip()
    return Path(common).parent.parent


def categories(projects: Path) -> tuple[Category, ...]:
    repo = projects / "OpenMates"
    worktrees = (f"{repo}/.openmates-agent-worktrees/*", f"{repo}/.claude/worktrees/*")
    # Caps approved by the owner on 2026-11-17 (TASK-7646); steady state about 57% of 300 GB.
    return (
        Category("rust", "Rust build output", (), 25 * GB, finder=lambda: rust_paths(projects)),
        Category("ci_artifacts", "CI artifacts and test results",
                 (f"{repo}/logs/ci-runs", f"{repo}/logs/ci-candidates", f"{repo}/test-results",
                  f"{repo}/frontend/apps/web_app/test-results"), 10 * GB),
        Category("proof_recordings", "Dev-stack proof recordings and screenshots (proof cleanup)",
                 (f"{projects}/.openmates-runtime/product-stack/test-results",), None),
        Category("scratchpads", "Chat scratchpads", (f"/tmp/claude-{os.getuid()}",), 6 * GB),
        Category("worktrees", "Agent worktrees", worktrees, 15 * GB),
        Category("runtime", "Shared runtime folders", (f"{projects}/.openmates-runtime",), None),
        Category("toolchains", "Toolchain and package caches",
                 (f"{HOME}/.cache/ms-playwright", f"{HOME}/.npm", f"{HOME}/.local/share/pnpm", f"{HOME}/.cache/pnpm",
                  f"{HOME}/.cargo/registry", f"{HOME}/.cargo/git", f"{HOME}/.cache/pip", f"{HOME}/.rustup"), None),
        Category("checkout", "Canonical checkout (logs, node_modules, build output)",
                 (f"{repo}/*", f"{repo}/.[!.]*"), None, exclude=(f"{repo}/.openmates-agent-worktrees",)),
        Category("other_projects", "Other projects and recovery folders",
                 (f"{projects}/*", f"{projects}/.[!.]*"), None, exclude=(str(repo),)),
        Category("home_other", "Rest of the home folder (chat transcripts, caches)",
                 (f"{HOME}/*", f"{HOME}/.[!.]*"), None, exclude=(str(projects),)),
        Category("system_logs", "System logs outside the journal", ("/var/log",), None),
    )


DOCKER_CAPS = {"docker_images": 20 * GB, "docker_logs": 1 * GB, "journal": 1 * GB}


def du_bytes(path: str) -> int:
    """Disk blocks used under path on its filesystem (0 when it vanished)."""
    result = subprocess.run(["ionice", "-c3", "nice", "-n19", "du", "-sx", "-B1", path],
                            capture_output=True, text=True, timeout=DU_TIMEOUT, check=False)
    # du exits 1 for unreadable entries inside the tree but still prints the total.
    line = result.stdout.strip().splitlines()[-1:] or ["0"]
    return int(line[0].split()[0]) if line[0].split()[0].isdigit() else 0


def _inside(path: str, parents: list[str]) -> bool:
    return any(path == parent or path.startswith(parent.rstrip("/") + "/") for parent in parents)


def measure_paths(cats: tuple[Category, ...], du=du_bytes) -> dict[str, dict]:
    """Per category: bytes and the largest paths, nested earlier-category paths subtracted."""
    seen: dict[str, int] = {}
    result: dict[str, dict] = {}
    for cat in cats:
        listed = [path for pattern in cat.patterns for path in glob.glob(pattern)] + (cat.finder() if cat.finder else [])
        paths = sorted({path for path in listed
                        if os.path.isdir(path) and not os.path.islink(path) and path not in cat.exclude})
        paths = [path for path in paths if not _inside(path, [p for p in paths if p != path])]
        sizes = {}
        for path in paths:
            if path in seen:
                continue
            own = du(path) - sum(size for inner, size in seen.items() if _inside(inner, [path]))
            sizes[path] = max(own, 0)
        seen.update(sizes)
        largest = sorted(sizes.items(), key=lambda item: -item[1])[:5]
        result[cat.name] = {"bytes": sum(sizes.values()), "largest": [[path, size] for path, size in largest]}
    return result


_UNITS = {"B": 1, "KB": 1000, "MB": 1000**2, "GB": 1000**3, "TB": 1000**4,
          "KIB": 1024, "MIB": 1024**2, "GIB": 1024**3, "TIB": 1024**4, "K": 1024, "M": 1024**2, "G": 1024**3}


def parse_size(text: str) -> int:
    match = re.match(r"\s*([\d.]+)\s*([A-Za-z]*)", text)
    if not match:
        raise ValueError(f"Not a size: {text!r}")
    return int(float(match.group(1)) * _UNITS[(match.group(2) or "B").upper()])


def docker_usage() -> dict[str, int]:
    """Images, containers, volumes and build cache as Docker reports them."""
    result = subprocess.run(["docker", "system", "df", "--format", "json"],
                            capture_output=True, text=True, timeout=120, check=True)
    names = {"Images": "docker_images", "Build Cache": "docker_build_cache",
             "Local Volumes": "docker_volumes", "Containers": "docker_containers"}
    usage = {}
    for line in result.stdout.splitlines():
        row = json.loads(line)
        if row.get("Type") in names:
            usage[names[row["Type"]]] = parse_size(row["Size"])
    return usage


def journal_bytes() -> int:
    result = subprocess.run(["journalctl", "--disk-usage"], capture_output=True, text=True, timeout=60, check=True)
    match = re.search(r"take up ([\d.]+\s*[A-Za-z]+)", result.stdout + result.stderr)
    if not match:
        raise RuntimeError(f"Unexpected journalctl --disk-usage output: {result.stdout.strip()[:200]}")
    return parse_size(match.group(1))


def root_report(path: Path = ROOT_REPORT) -> dict:
    """The weekly root cleanup's report (orphaned layers, container logs), or {} before its first run."""
    try:
        return json.loads(path.read_text())
    except FileNotFoundError:
        return {}


def filesystem(path: Path) -> dict[str, float]:
    stat = os.statvfs(path)
    total = stat.f_blocks * stat.f_frsize
    available = stat.f_bavail * stat.f_frsize
    used = (stat.f_blocks - stat.f_bfree) * stat.f_frsize
    return {"total": total, "used": used, "available": available,
            "percent": round(100.0 * (total - available) / total, 1) if total else 0.0}


def record(directory: Path, projects: Path, now: float | None = None) -> dict:
    now = time.time() if now is None else now
    started = time.monotonic()
    cats = categories(projects)
    measured = measure_paths(cats)
    report = root_report()
    entry = {"at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime(now)), "ts": now,
             "disk": filesystem(projects), "categories": {name: value["bytes"] for name, value in measured.items()},
             "largest": {name: value["largest"] for name, value in measured.items()}}
    entry["categories"].update(docker_usage())
    entry["categories"]["journal"] = journal_bytes()
    if report:
        entry["categories"]["docker_logs"] = sum(item["bytes"] for item in report.get("logs", []))
        entry["categories"]["docker_orphan_layers"] = max(
            int(report.get("orphan_bytes") or 0) - int(report.get("removed_bytes") or 0), 0)
        entry["root_report"] = {key: report.get(key) for key in ("at", "orphans", "orphan_bytes", "removed_bytes")}
        docker_dirs = report.get("docker_dirs") or {}
        if "overlay2" in docker_dirs:
            # Layer data Docker's own accounting misses (orphans, container layers), as of the root run.
            entry["categories"]["docker_layers_unaccounted"] = max(int(docker_dirs["overlay2"]) - sum(
                entry["categories"].get(key, 0) for key in ("docker_images", "docker_containers",
                                                           "docker_build_cache", "docker_orphan_layers")), 0)
    # Root-report numbers are up to a week old; "other" stays an estimate.
    entry["categories"]["other"] = max(int(entry["disk"]["used"]) - sum(entry["categories"].values()), 0)
    entry["seconds"] = round(time.monotonic() - started, 1)
    append(directory, entry)
    return entry


def append(directory: Path, entry: dict) -> None:
    directory.mkdir(parents=True, exist_ok=True)
    path = directory / "usage.jsonl"
    lines = path.read_text().splitlines() if path.exists() else []
    lines = (lines + [json.dumps(entry, separators=(",", ":"))])[-RETENTION_HOURS:]
    temporary = path.with_suffix(".tmp")
    temporary.write_text("\n".join(lines) + "\n")
    temporary.replace(path)


def history(directory: Path) -> list[dict]:
    path = directory / "usage.jsonl"
    if not path.exists():
        return []
    return [json.loads(line) for line in path.read_text().splitlines() if line.strip()]


def growth(records: list[dict], hours: float = 24) -> dict[str, int]:
    """Bytes per category added since the record closest to `hours` before the newest one."""
    if len(records) < 2:
        return {}
    newest = records[-1]
    target = newest["ts"] - hours * 3600
    earlier = min(records[:-1], key=lambda item: abs(item["ts"] - target))
    return {name: size - earlier["categories"].get(name, 0) for name, size in newest["categories"].items()}


def caps(projects: Path) -> dict[str, int]:
    values = {cat.name: cat.cap for cat in categories(projects) if cat.cap}
    values.update(DOCKER_CAPS)
    return values


def growth_summary(directory: Path, projects: Path, limit: int = 3) -> str:
    """'largest growers in 24 h: rust +6.1 GB (31 GB, cap 25 GB), ...' for alerts; '' without history."""
    records = history(directory)
    delta = growth(records)
    if not delta:
        return ""
    newest = records[-1]["categories"]
    limits = caps(projects)
    parts = []
    for name, added in sorted(delta.items(), key=lambda item: -item[1])[:limit]:
        if added <= 0:
            break
        cap = f", cap {limits[name] / GB:.0f} GB" if name in limits else ""
        parts.append(f"{name} +{added / GB:.1f} GB ({newest[name] / GB:.1f} GB{cap})")
    over = [f"{name} {newest[name] / GB:.1f}/{cap / GB:.0f} GB" for name, cap in limits.items()
            if newest.get(name, 0) > cap]
    text = f"largest growers in 24 h: {', '.join(parts) or 'none'}"
    return text + (f"; over budget: {', '.join(over)}" if over else "")


def status(directory: Path, projects: Path) -> str:
    records = history(directory)
    if not records:
        return "No size record yet (logs/host-disk/usage.jsonl); run: host_disk_usage.py record"
    newest, delta, limits = records[-1], growth(records), caps(projects)
    disk = newest["disk"]
    lines = [f"{newest['at']}  disk {disk['percent']}% used, {disk['available'] / GIB:.0f} GiB available "
             f"(measured in {newest['seconds']} s)", f"{'category':22} {'size GB':>8} {'cap GB':>7} {'24 h GB':>8}"]
    for name, size in sorted(newest["categories"].items(), key=lambda item: -item[1]):
        cap = f"{limits[name] / GB:.0f}" if name in limits else "-"
        change = f"{delta[name] / GB:+.1f}" if name in delta else "-"
        flag = "  OVER" if name in limits and size > limits[name] else ""
        lines.append(f"{name:22} {size / GB:8.1f} {cap:>7} {change:>8}{flag}")
    return "\n".join(lines)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("command", choices=("record", "status"))
    parser.add_argument("--directory", type=Path, help="log folder (default: <canonical checkout>/logs/host-disk)")
    args = parser.parse_args(argv)
    projects = projects_root()
    directory = args.directory or projects / "OpenMates" / "logs" / "host-disk"
    if args.command == "record":
        entry = record(directory, projects)
        print(f"recorded {entry['at']}: {entry['disk']['percent']}% used, "
              f"{len(entry['categories'])} categories in {entry['seconds']} s")
    print(status(directory, projects))
    return 0


if __name__ == "__main__":
    sys.exit(main())
