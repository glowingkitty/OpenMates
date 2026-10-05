"""Shared, fail-closed disk reservations and dry-run inventory for managed CI bytes.

The inventory owns only extracted successful CI payloads. Worktree expiry owns
worktree deletion; candidate patches and dependency copies are reported but kept.
No background cleaner or implicit deletion runs from admission.
"""

from __future__ import annotations

from contextlib import contextmanager
from datetime import datetime
import fcntl
import hashlib
import json
import os
from pathlib import Path
import re
import shutil
import sqlite3
import stat
import subprocess
import time
import uuid

GIB = 1024 ** 3
MIN_FREE = 30 * GIB
MAX_USED_PERCENT = 85
RESULT_AGE_SECONDS = 14 * 24 * 3600
RESULT_ID = re.compile(r"[A-Za-z0-9_-]{6,100}")
RETAINED_RESULT_NAMES = frozenset({
    "receipt.json", "ci-cleanup.json", "codex-evidence.json", "codex-evidence.lock",
    "ci-environment.json", "ci-results.json", "ci-startup-phases.json",
    "ci-runtime-images.json", "ci-artifacts.json",
})


def _control(root: Path) -> Path:
    return root / ".claude" / "resource-budget"


def _start_time(pid: int) -> str:
    try:
        return Path(f"/proc/{pid}/stat").read_text().rsplit(") ", 1)[1].split()[19]
    except (OSError, IndexError):
        return ""


@contextmanager
def _locked(root: Path):
    directory = _control(root)
    directory.mkdir(parents=True, exist_ok=True, mode=0o700)
    with (directory / "budget.lock").open("a+") as handle:
        fcntl.flock(handle, fcntl.LOCK_EX)
        try:
            yield directory
        finally:
            fcntl.flock(handle, fcntl.LOCK_UN)


def _reservations(directory: Path) -> list[dict]:
    live = []
    for path in directory.glob("reservation-*.json"):
        try:
            item = json.loads(path.read_text())
            if (item["pid"] > 0 and item["start"]
                    and _start_time(item["pid"]) == item["start"]
                    and type(item["bytes"]) is int and item["bytes"] >= 0):
                live.append(item)
            else:
                path.unlink()
        except (OSError, ValueError, KeyError, TypeError):
            # An unreadable reservation may still own bytes. Never ignore it.
            raise RuntimeError(f"Uncertain disk reservation: {path}")
    return live


def admission(root: Path, requested: int, *, min_free: int = MIN_FREE,
              max_used_percent: int = MAX_USED_PERCENT, usage=None,
              reserved: int = 0) -> dict:
    usage = usage or shutil.disk_usage(root)
    free_after = usage.free - reserved - requested
    used_after = usage.used + reserved + requested
    percent = 100 * used_after / usage.total if usage.total else 100
    return {"allowed": requested >= 0 and free_after >= min_free and percent < max_used_percent,
            "free_after": free_after, "used_percent_after": percent,
            "reserved_bytes": reserved, "requested_bytes": requested}


@contextmanager
def reserve(root: Path, amount: int, *, min_free: int = MIN_FREE,
            max_used_percent: int = MAX_USED_PERCENT):
    """Reserve allocation headroom across local processes until owner exit.

    A PID and Linux process start tick fence stale reservations, including a
    crashed owner and PID reuse. All admission callers use the same root lock.
    """
    if amount < 0:
        raise ValueError("Negative disk reservation")
    root = root.resolve()
    token = uuid.uuid4().hex
    for attempt in range(2):
        with _locked(root) as directory:
            existing = sum(item["bytes"] for item in _reservations(directory))
            decision = admission(root, amount, min_free=min_free,
                                 max_used_percent=max_used_percent, reserved=existing)
            if decision["allowed"]:
                start = _start_time(os.getpid())
                if not start:
                    raise RuntimeError("Cannot establish disk reservation owner")
                path = directory / f"reservation-{token}.json"
                path.write_text(json.dumps({"pid": os.getpid(), "start": start,
                                            "bytes": amount, "created": time.time()}))
                break
        if attempt or not _auto_enabled(root):
            raise RuntimeError("Disk budget exceeded: " + json.dumps(decision, sort_keys=True))
        # The admin has reviewed a dry-run manifest and explicitly enabled this
        # owner. Persist each automatic dry-run before touching eligible bytes.
        manifest = inventory(root)
        stamp = f"auto-dry-run-{int(time.time())}-{uuid.uuid4().hex}.json"
        (_control(root) / stamp).write_text(json.dumps(manifest, indent=2, sort_keys=True))
        cleanup(root, manifest=manifest)
    try:
        yield decision
    finally:
        with _locked(root):
            path.unlink(missing_ok=True)


