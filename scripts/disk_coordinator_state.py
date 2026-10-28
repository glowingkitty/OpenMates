#!/usr/bin/env python3
"""Host-local disk admission and the sole scheduler of approved cleanup.

One SQLite ledger covers all registered checkouts on each filesystem. Clients
only enqueue/claim leases; the elected service grants capacity and runs existing
cleanup owners. Durable chat waits survive short-lived CLI processes. No model,
Task account, arbitrary shell command or user pause is owned by this service.
"""

from __future__ import annotations

from contextlib import contextmanager
import hashlib
import json
import os
from pathlib import Path
import shutil
import socket
import sqlite3
import subprocess
import sys
import time
import uuid

try:
    from scripts import resource_budget as budget
except ModuleNotFoundError:
    import resource_budget as budget

GIB = 1024**3
GRANT_SECONDS = 300
CLEANUP_BACKOFF = 300
RECOVERY_MARGIN = 2 * GIB
MIN_INODES = 10000
KINDS = ("managed", "worktrees", "docker", "proof")
SCHEMA = """
CREATE TABLE IF NOT EXISTS repositories (
 path TEXT PRIMARY KEY, enabled INTEGER NOT NULL, maintenance TEXT NOT NULL);
CREATE TABLE IF NOT EXISTS requests (
 id TEXT PRIMARY KEY, repository TEXT NOT NULL, filesystem TEXT NOT NULL,
 thread TEXT NOT NULL, task_id TEXT NOT NULL, operation TEXT NOT NULL,
 amount INTEGER NOT NULL, outstanding INTEGER NOT NULL,
 min_free INTEGER NOT NULL, max_percent REAL NOT NULL, min_inodes INTEGER NOT NULL,
 pid INTEGER NOT NULL, start TEXT NOT NULL, owner_group INTEGER NOT NULL DEFAULT 0,
 state TEXT NOT NULL, grant_id TEXT NOT NULL DEFAULT '', expires_at REAL NOT NULL DEFAULT 0,
 created_at REAL NOT NULL, updated_at REAL NOT NULL, reason TEXT NOT NULL DEFAULT '',
 acknowledged INTEGER NOT NULL DEFAULT 0, attempts INTEGER NOT NULL DEFAULT 0);
CREATE INDEX IF NOT EXISTS requests_fs ON requests(filesystem,state);
CREATE TABLE IF NOT EXISTS pressure (
 filesystem TEXT PRIMARY KEY, active INTEGER NOT NULL DEFAULT 0,
 next_cleanup REAL NOT NULL DEFAULT 0, last_free INTEGER NOT NULL DEFAULT 0,
 reason TEXT NOT NULL DEFAULT '');
CREATE TABLE IF NOT EXISTS maintenance (
 repository TEXT NOT NULL, kind TEXT NOT NULL, state TEXT NOT NULL,
 created_at REAL NOT NULL, reason TEXT NOT NULL DEFAULT '',
 PRIMARY KEY(repository,kind));
CREATE TABLE IF NOT EXISTS events (
 id INTEGER PRIMARY KEY, created_at REAL NOT NULL, kind TEXT NOT NULL, detail TEXT NOT NULL);
"""


def default_state():
    return Path(
        os.environ.get("OPENMATES_DISK_STATE")
        or Path.home() / ".local/state/openmates/disk-coordinator"
    )


def canonical_repository(path):
    path = Path(path).resolve()
    try:
        result = subprocess.run(
            ["git", "rev-parse", "--path-format=absolute", "--git-common-dir"],
            cwd=path,
            capture_output=True,
            text=True,
            timeout=5,
        )
        if result.returncode == 0:
            return Path(result.stdout.strip()).resolve().parent
        if (path / ".git").exists():
            raise RuntimeError(
                "Cannot resolve the repository disk coordinator identity"
            )
    except (OSError, subprocess.SubprocessError):
        if (path / ".git").exists():
            raise RuntimeError(
                "Cannot resolve the repository disk coordinator identity"
            ) from None
    return path


def marker(repository):
    return canonical_repository(repository) / ".claude/resource-budget/coordinator.json"


def configured(repository):
    try:
        record = json.loads(marker(repository).read_text())
        try:
            from scripts.disk_coordinator import Coordinator
        except ModuleNotFoundError:
            from disk_coordinator import Coordinator
        return (
            Coordinator(Path(record["state_root"]))
            if record.get("enabled") is True
            else None
        )
    except FileNotFoundError:
        return None


def filesystem(path):
    return f"{socket.gethostname()}:{Path(path).stat().st_dev}"


