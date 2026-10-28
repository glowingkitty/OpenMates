#!/usr/bin/env python3
"""Single elected host disk service and bounded owned-command execution.

The ledger and admission API are in disk_coordinator_state. This module is also
its stable public entry point for existing scripts and the foreground adapter.
"""

from __future__ import annotations

import argparse
from collections import Counter
from contextlib import contextmanager
import fcntl
import json
import os
from pathlib import Path
import signal
import shutil
import subprocess
import sys
import time
import uuid

try:
    from scripts import resource_budget as budget
    from scripts.disk_coordinator_state import (
        CoordinatorState,
        DiskWait,
        canonical_repository,
        configured,
        default_state,
        filesystem,
        group_alive,
        marker,
        _atomic,
        GRANT_SECONDS,
        CLEANUP_BACKOFF,
        RECOVERY_MARGIN,
        MIN_INODES,
        KINDS,
    )
except ModuleNotFoundError:
    import resource_budget as budget
    from disk_coordinator_state import (
        CoordinatorState,
        DiskWait,
        canonical_repository,
        configured,
        default_state,
        filesystem,
        group_alive,
        marker,
        _atomic,
        GRANT_SECONDS,
        CLEANUP_BACKOFF,
        RECOVERY_MARGIN,
        MIN_INODES,
        KINDS,
    )


__all__ = [
    "Coordinator",
    "DiskWait",
    "canonical_repository",
    "configured",
    "default_state",
    "filesystem",
    "group_alive",
    "marker",
    "GRANT_SECONDS",
    "CLEANUP_BACKOFF",
    "RECOVERY_MARGIN",
    "MIN_INODES",
    "KINDS",
    "owner_check",
    "run_command",
]