def _bytes(path: Path) -> tuple[int, bool]:
    """Count allocated file bytes without following links; report unsafe types."""
    total = 0
    safe = True
    paths = [path]
    while paths:
        current = paths.pop()
        try:
            info = current.lstat()
            if stat.S_ISDIR(info.st_mode):
                paths.extend(current.iterdir())
            elif stat.S_ISREG(info.st_mode):
                total += info.st_blocks * 512
            else:
                total += info.st_blocks * 512
                safe = False
        except OSError:
            safe = False
    return total, safe


def _queue_rows(root: Path) -> list[dict] | None:
    path = root / "logs/ci-coordinator/queue.sqlite3"
    if not path.is_file():
        return None
    try:
        with sqlite3.connect(f"file:{path}?mode=ro", uri=True, timeout=2) as db:
            db.row_factory = sqlite3.Row
            return [dict(row) for row in db.execute("SELECT id,source,state,owner FROM jobs")]
    except sqlite3.Error:
        return None


def _active_owners(root: Path) -> set[str] | None:
    path = root / ".claude/sessions.json"
    if not path.exists():
        return set()
    try:
        sessions = json.loads(path.read_text())["sessions"]
        if not isinstance(sessions, dict):
            return None
        return {str(key) for key, session in sessions.items()
                if isinstance(session, dict) and
                ((session.get("worktree") or {}).get("status") in
                 {"active", "merged", "changes_pending", "recovery_needed"}
                 or _recent_session(session))}
    except (OSError, ValueError, KeyError, AttributeError):
        return None


def _recent_session(session: dict) -> bool:
    """Protect recently active Tasks even before their workspace is created."""
    try:
        stamp = datetime.fromisoformat(str(session["last_active"]).replace("Z", "+00:00"))
        return stamp.tzinfo is not None and time.time() - stamp.timestamp() < 7 * 86400
    except (KeyError, ValueError, TypeError):
        return False


def _runtime_leases(root: Path) -> dict:
    """Report local leases; remote dev-stack leases do not own CI payload paths."""
    backend = os.environ.get("OPENMATES_COORDINATION_BACKEND", "").strip().lower()
    remote_config = Path.home() / ".config/openmates/engineering-control-plane.env"
    remote = backend == "api" or (backend != "local" and remote_config.is_file())
    authority = "persistent_dev_stack_unenumerated" if remote else "local"
    path = root / ".claude/sessions.json"
    if not path.exists():
        return {"known": True, "authority": authority,
                "test_lease_count": 0, "active_operation_count": 0}
    try:
        infrastructure = json.loads(path.read_text())["infrastructure"]
        leases = infrastructure.get("test_leases", {})
        operations = infrastructure.get("docker_operations", [])
        if not isinstance(leases, dict) or not isinstance(operations, list):
            raise ValueError("Invalid runtime lease inventory")
        return {"known": True, "authority": authority, "test_lease_count": len(leases),
                "active_operation_count": sum(
                    isinstance(item, dict) and item.get("status") in
                    {"queued", "admitted", "draining_tests", "restarting", "verifying"}
                    for item in operations)}
    except (OSError, ValueError, KeyError, AttributeError, TypeError):
        return {"known": False, "authority": authority,
                "test_lease_count": None, "active_operation_count": None}


def _payload_snapshot(paths: list[Path], base: Path) -> str:
    digest = hashlib.sha256()
    for path in paths:
        descendants = [path, *sorted(path.rglob("*"))] if path.is_dir() else [path]
        for entry in descendants:
            info = entry.lstat()
            if not (stat.S_ISREG(info.st_mode) or stat.S_ISDIR(info.st_mode)):
                raise RuntimeError("Unsafe result payload type")
            digest.update(json.dumps([str(entry.relative_to(base)), info.st_mode,
                                      info.st_ino, info.st_size, info.st_mtime_ns],
                                     separators=(",", ":")).encode())
    return digest.hexdigest()


def _evidence_complete(directory: Path) -> bool:
    path = directory / "codex-evidence.json"
    if not path.is_file():
        return False
    try:
        records = json.loads(path.read_text())["records"]
        return isinstance(records, dict) and all(
            record.get("recording") != "available"
            or (record.get("upload") == "uploaded" and record.get("delivery") == "delivered")
            for record in records.values()
        )
    except (OSError, ValueError, KeyError, AttributeError):
        return False