def _atomic(path, value):
    path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
    temporary = path.with_name(path.name + f".{uuid.uuid4().hex}.tmp")
    try:
        with temporary.open("x") as stream:
            os.chmod(temporary, 0o600)
            json.dump(value, stream)
            stream.flush()
            os.fsync(stream.fileno())
        temporary.replace(path)
    finally:
        temporary.unlink(missing_ok=True)


def group_alive(group):
    try:
        os.killpg(group, 0)
    except ProcessLookupError:
        return False
    except PermissionError:
        return True
    if not sys.platform.startswith("linux"):
        return True
    # Zombies cannot write and must not retain capacity forever on hosts whose
    # PID 1 does not promptly reap orphaned descendants.
    try:
        for entry in Path("/proc").iterdir():
            if not entry.name.isdigit():
                continue
            try:
                fields = (entry / "stat").read_text().rsplit(") ", 1)[1].split()
                if int(fields[2]) == group and fields[0] != "Z":
                    return True
            except FileNotFoundError:
                continue
            except (OSError, ValueError, IndexError):
                return True
        return False
    except OSError:
        return True


def allocation_exited(pid):
    if budget._owner_is_dead(pid):
        return True
    if sys.platform.startswith("linux"):
        try:
            return (
                Path(f"/proc/{pid}/stat").read_text().rsplit(") ", 1)[1].split()[0]
                == "Z"
            )
        except (OSError, IndexError):
            pass
    return False


class DiskWait(RuntimeError):
    def __init__(self, request):
        self.request = request
        super().__init__(
            "Disk capacity wait persisted: "
            + json.dumps(
                {
                    "request_id": request["id"],
                    "operation": request["operation"],
                    "state": request["state"],
                    "reason": request["reason"],
                    "next_action": "Checkpoint and yield this disk-dependent work. The disk coordinator owns cleanup; the registered Task adapter will notify eligible owners. Do not run independent cleanup or retry in a loop.",
                },
                sort_keys=True,
            )
        )