class Coordinator(CoordinatorState):
    @contextmanager
    def leadership(self):
        self.root.mkdir(parents=True, exist_ok=True, mode=0o700)
        with (self.root / "leader.lock").open("a+") as leader:
            fcntl.flock(leader, fcntl.LOCK_EX | fcntl.LOCK_NB)
            start = budget._start_time(os.getpid())
            if not start:
                raise RuntimeError("Cannot establish disk coordinator identity")
            self._leader = leader
            with self.db(write=True) as db:
                db.execute(
                    "UPDATE maintenance SET state='waiting' WHERE state='running'"
                )
            _atomic(self.root / "leader.json", {"pid": os.getpid(), "start": start})
            try:
                yield
            finally:
                (self.root / "leader.json").unlink(missing_ok=True)
                self._leader = None

    def _assert_leader(self):
        if self._leader is None or not self.available():
            raise RuntimeError("Only the elected disk coordinator may grant or clean")

    def enqueue_maintenance(self, repository, kind):
        if kind not in KINDS:
            raise ValueError("Unknown cleanup kind")
        repository = str(canonical_repository(repository))
        with self.db(write=True) as db:
            row = db.execute(
                "SELECT * FROM repositories WHERE path=? AND enabled=1", (repository,)
            ).fetchone()
            if not row or kind not in json.loads(row["maintenance"]):
                raise RuntimeError("Cleanup kind is not enabled for this repository")
            db.execute(
                "INSERT INTO maintenance VALUES (?,?,'waiting',?,'') ON CONFLICT(repository,kind) DO UPDATE SET state='waiting'",
                (repository, kind, self.clock()),
            )

    def _event(self, db, kind, detail):
        db.execute(
            "INSERT INTO events(created_at,kind,detail) VALUES (?,?,?)",
            (self.clock(), kind, json.dumps(detail, sort_keys=True)),
        )
        db.execute(
            "DELETE FROM events WHERE id <= (SELECT COALESCE(MAX(id),0)-500 FROM events)"
        )

    def _cleanup(self, repository, kind):
        self._assert_leader()
        if kind == "managed":
            if not budget._auto_enabled(Path(repository)):
                return {"retained": "managed cleanup has no reviewed opt-in"}
            manifest = budget.inventory(Path(repository), count_bytes=False)
            result = budget.cleanup(
                Path(repository), manifest=manifest, _coordinator_owned=True
            )
            result["protected_categories"] = dict(
                Counter(
                    entry["reason"]
                    for entry in manifest["entries"]
                    if entry["action"] == "retain"
                )
            )
            return result
        script = {
            "docker": "docker-cleanup.sh",
            "proof": "cleanup-proof-videos.sh",
        }.get(kind)
        command = (
            ["bash", str(Path(repository) / "scripts" / script)]
            if script
            else [
                sys.executable,
                str(Path(repository) / "scripts/sessions.py"),
                "worktree",
                "expire",
                "--max-age-hours",
                "96",
                "--format",
                "json",
            ]
        )
        environment = {
            **os.environ,
            "OPENMATES_DISK_STATE": str(self.root),
            "OPENMATES_DISK_OWNER_FD": str(self._leader.fileno()),
            "OPENMATES_DISK_OWNER_PID": str(os.getpid()),
        }
        # The child holds the same elected-owner lock even if its parent exits.
        result = subprocess.run(
            command,
            cwd=repository,
            env=environment,
            pass_fds=(self._leader.fileno(),),
            stdout=subprocess.PIPE if not script else subprocess.DEVNULL,
            stderr=subprocess.PIPE if not script else subprocess.DEVNULL,
            text=True,
            timeout=1200,
        )
        report = {"kind": kind, "returncode": result.returncode}
        if not script:
            try:
                if len(result.stdout) > 2 * 1024 * 1024:
                    raise ValueError("Worktree cleanup report exceeds diagnostic limit")
                detail = json.loads(result.stdout)
                report.update(
                    inspected=detail["inspected"],
                    deleted=detail["deleted"],
                    protected_live=len(detail.get("protected_live", [])),
                    protected_unresolved=len(detail.get("protected_unresolved", [])),
                    failures=detail.get("failures", []),
                )
            except (ValueError, TypeError, KeyError):
                report["error"] = "Worktree cleanup did not return a valid structured report"
        return report

    def tick(self, *, cleaner=None, recovery_margin=RECOVERY_MARGIN):
        self._assert_leader()
        cleaner = cleaner or self._cleanup
        now = self.clock()
        cleanup_jobs = []
        with self.db(write=True) as db:
            self._reconcile(db)
            db.execute(
                "DELETE FROM requests WHERE state IN ('complete','cancelled') AND updated_at<?",
                (now - 30 * 86400,),
            )
            enabled = {
                r["path"]: json.loads(r["maintenance"])
                for r in db.execute("SELECT * FROM repositories WHERE enabled=1")
            }
            for row in db.execute(
                "SELECT * FROM maintenance WHERE state='waiting'"
            ).fetchall():
                fs = filesystem(row["repository"])
                status = db.execute(
                    "SELECT next_cleanup FROM pressure WHERE filesystem=?", (fs,)
                ).fetchone()
                if (
                    status
                    and status[0] > now
                    and not any(filesystem(repo) == fs for repo, _ in cleanup_jobs)
                ):
                    continue
                if (
                    row["repository"] in enabled
                    and row["kind"] in enabled[row["repository"]]
                ):
                    cleanup_jobs.append((row["repository"], row["kind"]))
                    db.execute(
                        "UPDATE maintenance SET state='running' WHERE repository=? AND kind=?",
                        (row["repository"], row["kind"]),
                    )
                    db.execute(
                        "INSERT INTO pressure(filesystem,next_cleanup) VALUES (?,?) ON CONFLICT(filesystem) DO UPDATE SET next_cleanup=excluded.next_cleanup",
                        (fs, now + CLEANUP_BACKOFF),
                    )
            waiting = db.execute(
                "SELECT * FROM requests WHERE state='waiting' AND expires_at<=? ORDER BY created_at,id",
                (now,),
            ).fetchall()
            by_fs = {}
            for row in waiting:
                if row["repository"] in enabled:
                    by_fs.setdefault(row["filesystem"], []).append(row)
            for fs, rows in by_fs.items():
                db.execute(
                    "INSERT OR IGNORE INTO pressure(filesystem) VALUES (?)", (fs,)
                )
                status = db.execute(
                    "SELECT * FROM pressure WHERE filesystem=?", (fs,)
                ).fetchone()
                committed = db.execute(
                    "SELECT COALESCE(SUM(outstanding),0) FROM requests WHERE filesystem=? AND state IN ('granted','claimed')",
                    (fs,),
                ).fetchone()[0]
                usage = self.usage(rows[0]["repository"])
                pressure = bool(status["active"])
                protected = 0
                for row in rows:
                    decision = budget.admission(
                        Path(row["repository"]),
                        row["amount"],
                        min_free=row["min_free"] + (recovery_margin if pressure else 0),
                        max_used_percent=row["max_percent"],
                        usage=usage,
                        reserved=committed + protected,
                    )
                    if (
                        decision["allowed"]
                        and self.inodes(row["repository"]) >= row["min_inodes"]
                    ):
                        db.execute(
                            "UPDATE requests SET state='granted',grant_id=?,expires_at=?,updated_at=?,reason='',attempts=0 WHERE id=?",
                            (uuid.uuid4().hex, now + GRANT_SECONDS, now, row["id"]),
                        )
                        committed += row["outstanding"]
                        self._event(db, "grant", {"request_id": row["id"]})
                    else:
                        pressure = True
                        shortfall = max(
                            0,
                            row["min_free"]
                            + recovery_margin
                            + row["amount"]
                            + committed + protected
                            - usage.free,
                        )
                        # Percentage admission can be stricter than the byte
                        # floor (notably workspace creation). Report both.
                        percent_shortfall = max(0, int(usage.used + committed + protected + row['amount'] - usage.total * row['max_percent'] / 100) + 1)
                        shortfall = max(shortfall, percent_shortfall)
                        reason = f"Waiting for disk capacity: {shortfall} additional bytes needed; free={usage.free}, committed={committed}, protected={protected}, ceiling={row['max_percent']}%, inodes={self.inodes(row['repository'])}"
                        db.execute(
                            "UPDATE requests SET reason=?,attempts=attempts+1 WHERE id=?",
                            (reason, row["id"]),
                        )
                        if status["next_cleanup"] <= now:
                            for repo, kinds in enabled.items():
                                if filesystem(repo) == fs:
                                    cleanup_jobs.extend((repo, k) for k in kinds)
                        # Protect the oldest waiting peak, not its policy floor.
                        # A stricter workspace ceiling must not freeze every CI
                        # operation on this filesystem. Later grants still pass
                        # their own guards and leave this peak uncommitted.
                        if not protected and now - row["created_at"] >= 60:
                            protected = row["outstanding"]
                db.execute(
                    "UPDATE pressure SET active=?,last_free=?,next_cleanup=? WHERE filesystem=?",
                    (
                        int(pressure),
                        usage.free,
                        now + CLEANUP_BACKOFF
                        if status["next_cleanup"] <= now and pressure
                        else status["next_cleanup"],
                        fs,
                    ),
                )
            # Reset hysteresis after the queue has recovered.
            for row in db.execute(
                "SELECT filesystem FROM pressure WHERE active=1"
            ).fetchall():
                if not db.execute(
                    "SELECT 1 FROM requests WHERE filesystem=? AND state='waiting'",
                    (row[0],),
                ).fetchone():
                    db.execute(
                        "UPDATE pressure SET active=0 WHERE filesystem=?", (row[0],)
                    )
        results = []
        for repository, kind in dict.fromkeys(cleanup_jobs):
            try:
                result = cleaner(repository, kind)
            except (OSError, RuntimeError, subprocess.SubprocessError) as error:
                result = {"error": str(error)[:300]}
            with self.db(write=True) as db:
                self._event(
                    db,
                    "cleanup",
                    {"repository": repository, "kind": kind, **(result or {})},
                )
                db.execute(
                    "UPDATE maintenance SET state='complete',reason=? WHERE repository=? AND kind=?",
                    (json.dumps(result), repository, kind),
                )
            results.append({"repository": repository, "kind": kind, "result": result})
        return results