def _integrated_candidate(path: Path, root: Path, rows: list[dict] | None,
                          active_owners: set[str] | None, now: float) -> bool:
    """A patch is redundant only when its exact commit is retained on dev."""
    if rows is None or active_owners is None or not re.fullmatch(r"[0-9a-f]{40}", path.name):
        return False
    manifest, patch = path / "manifest.json", path / "candidate.patch"
    try:
        if set(path.iterdir()) != {manifest, patch} or not patch.is_file() or patch.is_symlink():
            return False
        item = json.loads(manifest.read_text())
        expiry = datetime.fromisoformat(item["artifact_expires_at"])
        if (expiry.tzinfo is None or now - expiry.timestamp() < RESULT_AGE_SECONDS
                or item.get("source") != path.name or item.get("session") in active_owners
                or Path(item.get("local_patch", "")).resolve() != patch.resolve()
                or hashlib.sha256(patch.read_bytes()).hexdigest() != item.get("patch_sha256")
                or any(row["source"] == path.name and row["state"] not in
                       {"success", "failure", "cancelled"} for row in rows)):
            return False
        check = subprocess.run(["git", "merge-base", "--is-ancestor", path.name, "dev"],
                               cwd=root, capture_output=True, timeout=5)
        return check.returncode == 0
    except (OSError, ValueError, KeyError, TypeError, subprocess.TimeoutExpired):
        return False


def inventory(root: Path, *, now: float | None = None) -> dict:
    """Return explicit dry-run paths and bytes; ambiguity always protects data."""
    root = root.resolve()
    now = time.time() if now is None else now
    rows = _queue_rows(root)
    jobs = {row["id"]: row for row in rows or []}
    active_owners = _active_owners(root)
    pending_sources = {row["source"] for row in rows or []
                       if row["state"] not in {"success", "failure", "cancelled"}}
    leases = _runtime_leases(root)
    runtime_busy = (not leases["known"] or bool(leases["test_lease_count"])
                    or bool(leases["active_operation_count"]))
    entries = []
    categories = {
        "worktrees": root / ".openmates-agent-worktrees",
        "candidates": root / "logs/ci-candidates",
        "results": root / "test-results/ci-runs",
    }
    for category, base in categories.items():
        if not base.is_dir():
            continue
        for path in sorted(base.iterdir()):
            if not path.is_dir() or path.is_symlink():
                continue
            size, safe = _bytes(path)
            item = {"category": category, "path": str(path), "bytes": size,
                    "action": "retain", "reason": "owner_or_recovery_state"}
            if category == "worktrees":
                item["reason"] = "worktree_expiry_is_sole_owner"
                deps = sum(_bytes(dep)[0] for dep in path.rglob("node_modules")
                           if dep.is_dir() and not dep.is_symlink()
                           and not any(part == "node_modules" for part in dep.relative_to(path).parts[:-1]))
                item["dependency_bytes"] = deps
            elif category == "candidates":
                item["reason"] = "candidate_source_or_recovery_patch"
                if safe and not runtime_busy and _integrated_candidate(path, root, rows, active_owners, now):
                    patch = path / "candidate.patch"
                    item.update(action="remove_candidate_patch", reason="exact_commit_integrated_on_dev",
                                payload_paths=[str(patch)],
                                payload_info=[{"path": str(patch), "size": patch.stat().st_size,
                                               "mtime_ns": patch.stat().st_mtime_ns,
                                               "inode": patch.stat().st_ino}],
                                payload_snapshot=_payload_snapshot([patch], path),
                                reclaim_bytes=_bytes(patch)[0])
            elif not safe:
                item["reason"] = "unsafe_or_unreadable_payload"
            elif rows is None or active_owners is None or not RESULT_ID.fullmatch(path.name):
                item["reason"] = "unknown_queue_or_result_identity"
            else:
                row = jobs.get(path.name)
                receipt = path / "receipt.json"
                try:
                    proof = json.loads(receipt.read_text())
                    identity_ok = row and proof.get("id") == path.name and proof.get("source_commit") == row["source"]
                    age_ok = now - receipt.stat().st_mtime >= RESULT_AGE_SECONDS
                except (OSError, ValueError):
                    identity_ok = age_ok = False
                    proof = {}
                if not identity_ok:
                    item["reason"] = "unverified_result_identity"
                elif row["state"] != "success" or proof.get("state") != "success":
                    item["reason"] = "non_success_or_active_job"
                elif row["owner"] in active_owners:
                    item["reason"] = "active_session_owner"
                elif row["source"] in pending_sources:
                    item["reason"] = "pending_source_consumer"
                elif runtime_busy:
                    item["reason"] = "runtime_lease_or_operation"
                elif not age_ok:
                    item["reason"] = "retention_window"
                elif not _evidence_complete(path):
                    item["reason"] = "evidence_delivery_pending"
                else:
                    payload = [child for child in path.rglob("*")
                               if child.is_file() and child.name not in RETAINED_RESULT_NAMES]
                    if any(child.is_symlink() for child in payload):
                        item["reason"] = "unsafe_payload"
                    elif payload:
                        payload_info = [
                            {"path": str(child), "size": child.stat().st_size,
                             "mtime_ns": child.stat().st_mtime_ns, "inode": child.stat().st_ino}
                            for child in payload
                        ]
                        item.update(action="remove_result_payload", reason="terminal_delivered_success",
                                    payload_paths=[str(child) for child in payload],
                                    payload_info=payload_info,
                                    payload_snapshot=_payload_snapshot(payload, path),
                                    reclaim_bytes=sum(_bytes(child)[0] for child in payload))
                    else:
                        item["reason"] = "compact_receipt_only"
            entries.append(item)
    return {"dry_run": True, "root": str(root), "entries": entries,
            "runtime_leases": leases, "pending_ci_source_count": len(pending_sources),
            "totals": {category: sum(item["bytes"] for item in entries if item["category"] == category)
                       for category in categories},
            "reclaim_bytes": sum(item.get("reclaim_bytes", 0) for item in entries)}


