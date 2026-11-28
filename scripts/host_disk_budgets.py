"""Per-category disk budgets, enforced oldest first (TASK-7646, owner decision 2026-11-17).

Runs inside the disk coordinator's ``host`` cleanup kind (scripts/host_disk_cleanup.py),
which the coordinator schedules every hour and every 30 min from 75% used, so cleanup
starts long before the 10 GiB floor. For each budgeted category that is over its
target, whole units are removed least recently used first until it fits again. The
target is the approved cap, or PRESSURE_SHARE of it once the disk is at
PRESSURE_PERCENT or more.

| category | unit | protected |
|---|---|---|
| rust (25 GB) | one cargo target folder (OpenMates checkouts, sibling projects, /tmp), or one subfolder of the shared cache root | a cargo/rustc process names it or works in its worktree; any process works in its sibling project; used in the last hour |
| ci_artifacts (10 GB) | one run under test-results/ci-runs, logs/ci-runs, logs/ci-candidates | a non-terminal CI job references it; changed in the last hour |
| scratchpads (6 GB, 2 GB per chat) | one entry of a chat's scratch folder | open or in use; changed in the last 6 h |
| worktrees (15 GB) | node_modules or .svelte-kit of an agent worktree, or its downloaded CI evidence and runtime scratch (top-level test-results/, .runtime/) | a process works in the worktree; a file in it changed in the last 12 h |

Everything removed is rebuildable (build output, downloaded CI results, installed
dependencies, scratch files); source, worktrees themselves, WIP and recovery
archives are never units. Docker images and build cache share one 20 GB budget in
scripts/docker-cleanup.sh; container logs and the journal are capped by the root
tool (scripts/host_disk_root.py). Sizes and budgets: scripts/host_disk_usage.py.
"""

from __future__ import annotations

from dataclasses import dataclass
import glob
import os
from pathlib import Path
import shutil
import time

import host_disk_usage as usage
import resource_budget

PRESSURE_PERCENT = 75.0
PRESSURE_SHARE = 0.8
RUST_IDLE_SECONDS = 3600
CI_IDLE_SECONDS = 3600
SCRATCH_IDLE_SECONDS = 6 * 3600
WORKTREE_IDLE_SECONDS = 12 * 3600
# Emergency: free space below resource_budget.CLEANUP_TARGET_FREE (TASK-5181). Caps
# drop to half and idle windows shrink, so the budgets free space before the 10 GiB
# floor instead of keeping everything touched in the last hours. In-use protections
# (cargo, processes in a worktree or project, live CI jobs) never change.
EMERGENCY_SHARE = 0.5
EMERGENCY_IDLE_SECONDS = {"rust": 900, "ci_artifacts": 900, "worktrees": 4 * 3600, "scratchpads": 3600}
SCRATCH_PER_CHAT = 2 * usage.GB
SHARED_RUST_ROOT = usage.HOME / ".cache" / "openmates-rust-target"
DEPENDENCY_NAMES = frozenset({"node_modules", ".svelte-kit"})
# Top-level worktree folders that only hold downloaded CI results and runtime scratch.
# Without them the worktrees budget could never get under its cap (TASK-5181).
WORKTREE_SCRATCH_NAMES = ("test-results", ".runtime")


@dataclass
class Unit:
    path: Path
    last_used: float
    group: str = ""
    owner: Path | None = None


def _within(path: str, root: str) -> bool:
    return path == root or path.startswith(root.rstrip("/") + "/")


def _mtime(path: Path) -> float:
    try:
        return path.lstat().st_mtime
    except OSError:
        return 0.0


def _recent_mtime(path: Path, depth: int = 2) -> float:
    """Newest mtime of path and its entries down to depth (cargo touches deps/ and .fingerprint/)."""
    newest, level = _mtime(path), [path]
    for _ in range(depth):
        following = []
        for folder in level:
            try:
                entries = list(os.scandir(folder))
            except OSError:
                continue
            for entry in entries:
                try:
                    newest = max(newest, entry.stat(follow_symlinks=False).st_mtime)
                    if entry.is_dir(follow_symlinks=False):
                        following.append(Path(entry.path))
                except OSError:
                    continue
        level = following
    return newest


def _deep_mtime(path: Path) -> float:
    newest, pending = 0.0, [path]
    while pending:
        current = pending.pop()
        try:
            info = current.lstat()
        except OSError:
            continue
        newest = max(newest, info.st_mtime)
        if current.is_dir() and not current.is_symlink():
            try:
                pending.extend(current.iterdir())
            except OSError:
                continue
    return newest


def _worktree_of(path: str, roots: list[str]) -> Path | None:
    for root in roots:
        if _within(path, root):
            return Path(root)
    return None