def run_command(repository, amount, operation, command, *, write_paths=()):
    """Monitor a newly owned subprocess; never suspend unrelated host work."""
    paths = [Path(p).resolve() for p in write_paths]
    initial = sum(budget._bytes(p)[0] for p in paths if p.exists())
    with budget.reserve(repository, amount, operation=operation) as lease:
        process = None
        coordinator = lease.get("coordinator")
        if coordinator is None:
            raise RuntimeError(
                "Owned command execution requires enabled coordinated admission"
            )
        reader, writer = os.pipe()
        try:
            with coordinator.db(write=True) as db:
                current = db.execute(
                    "SELECT * FROM requests WHERE id=? AND state='claimed'",
                    (lease["id"],),
                ).fetchone()
                if (
                    not current
                    or current["pid"] != os.getpid()
                    or current["start"] != budget._start_time(os.getpid())
                ):
                    raise RuntimeError(
                        "Cannot transfer another allocation owner's command"
                    )
                process = subprocess.Popen(
                    [
                        sys.executable,
                        str(Path(__file__).resolve()),
                        "child",
                        "--gate-fd",
                        str(reader),
                        "--",
                        *command,
                    ],
                    cwd=repository,
                    start_new_session=True,
                    pass_fds=(reader,),
                )
                start = budget._start_time(process.pid)
                if not start:
                    raise RuntimeError("Cannot establish child allocation identity")
                db.execute(
                    "UPDATE requests SET pid=?,start=?,owner_group=? WHERE id=?",
                    (process.pid, start, process.pid, lease["id"]),
                )
            # Only a committed child-owner record authorizes execution. A parent
            # crash before this byte closes the gate and the child exits unwritten.
            os.write(writer, b"1")
        except BaseException:
            if process is not None and process.poll() is None:
                process.kill()
                process.wait()
            raise
        finally:
            os.close(reader)
            os.close(writer)
        try:
            while process.poll() is None:
                usage = shutil.disk_usage(repository)
                allocated = max(
                    0, sum(budget._bytes(p)[0] for p in paths if p.exists()) - initial
                )
                if (
                    usage.free < budget.MIN_FREE
                    or os.statvfs(repository).f_favail < MIN_INODES
                    or allocated > amount
                ):
                    raise RuntimeError(
                        "Owned command stopped at its disk allocation limit; checkpoint before retry"
                    )
                # Keep the conservative peak while a separate process owns
                # writes; only that live owner may attest materialization.
                try:
                    return process.wait(timeout=2)
                except subprocess.TimeoutExpired:
                    pass
            return process.returncode
        finally:
            if process.poll() is None:
                os.killpg(process.pid, signal.SIGTERM)
                try:
                    process.wait(timeout=5)
                except subprocess.TimeoutExpired:
                    os.killpg(process.pid, signal.SIGKILL)
                    process.wait()