def cleanup(root: Path, *, manifest: dict) -> dict:
    """Apply only an unchanged, explicit manifest under the shared budget lock."""
    root = root.resolve()
    if manifest.get("dry_run") is not True or manifest.get("root") != str(root):
        raise ValueError("Expected exact dry-run disk manifest")
    with _locked(root):
        current = inventory(root)
        allowed = {"remove_result_payload", "remove_candidate_patch"}
        approved = {entry["path"]: entry for entry in manifest.get("entries", [])
                    if entry.get("action") in allowed}
        fresh = {entry["path"]: entry for entry in current["entries"]
                 if entry.get("action") in allowed}
        removed = []
        for path, item in approved.items():
            if (path not in fresh or item.get("payload_paths") != fresh[path].get("payload_paths")
                    or item.get("action") != fresh[path].get("action")
                    or item.get("payload_info") != fresh[path].get("payload_info")
                    or item.get("payload_snapshot") != fresh[path].get("payload_snapshot")
                    or item.get("reclaim_bytes") != fresh[path].get("reclaim_bytes")):
                continue
            for name in item["payload_paths"]:
                target = Path(name)
                if (not target.resolve().is_relative_to(Path(path).resolve())
                        or target.is_symlink()):
                    raise RuntimeError("Unsafe result payload path")
                if target.is_file():
                    target.unlink()
                else:
                    raise RuntimeError("Changed result payload type")
            removed.append(path)
        return {"removed": removed, "reclaimed_estimate_bytes": sum(approved[path]["reclaim_bytes"] for path in removed)}


def enable_auto(root: Path, *, manifest: dict) -> None:
    """Opt in only after reviewing a fresh matching dry-run manifest."""
    root = root.resolve()
    if manifest.get("dry_run") is not True or manifest.get("root") != str(root):
        raise ValueError("Expected exact dry-run disk manifest")
    with _locked(root) as directory:
        current = inventory(root)
        reviewed = [(item["path"], item.get("action"), item.get("payload_snapshot"))
                    for item in manifest.get("entries", [])]
        fresh = [(item["path"], item.get("action"), item.get("payload_snapshot"))
                 for item in current["entries"]]
        if reviewed != fresh:
            raise RuntimeError("Disk inventory changed since review; generate a new manifest")
        (directory / "cleanup-enabled.json").write_text(json.dumps({
            "enabled_at": time.time(), "reviewed_reclaim_bytes": manifest.get("reclaim_bytes", 0),
        }))


def _auto_enabled(root: Path) -> bool:
    try:
        record = json.loads((_control(root) / "cleanup-enabled.json").read_text())
        return type(record.get("enabled_at")) in {int, float}
    except (OSError, ValueError, AttributeError):
        return False


def disable_auto(root: Path) -> None:
    with _locked(root.resolve()) as directory:
        (directory / "cleanup-enabled.json").unlink(missing_ok=True)