def rust_units(projects: Path) -> list[Unit]:
    roots = usage.worktree_roots(projects) + [str(projects / "OpenMates")]
    siblings = usage.other_project_roots(projects)
    units = []
    for path in usage.rust_paths(projects):
        folder = Path(path)
        children = [child for child in folder.iterdir() if child.is_dir() and not child.is_symlink()] \
            if folder == SHARED_RUST_ROOT else [folder]
        for child in children:
            sibling = _worktree_of(str(child), siblings)
            owner = sibling or _worktree_of(str(child), roots)
            group = "sibling" if sibling else ""
            # Incremental caches are often half a target; they go before whole targets.
            for incremental in incremental_dirs(child):
                units.append(Unit(incremental, _recent_mtime(incremental), group=group, owner=owner))
            units.append(Unit(child, _recent_mtime(child), group=group, owner=owner))
    return units


def incremental_dirs(target: Path, depth: int = 4) -> list[Path]:
    """Cargo `incremental` folders inside one target folder (any profile or triple)."""
    found, level = [], [target]
    for _ in range(depth):
        following = []
        for folder in level:
            try:
                entries = [Path(entry.path) for entry in os.scandir(folder)
                           if entry.is_dir(follow_symlinks=False)]
            except OSError:
                continue
            for entry in entries:
                (found if entry.name == "incremental" else following).append(entry)
        level = following
    return sorted(found)


def ci_units(repository: Path) -> list[Unit]:
    units = []
    for base in ("test-results/ci-runs", "logs/ci-runs", "logs/ci-candidates"):
        folder = repository / base
        if folder.is_dir():
            units += [Unit(entry, _mtime(entry)) for entry in folder.iterdir() if not entry.is_symlink()]
    return units


def scratch_units(scratch_root: Path) -> list[Unit]:
    """Entries of every chat's scratch folders: <root>/<project>/<chat>/<folder>/<entry>."""
    units = []
    for entry in glob.glob(f"{scratch_root}/*/*/*/*"):
        path = Path(entry)
        if not path.is_symlink():
            units.append(Unit(path, _deep_mtime(path), group=str(path.parent.parent)))
    return units


def _worktree_activity(worktree: Path) -> float:
    """Last change anywhere in a worktree's own files (dependency and build folders left out).

    The session ledger's last_active and the git index lag behind a chat that edits
    files, so file mtimes decide.
    """
    newest = _mtime(worktree)
    for current, dirs, files in os.walk(worktree):
        dirs[:] = [name for name in dirs if name not in DEPENDENCY_NAMES and name not in usage.PRUNE_NAMES
                   and name != "target" and not os.path.islink(os.path.join(current, name))]
        for name in files:
            newest = max(newest, _mtime(Path(current) / name))
    return newest


def dependency_units(projects: Path, max_depth: int = 4) -> list[Unit]:
    units = []
    for root in usage.worktree_roots(projects):
        worktree = Path(root)
        activity = _worktree_activity(worktree)
        for name in WORKTREE_SCRATCH_NAMES:
            scratch = worktree / name
            if scratch.is_dir() and not scratch.is_symlink():
                units.append(Unit(scratch, max(activity, _deep_mtime(scratch)), owner=worktree))
        base = root.rstrip("/").count("/")
        for current, dirs, _files in os.walk(root):
            for name in [name for name in dirs if name in DEPENDENCY_NAMES]:
                units.append(Unit(Path(current) / name, activity, owner=worktree))
            dirs[:] = [] if current.count("/") - base >= max_depth else [
                name for name in dirs if name not in DEPENDENCY_NAMES and name not in usage.PRUNE_NAMES
                and name != "target" and not os.path.islink(os.path.join(current, name))]
    return units


def _size(path: Path) -> int:
    if path.is_dir() and not path.is_symlink():
        return usage.du_bytes(str(path))
    try:
        return path.lstat().st_blocks * 512
    except OSError:
        return 0


def _remove(path: Path) -> None:
    if path.is_dir() and not path.is_symlink():
        shutil.rmtree(path)
    else:
        path.unlink()


def trim(units: list[Unit], total: int, target: int, *, apply: bool, now: float, idle: float,
         protected, report: dict, category: str, size=None) -> int:
    """Remove units least recently used first until total <= target; returns the new total."""
    size = size or _size
    for unit in sorted(units, key=lambda item: (item.path.name != "incremental", item.last_used)):
        if total <= target:
            break
        if apply and not unit.path.exists():
            continue  # removed with an enclosing unit earlier in this pass
        if now - unit.last_used < idle:
            report["skipped"]["recent"] += 1
            continue
        reason = protected(unit)
        if reason:
            report["skipped"][reason] = report["skipped"].get(reason, 0) + 1
            continue
        bytes_ = size(unit.path)
        if apply:
            try:
                _remove(unit.path)
            except PermissionError:
                report["skipped"]["permission"] += 1
                continue
            except OSError as error:
                report["failures"].append({"path": str(unit.path), "error": type(error).__name__})
                continue
        report["deleted"].append({"path": str(unit.path), "category": category, "bytes": bytes_})
        total -= bytes_
    return total