class CoordinatorState:
    def __init__(self, state_root=None, *, usage=None, inodes=None, clock=None):
        self.root = Path(state_root) if state_root is not None else default_state()
        self.database = self.root / "ledger.sqlite3"
        self.usage = usage or shutil.disk_usage
        self.inodes = inodes or (lambda p: os.statvfs(p).f_favail)
        self.clock = clock or time.time
        self._leader = None

    @contextmanager
    def db(self, *, write=False):
        if write:
            self.root.mkdir(parents=True, exist_ok=True, mode=0o700)
        db = sqlite3.connect(
            str(self.database) if write else f"file:{self.database}?mode=ro",
            uri=not write,
            timeout=10,
        )
        db.row_factory = sqlite3.Row
        try:
            if write:
                os.chmod(self.database, 0o600)
                db.executescript(SCHEMA)
                db.execute("BEGIN IMMEDIATE")
            yield db
            if write:
                db.commit()
        except BaseException:
            db.rollback()
            raise
        finally:
            db.close()

    def available(self):
        try:
            record = json.loads((self.root / "leader.json").read_text())
            return bool(
                record["start"] and budget._start_time(record["pid"]) == record["start"]
            )
        except (OSError, ValueError, KeyError):
            return False

    def register(self, repository, *, maintenance=("managed", "worktrees")):
        repository = canonical_repository(repository)
        if not set(maintenance) <= set(KINDS):
            raise ValueError("Unknown cleanup kind")
        # Cutover requires no old local allocation owner to remain in flight.
        with budget._locked(repository) as directory:
            if budget._reservations(directory):
                raise RuntimeError(
                    "Active legacy reservations: finish them before disk cutover"
                )
            with self.db(write=True) as db:
                db.execute(
                    "INSERT OR REPLACE INTO repositories VALUES (?,1,?)",
                    (str(repository), json.dumps(list(maintenance))),
                )
            _atomic(
                marker(repository),
                {"enabled": True, "state_root": str(self.root.resolve())},
            )

    def disable(self, repository):
        repository = str(canonical_repository(repository))
        with self.db(write=True) as db:
            if db.execute(
                "SELECT 1 FROM requests WHERE repository=? AND state IN ('granted','claimed')",
                (repository,),
            ).fetchone():
                raise RuntimeError(
                    "Reconcile outstanding capacity grants before disabling"
                )
            db.execute("UPDATE repositories SET enabled=0 WHERE path=?", (repository,))
        _atomic(
            marker(repository),
            {"enabled": False, "state_root": str(self.root.resolve())},
        )

    def request(
        self,
        repository,
        amount,
        *,
        operation,
        thread="",
        task_id="",
        min_free=budget.MIN_FREE,
        max_used_percent=budget.MAX_USED_PERCENT,
        min_inodes=MIN_INODES,
        pid=None,
    ):
        repository = str(canonical_repository(repository))
        if (
            type(amount) is not int
            or amount < 0
            or not operation
            or len(operation) > 300
            or min_free < 0
            or not 0 < max_used_percent <= 100
            or min_inodes < 0
        ):
            raise ValueError("Invalid disk capacity request")
        if thread:
            uuid.UUID(thread)
        pid = os.getpid() if pid is None else pid
        start = budget._start_time(pid)
        if not start:
            raise RuntimeError("Cannot establish disk reservation owner")
        fs = filesystem(repository)
        # An anonymous process cannot transfer its reservation to a later PID.
        key = [repository, fs, thread or f"{pid}:{start}", operation]
        identity = hashlib.sha256(json.dumps(key).encode()).hexdigest()
        now = self.clock()
        with self.db(write=True) as db:
            registered = db.execute(
                "SELECT enabled FROM repositories WHERE path=?", (repository,)
            ).fetchone()
            if not registered or not registered[0]:
                raise RuntimeError(
                    "Repository is not enabled for coordinated disk admission"
                )
            prior = db.execute(
                "SELECT * FROM requests WHERE repository=? AND filesystem=? AND thread=? AND operation=? AND state IN ('waiting','granted','claimed') ORDER BY created_at DESC LIMIT 1",
                (repository, fs, thread, operation),
            ).fetchone()
            if prior and (thread or (prior["pid"] == pid and prior["start"] == start)):
                identity = prior["id"]
            else:
                prior = None
                # Completed operations are a new cycle; never reuse their Task
                # status intents or delivery IDs after a later invocation.
                identity = hashlib.sha256(
                    json.dumps([*key, uuid.uuid4().hex]).encode()
                ).hexdigest()
            if amount + min_free > self.usage(repository).total:
                raise ValueError(
                    "Requested allocation and recovery reserve exceed filesystem size"
                )
            if prior and not task_id:
                task_id = prior["task_id"]
            if prior and (
                prior["amount"] != amount
                or prior["min_free"] != min_free
                or prior["max_percent"] != max_used_percent
                or prior["min_inodes"] != min_inodes
                or prior["task_id"] != task_id
            ):
                raise ValueError(
                    "Disk operation ID reused with different capacity requirements"
                )
            if not prior:
                db.execute(
                    """INSERT INTO requests
                    (id,repository,filesystem,thread,task_id,operation,amount,outstanding,min_free,
                     max_percent,min_inodes,pid,start,state,created_at,updated_at)
                    VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,'waiting',?,?)""",
                    (
                        identity,
                        repository,
                        fs,
                        thread,
                        task_id,
                        operation,
                        amount,
                        amount,
                        min_free,
                        max_used_percent,
                        min_inodes,
                        pid,
                        start,
                        now,
                        now,
                    ),
                )
            elif prior["state"] != "claimed":
                db.execute(
                    "UPDATE requests SET pid=?,start=?,updated_at=?,expires_at=CASE WHEN state='waiting' THEN 0 ELSE expires_at END WHERE id=?",
                    (pid, start, now, identity),
                )
            return dict(
                db.execute("SELECT * FROM requests WHERE id=?", (identity,)).fetchone()
            )

    def requests(self, repository, thread=None):
        if not self.database.exists():
            return []
        with self.db() as db:
            sql = "SELECT * FROM requests WHERE repository=?"
            args = [str(canonical_repository(repository))]
            if thread is not None:
                sql += " AND thread=?"
                args.append(thread)
            return [dict(r) for r in db.execute(sql + " ORDER BY created_at,id", args)]

    def get(self, identity):
        if not self.database.exists():
            return None
        with self.db() as db:
            row = db.execute(
                "SELECT * FROM requests WHERE id=?", (identity,)
            ).fetchone()
            return dict(row) if row else None

    def bind_task(self, identity, thread, task_id):
        """Fence a once-inferred Task so later same-chat work cannot inherit it."""
        if not task_id or not thread:
            return False
        with self.db(write=True) as db:
            result = db.execute(
                "UPDATE requests SET task_id=? WHERE id=? AND thread=? "
                "AND task_id IN ('',?) AND state IN ('waiting','granted')",
                (task_id, identity, thread, task_id),
            )
            return result.rowcount == 1

    def valid_grant(self, identity, grant_id):
        row = self.get(identity)
        return bool(
            self.available()
            and row
            and row["state"] == "granted"
            and grant_id
            and row["grant_id"] == grant_id
            and row["expires_at"] > self.clock()
        )

    def defer(self, identity):
        with self.db(write=True) as db:
            db.execute(
                """UPDATE requests SET state='waiting',grant_id='',expires_at=?,
                       updated_at=?,reason='Continuation is paused or ineligible',acknowledged=0
                       WHERE id=? AND state IN ('waiting','granted')""",
                (self.clock() + GRANT_SECONDS, self.clock(), identity),
            )

    def cancel(self, identity, reason="Cancelled by owner"):
        with self.db(write=True) as db:
            # A running allocation is released only by its actual process or death.
            db.execute(
                "UPDATE requests SET state='cancelled',outstanding=0,reason=?,updated_at=? "
                "WHERE id=? AND state IN ('waiting','granted')",
                (reason, self.clock(), identity),
            )

    def acknowledge(self, identity, grant_id):
        with self.db(write=True) as db:
            db.execute(
                "UPDATE requests SET acknowledged=1 WHERE id=? AND grant_id=? AND state='granted' AND expires_at>?",
                (identity, grant_id, self.clock()),
            )

    def _reconcile(self, db):
        now = self.clock()
        for row in db.execute(
            "SELECT * FROM requests WHERE state IN ('waiting','granted','claimed')"
        ).fetchall():
            start = budget._start_time(row["pid"])
            dead = bool(start and start != row["start"]) or allocation_exited(
                row["pid"]
            )
            group_live = bool(row["owner_group"] and group_alive(row["owner_group"]))
            if row["state"] == "claimed" and dead and not group_live:
                db.execute(
                    "UPDATE requests SET state='complete',outstanding=0,reason='Allocation owner exited' WHERE id=?",
                    (row["id"],),
                )
            elif row["state"] in {"waiting", "granted"} and not row["thread"] and dead:
                db.execute(
                    "UPDATE requests SET state='cancelled',outstanding=0 WHERE id=?",
                    (row["id"],),
                )
            elif row["state"] == "granted" and row["expires_at"] <= now:
                db.execute(
                    "UPDATE requests SET state='waiting',grant_id='',expires_at=0,acknowledged=0 WHERE id=?",
                    (row["id"],),
                )

    def claim(self, identity, grant_id):
        if not self.available():
            raise RuntimeError("Disk coordinator unavailable; retain pending request")
        with self.db(write=True) as db:
            self._reconcile(db)
            row = db.execute(
                "SELECT * FROM requests WHERE id=?", (identity,)
            ).fetchone()
            if (
                not row
                or row["state"] != "granted"
                or row["grant_id"] != grant_id
                or row["expires_at"] <= self.clock()
            ):
                raise RuntimeError("Disk capacity grant expired or unavailable")
            usage = self.usage(row["repository"])
            committed = db.execute(
                "SELECT COALESCE(SUM(outstanding),0) FROM requests WHERE filesystem=? AND state IN ('granted','claimed') AND id!=?",
                (row["filesystem"], identity),
            ).fetchone()[0]
            decision = budget.admission(
                Path(row["repository"]),
                row["amount"],
                min_free=row["min_free"],
                max_used_percent=row["max_percent"],
                usage=usage,
                reserved=committed,
            )
            if (
                not decision["allowed"]
                or self.inodes(row["repository"]) < row["min_inodes"]
            ):
                db.execute(
                    "UPDATE requests SET state='waiting',grant_id='',expires_at=0,reason='Capacity changed before claim' WHERE id=?",
                    (identity,),
                )
                return None
            db.execute(
                "UPDATE requests SET state='claimed',pid=?,start=?,updated_at=? WHERE id=?",
                (os.getpid(), budget._start_time(os.getpid()), self.clock(), identity),
            )
            return dict(
                db.execute("SELECT * FROM requests WHERE id=?", (identity,)).fetchone()
            )

    def materialized(self, identity, bytes_written):
        if type(bytes_written) is not int or bytes_written < 0:
            raise ValueError("Materialized allocation must be nonnegative bytes")
        with self.db(write=True) as db:
            row = db.execute(
                "SELECT * FROM requests WHERE id=? AND state='claimed'", (identity,)
            ).fetchone()
            if (
                not row
                or row["pid"] != os.getpid()
                or row["start"] != budget._start_time(os.getpid())
            ):
                raise RuntimeError("Only the live allocation owner may update a lease")
            if bytes_written > row["amount"]:
                raise RuntimeError("Disk allocation exceeded its admitted peak")
            db.execute(
                "UPDATE requests SET outstanding=MIN(outstanding,?),updated_at=? WHERE id=?",
                (row["amount"] - bytes_written, self.clock(), identity),
            )

    def release(self, identity):
        with self.db(write=True) as db:
            db.execute(
                "UPDATE requests SET state='complete',outstanding=0,updated_at=? WHERE id=? AND state='claimed' AND pid=? AND start=?",
                (self.clock(), identity, os.getpid(), budget._start_time(os.getpid())),
            )
