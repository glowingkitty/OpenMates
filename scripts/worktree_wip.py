"""Work-in-progress safety for session worktrees: nothing lives only in a dirty checkout.

Before every dev-to-main pull request the release-readiness gate used to find dozens of
worktrees with uncommitted work whose chats had ended or been stopped (TASK-9700). This
module keeps that work safe and visible:

  snapshot   commits a worktree's uncommitted state (tracked changes and untracked,
             non-ignored files) to the session-owned ref ``refs/openmates/wip/<session>``
             in the shared object store. A temporary index is used, so the worktree, its
             index and its HEAD are never touched. The ref survives the worktree's
             removal, archiving and the chat's end. When a private WIP remote is
             configured the ref is pushed there too; the public ``origin`` is refused,
             because WIP has passed none of the deploy gates (secrets, private data).
  unfinished which session worktrees hold files whose content is not on the target
             (``origin/dev``): dirty files equal to dev are already landed and do not count.
  park       the owning chat records why its unfinished work must wait (for example an
             answer from the owner). A parked worktree is preserved by its snapshot and is
             not woken; the readiness gate lists it as parked instead of blocking on it,
             until the worktree changes again.
  sweep      snapshots every dirty session worktree and writes ``status.json`` (every 30
             minutes from a systemd timer, scripts/worktree-wip-setup.sh).
  nightly    sweep, then the release-readiness gate, written to ``readiness.json`` for the
             daily meeting, then resumes the stopped owner chats of unparked unfinished
             work (at most a few per night, once per worktree state) with a finish prompt.

The Stop hook (.claude/hooks/wip-snapshot.sh) snapshots the chat's worktree at the end of
every turn, and the chat lifecycle (scripts/claude_idle_chats.py) wakes a chat with
unfinished work once before it stops it, snapshotting it when the chat cannot finish.
State lives in ``<canonical checkout>/logs/worktree-wip/``.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import subprocess
import sys
import tempfile
from datetime import datetime, timezone
from pathlib import Path

SCRIPT_ROOT = Path(__file__).resolve().parents[1]
WIP_REF_PREFIX = "refs/openmates/wip/"
TARGET_REF = "origin/dev"
MAX_FILE_BYTES = 25 * 1024 * 1024  # larger files are listed as skipped, never committed
# Outputs that deploy rebuilds; a lane never lands them, so they are not unfinished work.
GENERATED_PREFIXES = ("specifications/generated/",)
GENERATED_FILES = frozenset(
    f"docs/migration/rust/{name}.yml" for name in ("overview", "web-app", "shared-client", "cli", "sdk")
)
NIGHTLY_MAX_WAKES = 3
GIT_TIMEOUT = 120


def canonical_root(repo_root: Path = SCRIPT_ROOT) -> Path:
    """The main checkout for a linked worktree, else repo_root (state lives there)."""
    dot_git = repo_root / ".git"
    if dot_git.is_file():
        text = dot_git.read_text(encoding="utf-8").strip()
        if text.startswith("gitdir:"):
            gitdir = Path(text.split(":", 1)[1].strip())
            if gitdir.parent.name == "worktrees":
                return gitdir.parent.parent.parent
    return repo_root


def state_dir() -> Path:
    override = os.environ.get("OPENMATES_WORKTREE_WIP_DIR")
    return Path(override) if override else canonical_root() / "logs" / "worktree-wip"


def sessions_file() -> Path:
    override = os.environ.get("OPENMATES_SESSIONS_FILE")
    return Path(override) if override else canonical_root() / ".claude" / "sessions.json"


def _utc(ts: float | None = None) -> str:
    moment = datetime.fromtimestamp(ts, timezone.utc) if ts is not None else datetime.now(timezone.utc)
    return moment.strftime("%Y-%m-%dT%H:%M:%SZ")


def _git(path: Path, *args: str, env: dict | None = None, check: bool = True, data: bytes | None = None
         ) -> subprocess.CompletedProcess[bytes]:
    result = subprocess.run(["git", "-C", str(path), *args], capture_output=True, input=data,
                            env=env, timeout=GIT_TIMEOUT)
    if check and result.returncode != 0:
        raise RuntimeError(f"git {' '.join(args[:3])} failed in {path}: {result.stderr.decode(errors='replace')[-300:]}")
    return result


def _read_json(path: Path, default):
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except FileNotFoundError:
        return default


def _write_json(path: Path, data) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_name(f".{path.name}.{os.getpid()}.tmp")
    tmp.write_text(json.dumps(data, indent=1, sort_keys=True) + "\n", encoding="utf-8")
    os.replace(tmp, path)


# ---------------------------------------------------------------------------
# Session worktrees and their unfinished files.
# ---------------------------------------------------------------------------

def session_worktrees(data: dict | None = None) -> list[dict]:
    """Lane worktrees from sessions.json: session id, owning chat, task, path."""
    data = _read_json(sessions_file(), {}) if data is None else data
    rows = []
    for session_id, session in sorted((data.get("sessions") or {}).items()):
        worktree = session.get("worktree") if isinstance(session, dict) else None
        if not isinstance(worktree, dict) or not worktree.get("path"):
            continue
        path = Path(str(worktree["path"]))
        if not (path / ".git").exists():
            continue
        rows.append({"session_id": session_id, "chat_id": str(session.get("agent_task_id") or ""),
                     "task": str(session.get("task") or "")[:160], "path": str(path)})
    return rows


def dirty_files(path: Path) -> list[str]:
    """Tracked files changed against HEAD plus untracked, non-ignored files."""
    out = _git(path, "status", "--porcelain=v1", "-z", "--untracked-files=all").stdout.decode(errors="surrogateescape")
    files, parts, index = [], out.split("\0"), 0
    while index < len(parts):
        entry = parts[index]
        index += 1
        if len(entry) < 4:
            continue
        files.append(entry[3:])
        if entry[0] in "RC":  # a rename/copy record is followed by its source path
            index += 1
    return sorted(set(files))


def _generated(name: str) -> bool:
    return name.startswith(GENERATED_PREFIXES) or name in GENERATED_FILES


def unfinished_files(path: Path, target_ref: str = TARGET_REF) -> list[str]:
    """Dirty files whose current content differs from target_ref (generated outputs excluded)."""
    candidates = [name for name in dirty_files(path) if not _generated(name)]
    if not candidates:
        return []
    target: dict[str, str] = {}
    listing = _git(path, "ls-tree", "-r", "-z", target_ref, "--", *candidates, check=False).stdout.decode(
        errors="surrogateescape")
    for record in filter(None, listing.split("\0")):
        meta, name = record.split("\t", 1)
        target[name] = meta.split()[2]
    present = [name for name in candidates if (path / name).is_file() and not (path / name).is_symlink()]
    hashes = _git(path, "hash-object", "--stdin-paths", data="\n".join(present).encode()).stdout.decode().split() \
        if present else []
    current = dict(zip(present, hashes))
    return [name for name in candidates if current.get(name) != target.get(name)]


def unfinished(target_ref: str = TARGET_REF, rows: list[dict] | None = None) -> list[dict]:
    """Session worktrees with unfinished files, each with its parked state."""
    parked = load_parked()
    result = []
    for row in session_worktrees() if rows is None else rows:
        try:
            files = unfinished_files(Path(row["path"]), target_ref)
        except (OSError, RuntimeError) as exc:
            result.append({**row, "files": [], "error": str(exc)[:200], "parked": None})
            continue
        if files:
            result.append({**row, "files": files, "parked": parked_entry(row["session_id"], Path(row["path"]), parked)})
    return result


def unfinished_by_chat(target_ref: str = TARGET_REF) -> dict[str, list[dict]]:
    by_chat: dict[str, list[dict]] = {}
    for entry in unfinished(target_ref):
        if entry.get("chat_id"):
            by_chat.setdefault(entry["chat_id"], []).append(entry)
    return by_chat


# ---------------------------------------------------------------------------
# Snapshots.
# ---------------------------------------------------------------------------

def wip_ref(session_id: str) -> str:
    safe = "".join(ch if ch.isalnum() or ch in "-_" else "-" for ch in session_id)[:64] or "unknown"
    return WIP_REF_PREFIX + safe


def worktree_tree(path: Path) -> tuple[str, list[str], str]:
    """(tree of the worktree's current state, files skipped as too large, HEAD) via a temporary index."""
    head = _git(path, "rev-parse", "HEAD").stdout.decode().strip()
    files = dirty_files(path)
    skipped = [name for name in files if (path / name).is_file() and (path / name).stat().st_size > MAX_FILE_BYTES]
    keep = [name for name in files if name not in skipped]
    with tempfile.TemporaryDirectory(prefix="wip-index-") as scratch:
        env = {**os.environ, "GIT_INDEX_FILE": str(Path(scratch) / "index")}
        _git(path, "read-tree", "HEAD", env=env)
        if keep:
            _git(path, "update-index", "--add", "--remove", "-z", "--stdin", env=env,
                 data=b"\0".join(os.fsencode(name) for name in keep) + b"\0")
        tree = _git(path, "write-tree", env=env).stdout.decode().strip()
    return tree, skipped, head


def _ref_commit(path: Path, ref: str) -> str:
    result = _git(path, "rev-parse", "--verify", "--quiet", ref + "^{commit}", check=False)
    return result.stdout.decode().strip() if result.returncode == 0 else ""


def snapshot(row: dict, reason: str, *, push: bool = True) -> dict:
    """Commit the worktree's uncommitted state to its WIP ref; no-op when nothing changed."""
    path, session_id = Path(row["path"]), row["session_id"]
    ref = wip_ref(session_id)
    tree, skipped, head = worktree_tree(path)
    if tree == _git(path, "rev-parse", "HEAD^{tree}").stdout.decode().strip():
        return {"session_id": session_id, "ref": ref, "state": "clean"}
    previous = _ref_commit(path, ref)
    if previous and _git(path, "rev-parse", previous + "^{tree}").stdout.decode().strip() == tree:
        return {"session_id": session_id, "ref": ref, "state": "unchanged", "commit": previous, "tree": tree,
                "skipped": skipped}
    parents = ["-p", head] + (["-p", previous] if previous and previous != head else [])
    message = (f"wip: session {session_id} ({reason})\n\n{row.get('task') or ''}\n\n"
               f"Chat: {row.get('chat_id') or 'unknown'}\nWorktree: {path.name}\n"
               + (f"Skipped (over {MAX_FILE_BYTES // 2**20} MiB): {', '.join(skipped[:20])}\n" if skipped else ""))
    env = {**os.environ, "GIT_AUTHOR_NAME": "OpenMates WIP snapshot", "GIT_AUTHOR_EMAIL": "wip@example.org",
           "GIT_COMMITTER_NAME": "OpenMates WIP snapshot", "GIT_COMMITTER_EMAIL": "wip@example.org"}
    commit = _git(path, "commit-tree", tree, *parents, env=env, data=message.encode()).stdout.decode().strip()
    _git(path, "update-ref", "-m", f"wip snapshot ({reason})", ref, commit, previous or "0" * 40)
    result = {"session_id": session_id, "ref": ref, "state": "saved", "commit": commit, "tree": tree,
              "skipped": skipped, "pushed": ""}
    if push:
        result["pushed"] = push_ref(path, ref)
    return result


def wip_remote() -> str:
    config = _read_json(state_dir() / "config.json", {})
    return str(os.environ.get("OPENMATES_WIP_REMOTE") or config.get("wip_remote") or "")


def _remote_url(path: Path, remote: str) -> str:
    result = _git(path, "remote", "get-url", remote, check=False)
    return result.stdout.decode().strip() if result.returncode == 0 else remote


def _normalized(url: str) -> str:
    return url.strip().lower().removesuffix("/").removesuffix(".git").replace("git@github.com:", "https://github.com/")


def push_ref(path: Path, ref: str) -> str:
    """Push the WIP ref to the configured private remote; '' when none is configured."""
    remote = wip_remote()
    if not remote:
        return ""
    if _normalized(_remote_url(path, remote)) == _normalized(_remote_url(path, "origin")):
        return "refused: the WIP remote is the public origin"
    result = _git(path, "push", "--quiet", "--force", remote, f"{ref}:{ref}", check=False)
    return "pushed" if result.returncode == 0 else f"push failed: {result.stderr.decode(errors='replace')[-160:]}"


def snapshot_for_chat(chat_id: str, reason: str) -> list[dict]:
    return [snapshot(row, reason) for row in session_worktrees() if row["chat_id"] == chat_id
            and dirty_files(Path(row["path"]))]


# ---------------------------------------------------------------------------
# Parking.
# ---------------------------------------------------------------------------

def load_parked() -> dict[str, dict]:
    return _read_json(state_dir() / "parked.json", {})


def park(session_id: str, reason: str) -> dict:
    """Record why the session's unfinished work waits; valid while the worktree state is unchanged."""
    rows = {row["session_id"]: row for row in session_worktrees()}
    if session_id not in rows:
        raise SystemExit(f"worktree_wip: session {session_id} has no worktree")
    if not reason.strip():
        raise SystemExit("worktree_wip: --reason is required")
    saved = snapshot(rows[session_id], "parked")
    entry = {"reason": " ".join(reason.split())[:300], "at": _utc(), "tree": saved.get("tree", ""),
             "ref": saved["ref"], "commit": saved.get("commit", "")}
    parked = load_parked()
    parked[session_id] = entry
    _write_json(state_dir() / "parked.json", parked)
    return entry


def parked_entry(session_id: str, path: Path, parked: dict[str, dict] | None = None) -> dict | None:
    """The park record while the worktree still has the parked state, else None."""
    entry = (load_parked() if parked is None else parked).get(session_id)
    if not entry:
        return None
    try:
        tree, _skipped, _head = worktree_tree(path)
    except (OSError, RuntimeError):
        return None
    return entry if tree == entry.get("tree") else None


# ---------------------------------------------------------------------------
# Sweep, nightly readiness and owner wakes.
# ---------------------------------------------------------------------------

def finish_prompt(entries: list[dict]) -> str:
    """Wake text for unfinished entries (from unfinished(): files list, or status.json: count plus sample)."""
    parts = []
    for entry in entries:
        sample = entry.get("sample") or entry["files"][:5]
        count = entry["files"] if isinstance(entry["files"], int) else len(entry["files"])
        worktree = entry.get("worktree") or Path(entry["path"]).name
        more = f" (+{count - len(sample)} more)" if count > len(sample) else ""
        parts.append(f"session {entry['session_id']} ({worktree}: {count} files not on dev: "
                     f"{', '.join(sample)}{more}; WIP snapshot {wip_ref(entry['session_id'])})")
    return ("[Host note from the worktree WIP safety (scripts/worktree_wip.py), not from Marco: your work is not "
            "finished: " + "; ".join(parts) + ". Done means committed, tested and deployed to dev. Finish it now: "
            "run the proving checks and deploy with sessions.py deploy. If it must wait (for example on an answer "
            "from the owner), write what remains in your Task and run: python3 scripts/worktree_wip.py park "
            "--session <id> --reason \"<why>\". If it is superseded or abandoned, say so in your Task.]")


def sweep(reason: str = "periodic") -> dict:
    """Snapshot every dirty session worktree and write status.json."""
    unfinished_rows = unfinished()
    snapshots = []
    for entry in unfinished_rows:
        if entry.get("error"):
            continue
        try:
            snapshots.append(snapshot(entry, reason))
        except (OSError, RuntimeError) as exc:
            snapshots.append({"session_id": entry["session_id"], "state": "failed", "error": str(exc)[:200]})
    by_id = {item["session_id"]: item for item in snapshots}
    status = {"at": _utc(), "target_ref": TARGET_REF, "remote": wip_remote() or "",
              "unfinished": [{"session_id": e["session_id"], "chat_id": e["chat_id"], "task": e["task"],
                              "worktree": Path(e["path"]).name, "files": len(e["files"]),
                              "sample": e["files"][:5], "parked": e.get("parked"), "error": e.get("error", ""),
                              "snapshot": by_id.get(e["session_id"], {})} for e in unfinished_rows]}
    _write_json(state_dir() / "status.json", status)
    return status


def _chat_transcript(chat_id: str) -> Path | None:
    projects = Path(os.environ.get("CLAUDE_HOME") or Path.home() / ".claude") / "projects"
    matches = sorted(projects.glob(f"*/{chat_id}.jsonl")) if chat_id else []
    return matches[0] if matches else None


def _running_chat_ids() -> set[str]:
    sessions = Path(os.environ.get("CLAUDE_HOME") or Path.home() / ".claude") / "sessions"
    ids = set()
    for record in sessions.glob("*.json"):
        try:
            data = json.loads(record.read_text(encoding="utf-8"))
            os.kill(int(data.get("pid") or record.stem), 0)
        except (OSError, ValueError):
            continue
        ids.add(str(data.get("sessionId") or ""))
    return ids


def readiness() -> dict:
    """Run the release-readiness gate against origin/dev; returns its JSON report summary."""
    root = canonical_root()
    subprocess.run(["git", "-C", str(root), "fetch", "--quiet", "origin", "dev"], capture_output=True, timeout=300)
    result = subprocess.run([sys.executable, str(root / "scripts" / "sessions.py"), "worktree", "release-readiness",
                             "--target", TARGET_REF, "--format", "json"], capture_output=True, text=True,
                            timeout=1800, cwd=root)
    try:
        report = json.loads(result.stdout)
    except ValueError:
        return {"at": _utc(), "ready": False, "error": (result.stderr or result.stdout)[-400:]}
    return {"at": _utc(), "ready": bool(report.get("ready")), "target_commit": report.get("target_commit", ""),
            "blocking": report.get("blocking_worktrees", []), "parked": report.get("parked_worktrees", []),
            "blocked_deploys": report.get("blocked_deploys", []), "inspected": len(report.get("items", []))}


def wake_owners(status: dict, *, limit: int = NIGHTLY_MAX_WAKES, launch=None) -> list[dict]:
    """Resume stopped owner chats of unparked unfinished work, once per worktree state."""
    marks_path = state_dir() / "woken.json"
    marks = _read_json(marks_path, {})
    running = _running_chat_ids()
    by_chat: dict[str, list[dict]] = {}
    for entry in status.get("unfinished", []):
        if entry.get("parked") or entry.get("error") or not entry.get("chat_id"):
            continue
        by_chat.setdefault(entry["chat_id"], []).append(entry)
    results = []
    for chat_id, entries in by_chat.items():
        key = chat_id + ":" + hashlib.sha256(json.dumps(
            [e["snapshot"].get("tree", "") for e in entries]).encode()).hexdigest()[:16]
        if key in marks:
            continue
        if chat_id in running:
            results.append({"chat_id": chat_id, "state": "running", "note": "the chat lifecycle wakes it before stopping it"})
            continue
        if _chat_transcript(chat_id) is None:
            results.append({"chat_id": chat_id, "state": "no_transcript", "note": "owner chat is gone: list for the owner"})
            continue
        if len([r for r in results if r["state"] == "resumed"]) >= limit:
            results.append({"chat_id": chat_id, "state": "deferred", "note": f"over the nightly limit of {limit}"})
            continue
        outcome = (launch or _resume_chat)(chat_id, finish_prompt(entries))
        results.append({"chat_id": chat_id, "state": "resumed" if outcome == "ok" else "failed", "note": outcome})
        if outcome == "ok":
            marks[key] = _utc()
    _write_json(marks_path, dict(sorted(marks.items())[-500:]))
    return results


def _resume_chat(chat_id: str, prompt: str) -> str:
    sys.path.insert(0, str(Path(__file__).resolve().parent))
    import claude_dispatch  # noqa: E402  (sibling script, imported only when a wake is due)

    try:
        return claude_dispatch.resume_chat(chat_id, prompt)
    except claude_dispatch.DispatchError as exc:
        return str(exc)[:200]


def nightly() -> dict:
    status = sweep("nightly")
    report = {**status, "readiness": readiness()}
    report["wakes"] = wake_owners(status)
    _write_json(state_dir() / "readiness.json", report)
    return report


def briefing_lines(path: Path | None = None) -> list[str]:
    """Daily meeting lines: readiness verdict and unfinished worktree work (logs/worktree-wip/readiness.json)."""
    data = _read_json(path or state_dir() / "readiness.json", None)
    if not data:
        return ["_Worktree readiness unavailable: the nightly check (scripts/worktree_wip.py nightly) has not run yet._", ""]
    gate = data.get("readiness") or {}
    rows = data.get("unfinished") or []
    open_rows = [row for row in rows if not row.get("parked")]
    lines = [f"_Release readiness (dev→main) at {data['at'][:16]} UTC: "
             f"{'ready' if gate.get('ready') else 'NOT ready'}; {len(gate.get('blocking') or [])} blocking worktrees, "
             f"{len(open_rows)} with unfinished work, {len(rows) - len(open_rows)} parked._", ""]
    wakes = {w["chat_id"]: w for w in data.get("wakes") or []}
    for row in open_rows[:15]:
        wake = wakes.get(row["chat_id"], {})
        lines.append(f"- `{row['session_id']}` {row['task'][:90]} — {row['files']} files not on dev, chat "
                     f"`{(row['chat_id'] or '?')[:8]}` {wake.get('state', 'not woken')}")
    for row in [row for row in rows if row.get("parked")][:10]:
        lines.append(f"- parked `{row['session_id']}` {row['task'][:70]} — {row['parked'].get('reason', '')[:120]}")
    return lines + [""]


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    sub = parser.add_subparsers(dest="command", required=True)
    snap = sub.add_parser("snapshot", help="commit one worktree's uncommitted state to its WIP ref")
    who = snap.add_mutually_exclusive_group(required=True)
    who.add_argument("--session")
    who.add_argument("--chat")
    snap.add_argument("--reason", default="manual")
    snap.add_argument("--quiet", action="store_true")
    parked = sub.add_parser("park", help="record why a session's unfinished work must wait")
    parked.add_argument("--session", required=True)
    parked.add_argument("--reason", required=True)
    sub.add_parser("sweep", help="snapshot every dirty session worktree, write status.json")
    sub.add_parser("nightly", help="sweep, readiness gate, wake stopped owners")
    listing = sub.add_parser("list", help="session worktrees with unfinished work")
    listing.add_argument("--json", action="store_true")
    args = parser.parse_args(argv)
    if args.command == "snapshot":
        if args.chat:
            results = snapshot_for_chat(args.chat, args.reason)
        else:
            rows = [row for row in session_worktrees() if row["session_id"] == args.session]
            if not rows:
                raise SystemExit(f"worktree_wip: session {args.session} has no worktree")
            results = [snapshot(rows[0], args.reason)]
        if not args.quiet:
            print(json.dumps(results, indent=1))
        return 0
    if args.command == "park":
        print(json.dumps(park(args.session, args.reason), indent=1))
        return 0
    if args.command == "sweep":
        status = sweep()
        print(f"{len(status['unfinished'])} session worktrees with unfinished work; snapshots in {WIP_REF_PREFIX}*")
        return 0
    if args.command == "nightly":
        report = nightly()
        print(json.dumps({key: report[key] for key in ("at", "readiness", "wakes")}, indent=1))
        return 0
    rows = unfinished()
    if args.json:
        print(json.dumps(rows, indent=1))
    else:
        for row in rows:
            state = f"parked: {row['parked']['reason']}" if row.get("parked") else row.get("error") or "unfinished"
            print(f"{row['session_id']:8} chat {row['chat_id'][:8] or '?':8} {len(row['files']):4} files  {state}  {row['task'][:70]}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