def enforce(repository: Path, *, apply: bool, in_use: list[str], cargo: list[str],
            references: set[str] | None, now: float | None = None,
            scratch_root: Path | None = None, measure=None) -> dict:
    """Bring every budgeted category to its target; returns what was (or would be) removed."""
    now = time.time() if now is None else now
    projects = repository.parent
    scratch_root = scratch_root or Path(f"/tmp/claude-{os.getuid()}")
    disk = usage.filesystem(repository)
    pressure = disk["percent"] >= PRESSURE_PERCENT
    emergency = disk.get("available", resource_budget.CLEANUP_TARGET_FREE) < resource_budget.CLEANUP_TARGET_FREE
    share = EMERGENCY_SHARE if emergency else PRESSURE_SHARE if pressure else 1.0

    def idle_for(category: str, normal: float) -> float:
        return EMERGENCY_IDLE_SECONDS[category] if emergency else normal
    cats = {cat.name: cat for cat in usage.categories(projects) if cat.cap}
    totals = (measure or (lambda chosen: {name: value["bytes"]
                                          for name, value in usage.measure_paths(chosen).items()}))(
        tuple(cats.values()))
    report = {"pressure": pressure, "emergency": emergency, "percent": disk["percent"], "share": share,
              "categories": {},
              "deleted": [], "skipped": {"recent": 0, "in_use": 0, "permission": 0}, "failures": []}

    def busy(unit: Unit) -> str | None:
        prefix = str(unit.path)
        return "in_use" if any(_within(item, prefix) for item in in_use) else None

    def cargo_busy(unit: Unit) -> str | None:
        prefix, owner = str(unit.path), str(unit.owner) if unit.owner else None
        if any(_within(item, prefix) or (owner and _within(item, owner)) for item in cargo):
            return "cargo_running"
        if unit.group == "sibling" and owner and any(_within(item, owner) for item in in_use):
            return "in_use"  # a chat or dev server works in that project: keep its build output
        return busy(unit)

    def worktree_busy(unit: Unit) -> str | None:
        return "in_use" if any(_within(item, str(unit.owner)) for item in in_use) else None

    def ci_busy(unit: Unit) -> str | None:
        return "referenced" if unit.path.name in (references or ()) else busy(unit)

    plans = [("rust", lambda: rust_units(projects), idle_for("rust", RUST_IDLE_SECONDS), cargo_busy),
             ("ci_artifacts", lambda: ci_units(repository), idle_for("ci_artifacts", CI_IDLE_SECONDS), ci_busy),
             ("worktrees", lambda: dependency_units(projects), idle_for("worktrees", WORKTREE_IDLE_SECONDS),
              worktree_busy)]
    if references is None:
        plans = [plan for plan in plans if plan[0] != "ci_artifacts"]
        report["skipped"]["queue_unreadable"] = 1
    for name, units, idle, protected in plans:
        total, target = totals.get(name, 0), int(cats[name].cap * share)
        after = trim(units(), total, target, apply=apply, now=now, idle=idle, protected=protected,
                     report=report, category=name) if total > target else total
        report["categories"][name] = {"before": total, "after": after, "target": target}

    # Scratchpads: every chat down to its own share first, then the whole category.
    units = scratch_units(scratch_root)
    total, target = totals.get("scratchpads", 0), int(cats["scratchpads"].cap * share)
    before = total
    for group in sorted({unit.group for unit in units}):
        members = [unit for unit in units if unit.group == group]
        held = usage.du_bytes(group)
        if held > SCRATCH_PER_CHAT * share:
            left = trim(members, held, int(SCRATCH_PER_CHAT * share), apply=apply, now=now,
                        idle=idle_for("scratchpads", SCRATCH_IDLE_SECONDS), protected=busy, report=report, category="scratchpads")
            total -= held - left
    if total > target:
        remaining = [unit for unit in units if unit.path.exists() or not apply]
        removed = {item["path"] for item in report["deleted"]}
        total = trim([unit for unit in remaining if str(unit.path) not in removed], total, target,
                     apply=apply, now=now, idle=idle_for("scratchpads", SCRATCH_IDLE_SECONDS), protected=busy, report=report,
                     category="scratchpads")
    report["categories"]["scratchpads"] = {"before": before, "after": total, "target": target}
    report["reclaimed_bytes"] = sum(item["bytes"] for item in report["deleted"])
    return report