def owner_check(coordinator):
    try:
        fd = int(os.environ["OPENMATES_DISK_OWNER_FD"])
        pid = int(os.environ["OPENMATES_DISK_OWNER_PID"])
        info = os.fstat(fd)
        lock = (coordinator.root / "leader.lock").stat()
        record = json.loads((coordinator.root / "leader.json").read_text())
        if (
            (info.st_dev, info.st_ino) != (lock.st_dev, lock.st_ino)
            or record["pid"] != pid
            or not coordinator.available()
        ):
            return False
        fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
        return True
    except (OSError, ValueError, KeyError):
        return False


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "action",
        choices=(
            "enable",
            "disable",
            "serve",
            "status",
            "maintenance",
            "owner-check",
            "configured-check",
            "cancel",
            "run",
            "child",
        ),
    )
    parser.add_argument(
        "--repository", type=Path, default=Path(__file__).resolve().parents[1]
    )
    parser.add_argument("--state-root", type=Path)
    parser.add_argument("--kind", choices=KINDS)
    parser.add_argument("--cleanup", action="append", choices=KINDS)
    parser.add_argument("--request")
    parser.add_argument("--bytes", type=int)
    parser.add_argument("--operation")
    parser.add_argument("--gate-fd", type=int)
    parser.add_argument("--write-path", action="append", default=[])
    # Parse the child's command only beyond an explicit --, so action-first CLI
    # options are not swallowed by argparse.REMAINDER.
    argv = sys.argv[1:]
    separator = argv.index("--") if "--" in argv else len(argv)
    command = argv[separator + 1 :] if separator < len(argv) else []
    args = parser.parse_args(argv[:separator])
    coordinator = Coordinator(args.state_root)
    repository = args.repository.resolve()
    if args.action == "enable":
        coordinator.register(
            repository, maintenance=args.cleanup or ("managed", "worktrees")
        )
        print(
            "Coordinated disk admission enabled; run the elected service before allocating"
        )
    elif args.action == "disable":
        coordinator.disable(repository)
        print("Coordinated admission disabled; retained ledger and pending requests")
    elif args.action == "serve":
        stop = False

        def shutdown(*_):
            nonlocal stop
            stop = True

        signal.signal(signal.SIGTERM, shutdown)
        signal.signal(signal.SIGINT, shutdown)
        with coordinator.leadership():
            while not stop:
                coordinator.tick()
                time.sleep(1)
    elif args.action == "owner-check":
        return 0 if owner_check(coordinator) else 1
    elif args.action == "configured-check":
        # A disabled repository is distinct from malformed state/import errors.
        # Shell cleanup clients may use their legacy owner only on this code.
        return 0 if configured(repository) is not None else 3
    elif args.action == "child":
        if args.gate_fd is None or not command:
            parser.error("Internal child requires a committed allocation gate")
        if os.read(args.gate_fd, 1) != b"1":
            return 75
        os.close(args.gate_fd)
        os.execvp(command[0], command)
    elif args.action == "maintenance":
        active = configured(repository)
        if not active:
            parser.error("Repository is not enabled for coordinated cleanup")
        active.enqueue_maintenance(repository, args.kind)
        print("Cleanup request queued; the elected coordinator owns execution")
    elif args.action == "cancel":
        coordinator.cancel(args.request)
    elif args.action == "run":
        if args.bytes is None or not args.operation or not command:
            parser.error("run requires --bytes, --operation and -- command")
        return run_command(
            repository, args.bytes, args.operation, command, write_paths=args.write_path
        )
    else:
        rows = coordinator.requests(repository)
        print(
            json.dumps(
                {"available": coordinator.available(), "requests": rows}, indent=2
            )
        )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
