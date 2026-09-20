"""Durable admission and GitHub dispatch for isolated OpenMates test jobs.

All tasks share one SQLite queue in the canonical checkout. A single flocked
reconciler owns network calls; status readers never poll GitHub independently.
Dispatch intent is committed before sending and uncertain sends are reconciled,
never blindly repeated. See docs/plans/isolated-github-tests/plan.yml.
"""

from __future__ import annotations

import argparse
import fcntl
import hashlib
import json
import os
from pathlib import Path
import re
import sqlite3
import subprocess
import sys
import time
import uuid

POLL_SECONDS = 30
MAX_ACTIVE = 4
LIGHTWEIGHT_MODES = frozenset({"component", "pytest", "vitest", "codex"})
RATE_RESERVE = 100
ERROR_BACKOFF = 60
UNCERTAIN_SECONDS = 600
WORKFLOW = "isolated-tests.yml"
ACTIVE = ("dispatching", "submitted", "running", "attention")
TERMINAL = ("success", "failure", "cancelled")


def canonical_root(root: Path) -> Path:
    common = subprocess.check_output(
        ["git", "rev-parse", "--git-common-dir"], cwd=root, text=True
    ).strip()
    return (root / common).resolve().parent


class GitHubError(RuntimeError):
    def __init__(self, message: str, retry_at: float):
        super().__init__(message)
        self.retry_at = retry_at


class GitHub:
    def __init__(self, root: Path):
        self.root = root
        self.repo = subprocess.check_output(
            ["gh", "repo", "view", "--json", "nameWithOwner", "--jq", ".nameWithOwner"],
            cwd=root,
            text=True,
        ).strip()

    def request(self, endpoint: str, payload: dict | None = None):
        command = ["gh", "api", "--include", endpoint]
        if payload is not None:
            command += ["--method", "POST", "--input", "-"]
        result = subprocess.run(
            command,
            input=json.dumps(payload) if payload is not None else None,
            cwd=self.root,
            text=True,
            capture_output=True,
            timeout=45,
        )
        headers, _, body = result.stdout.replace("\r\n", "\n").partition("\n\n")
        if result.returncode:
            delay = re.search(r"(?im)^retry-after:\s*(\d+)", headers)
            reset = re.search(r"(?im)^x-ratelimit-reset:\s*(\d+)", headers)
            retry_at = time.time() + (int(delay[1]) if delay else ERROR_BACKOFF)
            if reset and re.search(r"(?im)^x-ratelimit-remaining:\s*0\s*$", headers):
                retry_at = max(retry_at, int(reset[1]) + 1)
            raise GitHubError(
                "GitHub request failed; queued work retained (see authenticated gh diagnostics).",
                retry_at,
            )
        return json.loads(body) if body.strip() else {}

    def budget(self):
        return self.request("rate_limit")["resources"]["core"]

    def runs(self):
        return self.request(
            f"repos/{self.repo}/actions/workflows/{WORKFLOW}/runs?event=workflow_dispatch&per_page=100"
        )["workflow_runs"]

    def prepare_dispatch(self, job: dict) -> dict:
        """Resolve private capabilities before recording any remote send intent."""
        prepared = dict(job)
        if job.get("preparation_key"):
            try:
                from scripts.ci_preparation_transport import dispatch_ticket
            except ModuleNotFoundError:
                from ci_preparation_transport import dispatch_ticket
            # Capability URLs live only in an owner-readable ticket, never in
            # queue status/results. Consumers receive read-only capabilities.
            prepared["_preparation_transport"] = dispatch_ticket(self.root, job)
        return prepared

    def dispatch(self, job: dict):
        if job.get("candidate_expires") and float(job["candidate_expires"]) <= time.time():
            raise ValueError("CI candidate artifact expired before dispatch; publish again")
        if job.get("preparation_key") and "_preparation_transport" not in job:
            job = self.prepare_dispatch(job)
        self.request(
            f"repos/{self.repo}/actions/workflows/{WORKFLOW}/dispatches",
            {
                "ref": "dev",
                "inputs": {
                    "checkout_ref": job.get("candidate_base") or job["source"],
                    "source_commit": job["source"],
                    "candidate_tree": job.get("candidate_tree", ""),
                    "candidate_owner": job.get("candidate_owner", ""),
                    "candidate_patch_sha256": job.get("candidate_patch_sha256", ""),
                    "candidate_patch_url": job.get("candidate_patch_url", ""),
                    "specs_json": job["specs"],
                    "mode": job["mode"],
                    "dispatch_token": job["token"],
                    "proof_video_profile": job.get("proof_profile", ""),
                    **({
                        "preparation_key": job["preparation_key"],
                        "prepared_run_id": str(job.get("prepared_run_id") or ""),
                        "prepare_cli": "true" if job.get("prepare_cli") else "false",
                        "prepare_upload": "true" if job.get("prepare_upload") else "false",
                        "preparation_transport": job.get("_preparation_transport", ""),
                    } if job.get("preparation_key") else {}),
                },
            },
        )

    def run(self, run_id):
        return self.request(f"repos/{self.repo}/actions/runs/{run_id}")

    def phase(self, run_id):
        jobs = self.request(f"repos/{self.repo}/actions/runs/{run_id}/jobs?per_page=100")["jobs"]
        for job in jobs:
            for step in job.get("steps", []):
                if step.get("status") == "in_progress":
                    return step["name"]
        return "GitHub runner setup" if jobs else "GitHub runner queue"


class Queue:
    def __init__(self, path: Path, *, max_active=None, lightweight_reserve=None):
        self.path = path
        self.max_active = int(max_active if max_active is not None else os.environ.get("OPENMATES_CI_MAX_ACTIVE", MAX_ACTIVE))
        self.lightweight_reserve = int(lightweight_reserve if lightweight_reserve is not None else os.environ.get("OPENMATES_CI_LIGHTWEIGHT_RESERVE", min(1, self.max_active - 1)))
        if not 1 <= self.max_active <= 32 or not 0 <= self.lightweight_reserve < self.max_active:
            raise ValueError("CI capacity must be 1..32 with a smaller nonnegative lightweight reserve")
        path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
        with self.connect() as db:
            db.executescript("""
                CREATE TABLE IF NOT EXISTS jobs (
                    id TEXT PRIMARY KEY, owner TEXT NOT NULL, source TEXT NOT NULL,
                    specs TEXT NOT NULL, mode TEXT NOT NULL, token TEXT NOT NULL UNIQUE,
                    state TEXT NOT NULL, run_id INTEGER, url TEXT, created REAL NOT NULL,
                    sent REAL, updated REAL NOT NULL, error TEXT);
                CREATE TABLE IF NOT EXISTS meta (key TEXT PRIMARY KEY, value TEXT NOT NULL);
            """)
            columns = {row[1] for row in db.execute("PRAGMA table_info(jobs)")}
            if "proof_profile" not in columns:
                try:
                    db.execute(
                        "ALTER TABLE jobs ADD COLUMN proof_profile TEXT NOT NULL DEFAULT ''"
                    )
                except sqlite3.OperationalError:
                    if "proof_profile" not in {
                        row[1] for row in db.execute("PRAGMA table_info(jobs)")
                    }:
                        raise
            candidate_columns = {
                "candidate_base": "TEXT NOT NULL DEFAULT ''",
                "candidate_tree": "TEXT NOT NULL DEFAULT ''",
                "candidate_owner": "TEXT NOT NULL DEFAULT ''",
                "candidate_patch_sha256": "TEXT NOT NULL DEFAULT ''",
                "candidate_patch_url": "TEXT NOT NULL DEFAULT ''",
                "candidate_expires": "REAL NOT NULL DEFAULT 0",
                "preparation_id": "TEXT NOT NULL DEFAULT ''",
                "preparation_key": "TEXT NOT NULL DEFAULT ''",
                "prepared_run_id": "INTEGER",
                "prepare_cli": "INTEGER NOT NULL DEFAULT 0",
                "prepare_upload": "INTEGER NOT NULL DEFAULT 0",
                "phase": "TEXT NOT NULL DEFAULT ''",
                "phase_updated": "REAL NOT NULL DEFAULT 0",
                "ready_at": "REAL",
            }
            for name, definition in candidate_columns.items():
                if name not in columns:
                    try:
                        db.execute(f"ALTER TABLE jobs ADD COLUMN {name} {definition}")
                    except sqlite3.OperationalError:
                        if name not in {row[1] for row in db.execute("PRAGMA table_info(jobs)")}:
                            raise
        path.chmod(0o600)

    def connect(self):
        db = sqlite3.connect(self.path, timeout=30)
        db.row_factory = sqlite3.Row
        return db

    def enqueue(
        self,
        owner: str,
        source: str,
        specs: list[str],
        mode="e2e",
        nonce="",
        proof_profile="",
        candidate: dict | None = None,
        preparation: dict | None = None,
    ) -> dict:
        if not owner or not re.fullmatch(r"[0-9a-f]{40}", source):
            raise ValueError("Owner and full immutable source commit are required")
        if mode not in ("prepare", "component", "e2e", "artifact", "codex", "pytest", "vitest", "selfhost", "visual-smoke"):
            raise ValueError("Unknown CI mode")
        if proof_profile not in ("", "web-phone", "web-laptop") or (
            proof_profile and mode not in ("component", "e2e", "artifact")
        ):
            raise ValueError("Invalid proof video profile")
        candidate = candidate or {}
        candidate_values = {
            "candidate_base": "",
            "candidate_tree": "",
            "candidate_owner": "",
            "candidate_patch_sha256": "",
            "candidate_patch_url": "",
            "candidate_expires": 0.0,
        }
        if candidate:
            from datetime import datetime
            try:
                from scripts.ci_candidate_artifact import validate_url
            except ModuleNotFoundError:
                from ci_candidate_artifact import validate_url
            if candidate.get("source") != source or candidate.get("session") != owner:
                raise ValueError("CI candidate identity does not match queue owner and source")
            for field in ("base", "tree"):
                if not re.fullmatch(r"[0-9a-f]{40}", str(candidate.get(field, ""))):
                    raise ValueError(f"CI candidate requires a full {field} SHA")
            digest = str(candidate.get("patch_sha256", ""))
            if not re.fullmatch(r"[0-9a-f]{64}", digest):
                raise ValueError("CI candidate requires a SHA-256 patch digest")
            url = validate_url(str(candidate.get("patch_url", "")))
            expires_value = datetime.fromisoformat(str(candidate.get("artifact_expires_at", "")))
            if expires_value.tzinfo is None:
                raise ValueError("CI candidate artifact expiry must include a timezone")
            expires = expires_value.timestamp()
            if expires <= time.time():
                raise ValueError("CI candidate artifact is expired")
            candidate_values = {
                "candidate_base": candidate["base"],
                "candidate_tree": candidate["tree"],
                "candidate_owner": candidate["session"],
                "candidate_patch_sha256": digest,
                "candidate_patch_url": url,
                "candidate_expires": expires,
            }
        if mode == "pytest":
            try:
                from scripts.ci_pytest_targets import validate_pytest_targets
            except ModuleNotFoundError:
                from ci_pytest_targets import validate_pytest_targets
            specs = validate_pytest_targets(specs)
        specs = list(specs) if mode == "pytest" else sorted(set(specs))
        if mode in ("component", "e2e") and len(specs) > 1:
            raise ValueError("Each browser job must contain exactly one spec")
        if mode == "visual-smoke":
            try:
                from scripts.ci_visual_smoke import validate_targets
            except ModuleNotFoundError:
                from ci_visual_smoke import validate_targets
            validate_targets(specs)
        for spec in ([] if mode in ("visual-smoke", "pytest") else specs):
            if (
                not re.fullmatch(r"[A-Za-z0-9_./-]+\.spec\.ts", spec)
                or ".." in spec
                or spec.startswith("/")
            ):
                raise ValueError("Invalid spec path")
        if mode in ("component", "e2e", "artifact") and not specs:
            raise ValueError("Browser requests require explicit specs")
        if mode == "selfhost" and specs != ["selfhost-smoke.spec.ts"]:
            raise ValueError("Installer runtime requires exactly its original smoke spec")
        if mode == "e2e":
            try:
                from scripts.ci_coverage import validate_runtime_batch
            except ModuleNotFoundError:
                from ci_coverage import validate_runtime_batch
            validate_runtime_batch(specs)
        encoded = json.dumps(specs, separators=(",", ":"))
        stable_candidate = {key: value for key, value in candidate_values.items() if key not in ("candidate_patch_url", "candidate_expires")}
        identity = [owner, source, specs, mode, nonce, stable_candidate]
        preparation = preparation or {}
        if preparation:
            if mode not in ("prepare", "e2e", "visual-smoke") or not re.fullmatch(r"[0-9a-f]{64}", preparation.get("key", "")):
                raise ValueError("Invalid preparation identity")
            identity.append(preparation)
        if proof_profile:
            identity.append(proof_profile)
        key = hashlib.sha256(json.dumps(identity).encode()).hexdigest()
        now = time.time()
        with self.connect() as db:
            db.execute(
                "INSERT OR IGNORE INTO jobs(id,owner,source,specs,mode,token,state,created,updated,proof_profile,candidate_base,candidate_tree,candidate_owner,candidate_patch_sha256,candidate_patch_url,candidate_expires) VALUES(?,?,?,?,?,?,?, ?,?,?,?,?,?,?,?,?)",
                (
                    key,
                    owner,
                    source,
                    encoded,
                    mode,
                    "ci-" + uuid.uuid4().hex,
                    "queued",
                    now,
                    now,
                    proof_profile,
                    candidate_values["candidate_base"],
                    candidate_values["candidate_tree"],
                    candidate_values["candidate_owner"],
                    candidate_values["candidate_patch_sha256"],
                    candidate_values["candidate_patch_url"],
                    candidate_values["candidate_expires"],
                ),
            )
            if preparation:
                db.execute(
                    "UPDATE jobs SET preparation_id=?,preparation_key=?,prepare_cli=?,prepare_upload=? WHERE id=? AND state='queued'",
                    (preparation.get("id", ""), preparation["key"], bool(preparation.get("cli")), bool(preparation.get("upload")), key),
                )
            if candidate:
                db.execute("UPDATE jobs SET candidate_patch_url=?,candidate_expires=? WHERE id=? AND state='queued'", (candidate_values["candidate_patch_url"], candidate_values["candidate_expires"], key))
            return dict(db.execute("SELECT * FROM jobs WHERE id=?", (key,)).fetchone())

    def supersede_pending(self, job: dict) -> int:
        """Replace only this owner's matching undispatched scope, never running work."""
        with self.connect() as db:
            db.execute("BEGIN IMMEDIATE")
            replaced = db.execute(
                "UPDATE jobs SET state='cancelled',phase='superseded before dispatch',updated=?,error='Replaced by a newer candidate for the same owner and check' WHERE owner=? AND source<>? AND specs=? AND mode=? AND proof_profile=? AND state='queued' AND sent IS NULL",
                (time.time(), job["owner"], job["source"], job["specs"], job["mode"], job["proof_profile"]),
            ).rowcount
            # A producer may be between creation and child attachment in another
            # submission. Do not infer that it is unused and cancel shared work.
            return replaced

    def status(self, key=None):
        with self.connect() as db:
            rows = db.execute(
                    "SELECT * FROM jobs"
                    + (" WHERE id=?" if key else " ORDER BY created DESC LIMIT 100"),
                    (key,) if key else (),
                ).fetchall()
            result = []
            for row in rows:
                end = row["sent"] or (row["updated"] if row["state"] in TERMINAL else time.time())
                ready = row["ready_at"] or (end if row["preparation_id"] else row["created"])
                result.append({**dict(row), "queue_seconds": round(max(0, end - ready), 1), "preparation_wait_seconds": round(max(0, ready - row["created"]), 1) if row["preparation_id"] else 0})
            return result

    def metadata(self, db, key, default="0"):
        row = db.execute("SELECT value FROM meta WHERE key=?", (key,)).fetchone()
        return row[0] if row else default

    def set_meta(self, db, key, value):
        db.execute(
            "INSERT INTO meta VALUES(?,?) ON CONFLICT(key) DO UPDATE SET value=excluded.value",
            (key, str(value)),
        )

    def prioritize(self, key: str, owner: str, reason: str):
        """Admit one owned prerequisite ahead of bulk work without adding slots."""
        if not reason.strip():
            raise ValueError("An explicit prerequisite reason is required")
        with self.connect() as db:
            db.execute("BEGIN IMMEDIATE")
            job = db.execute("SELECT * FROM jobs WHERE id=?", (key,)).fetchone()
            if not job or job["owner"] != owner or job["state"] != "queued":
                raise ValueError("Only an owned queued request can be prioritized")
            previous = self.metadata(db, "prerequisite_request", "")
            active = db.execute("SELECT state FROM jobs WHERE id=?", (previous,)).fetchone()
            if previous != key and active and active["state"] not in TERMINAL:
                raise ValueError("Another prerequisite is still pending")
            self.set_meta(db, "prerequisite_request", key)
            self.set_meta(db, "prerequisite_reason", reason.strip())
            return {"id": key, "reason": reason.strip(), "max_active": self.max_active}

    def result(self, github, key, root, fetch):
        """Use the same serialized rate budget for evidence and dispatch traffic."""
        with self.path.with_suffix(".lock").open("a") as lock:
            fcntl.flock(lock, fcntl.LOCK_EX)
            jobs = self.status(key)
            if not jobs:
                raise ValueError("Unknown CI request")
            receipt = root / "test-results/ci-runs" / key / "receipt.json"
            if receipt.is_file():
                # The reader upgrades and validates cached evidence locally.
                # Do not bypass new receipt invariants or spend network budget.
                return fetch(github, jobs[0], root)
            with self.connect() as db:
                now = time.time()
                if now < float(self.metadata(db, "network_retry_at")):
                    raise RuntimeError(
                        "GitHub backoff active; use cached status/health"
                    )
                try:
                    budget = github.budget()
                    if int(budget["remaining"]) < RATE_RESERVE + 5:
                        raise GitHubError(
                            "GitHub request reserve reached", int(budget["reset"]) + 1
                        )
                    return fetch(github, jobs[0], root)
                except GitHubError as exc:
                    self.set_meta(db, "network_retry_at", exc.retry_at)
                    self.set_meta(db, "next_poll", exc.retry_at)
                    self.set_meta(db, "last_error", str(exc))
                    db.commit()
                    raise

    def tick(self, github, now=None):
        now = time.time() if now is None else now
        with self.path.with_suffix(".lock").open("a") as lock:
            try:
                fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
            except BlockingIOError:
                return
            with self.connect() as db:
                if now < float(self.metadata(db, "next_poll")):
                    return
                self.set_meta(db, "next_poll", now + POLL_SECONDS)
                jobs = [
                    dict(row)
                    for row in db.execute(
                        "SELECT * FROM jobs WHERE state NOT IN ('success','failure','cancelled') ORDER BY (id=?) DESC, created",
                        (self.metadata(db, "prerequisite_request", ""),)
                    )
                ]
                db.commit()
                if not jobs:
                    return
                try:
                    budget = github.budget()
                    if int(budget["remaining"]) < RATE_RESERVE + 2 * self.max_active + 2:
                        self.set_meta(
                            db,
                            "network_retry_at",
                            max(now + POLL_SECONDS, int(budget["reset"]) + 1),
                        )
                        self.set_meta(
                            db,
                            "next_poll",
                            max(now + POLL_SECONDS, int(budget["reset"]) + 1),
                        )
                        self.set_meta(
                            db, "last_error", "GitHub request reserve reached"
                        )
                        return
                    runs = github.runs()
                    by_token = {
                        j["token"]: [
                            r for r in runs if j["token"] in r.get("display_title", "")
                        ]
                        for j in jobs
                    }
                    reservations = {}
                    for job in jobs:
                        matches = by_token[job["token"]]
                        if not matches and job["run_id"]:
                            # Long jobs can fall out of the newest 100 runs. Their
                            # persisted IDs provide bounded, unambiguous recovery.
                            run = github.run(job["run_id"])
                            if job["token"] not in run.get("display_title", ""):
                                raise ValueError(
                                    "Persisted GitHub run identity mismatch"
                                )
                            matches = [run]
                        if len(matches) > 1:
                            db.execute(
                                "UPDATE jobs SET state='attention',error='Duplicate remote dispatch requires reconciliation' WHERE id=?",
                                (job["id"],),
                            )
                            reservations[job["id"]] = max(1, sum(run.get("status") != "completed" for run in matches))
                            continue
                        if matches:
                            run = matches[0]
                            state = (
                                "running"
                                if run["status"] != "completed"
                                else (
                                    "success"
                                    if run["conclusion"] == "success"
                                    else "cancelled"
                                    if run["conclusion"] == "cancelled"
                                    else "failure"
                                )
                            )
                            db.execute(
                                "UPDATE jobs SET state=?,run_id=?,url=?,updated=?,error=NULL WHERE id=?",
                                (state, run["id"], run["html_url"], now, job["id"]),
                            )
                            if state == "running":
                                reservations[job["id"]] = 1
                            phase = state
                            if state == "running":
                                if run["status"] in ("queued", "requested", "waiting", "pending"):
                                    phase = "GitHub runner queue"
                                elif hasattr(github, "phase") and now - job.get("phase_updated", 0) >= 60:
                                    phase = github.phase(run["id"])
                                else:
                                    phase = job.get("phase") or "GitHub execution (phase pending refresh)"
                            if phase != job.get("phase") or now - job.get("phase_updated", 0) >= 60:
                                db.execute("UPDATE jobs SET phase=?,phase_updated=? WHERE id=?", (phase, now, job["id"]))
                        elif job["state"] in ACTIVE:
                            reservations[job["id"]] = 1
                            if job["sent"] and now - job["sent"] > UNCERTAIN_SECONDS:
                                db.execute(
                                    "UPDATE jobs SET state='attention',error='Dispatch not visible; do not resubmit without remote reconciliation' WHERE id=?",
                                    (job["id"],),
                                )
                    db.commit()
                    # Refresh after reconciliation: a completed producer can release
                    # consumers in this tick, without counting blocked consumers as slots.
                    current = [dict(row) for row in db.execute("SELECT * FROM jobs WHERE state NOT IN ('success','failure','cancelled') ORDER BY created,id")]
                    pending = []
                    for job in current:
                        if job["state"] != "queued":
                            continue
                        if job.get("candidate_expires") and float(job["candidate_expires"]) <= now:
                            db.execute(
                                "UPDATE jobs SET state='failure',updated=?,error='Candidate artifact expired before dispatch; publish again' WHERE id=?",
                                (now, job["id"]),
                            )
                            continue
                        if job["preparation_id"]:
                            producer = db.execute("SELECT * FROM jobs WHERE id=?", (job["preparation_id"],)).fetchone()
                            if not producer or producer["state"] in ("failure", "cancelled"):
                                db.execute("UPDATE jobs SET state='failure',phase='preparation failed',updated=?,error='Required preparation did not succeed; no test coverage credited' WHERE id=?", (now, job["id"]))
                                continue
                            if producer["state"] != "success" or not producer["run_id"]:
                                db.execute("UPDATE jobs SET phase='waiting for preparation',phase_updated=? WHERE id=?", (now, job["id"]))
                                continue
                            job["prepared_run_id"] = producer["run_id"]
                            db.execute("UPDATE jobs SET prepared_run_id=?,ready_at=COALESCE(ready_at,?) WHERE id=?", (producer["run_id"], now, job["id"]))
                        pending.append(job)
                    db.commit()
                    active_jobs = [job for job in current if job["id"] in reservations]
                    active = sum(reservations.values())
                    heavy = sum(reservations[job["id"]] for job in active_jobs if job["mode"] not in LIGHTWEIGHT_MODES)
                    owners = {}
                    for job in active_jobs:
                        owners[job["owner"]] = owners.get(job["owner"], 0) + reservations[job["id"]]
                    priority = self.metadata(db, "prerequisite_request", "")
                    last_owner = self.metadata(db, "last_admitted_owner", "")
                    # One writer owns capacity and owner fairness across all callers.
                    while pending and active < self.max_active:
                        eligible = [job for job in pending if job["mode"] in LIGHTWEIGHT_MODES or heavy < self.max_active - self.lightweight_reserve]
                        if not eligible:
                            break
                        job = min(eligible, key=lambda item: (item["id"] != priority, owners.get(item["owner"], 0), item["owner"] == last_owner, item["created"], item["id"]))
                        pending.remove(job)
                        dispatch_job = job
                        if hasattr(github, "prepare_dispatch"):
                            try:
                                dispatch_job = github.prepare_dispatch(job)
                            except (RuntimeError, ValueError, OSError, subprocess.TimeoutExpired):
                                # No GitHub request has happened. Do not retain
                                # an uncertain slot or log capability-bearing errors.
                                db.execute(
                                    "UPDATE jobs SET state='failure',phase='private transport setup failed',updated=?,error='Private preparation transport could not be prepared; no GitHub dispatch occurred' WHERE id=?",
                                    (now, job["id"]),
                                )
                                db.commit()
                                continue
                        db.execute(
                            "UPDATE jobs SET state='dispatching',phase='GitHub dispatch',sent=?,updated=? WHERE id=?",
                            (now, now, job["id"]),
                        )
                        db.commit()
                        github.dispatch(dispatch_job)
                        db.execute(
                            "UPDATE jobs SET state='submitted',updated=? WHERE id=?",
                            (now, job["id"]),
                        )
                        db.commit()
                        active += 1
                        heavy += job["mode"] not in LIGHTWEIGHT_MODES
                        owners[job["owner"]] = owners.get(job["owner"], 0) + 1
                        last_owner = job["owner"]
                        self.set_meta(db, "last_admitted_owner", last_owner)
                        # Respect GitHub's guidance to space mutating requests.
                        time.sleep(1)
                    self.set_meta(db, "last_error", "")
                    self.set_meta(db, "capacity", json.dumps({"total": self.max_active, "lightweight_reserved": self.lightweight_reserve, "active": active}))
                except (
                    GitHubError,
                    subprocess.TimeoutExpired,
                    ValueError,
                    KeyError,
                ) as exc:
                    self.set_meta(
                        db,
                        "next_poll",
                        max(now + ERROR_BACKOFF, getattr(exc, "retry_at", 0)),
                    )
                    self.set_meta(db, "last_error", str(exc))
                    self.set_meta(
                        db,
                        "network_retry_at",
                        max(now + ERROR_BACKOFF, getattr(exc, "retry_at", 0)),
                    )


def enqueue_submission(
    queue: Queue,
    owner: str,
    source: str,
    specs: list[str],
    mode: str,
    nonce: str = "",
    proof_profile: str = "",
    candidate: dict | None = None,
    *,
    source_root: Path | None = None,
    supersede: bool = True,
    prepared_builds: bool = False,
) -> list[dict]:
    """Split E2Es; enable private shared preparation only for explicit canaries."""
    if prepared_builds and (source_root is None or mode not in ("e2e", "visual-smoke")):
        raise ValueError("Prepared-build canaries require an E2E/visual source root")
    selections = list(specs) if mode == "pytest" else sorted(set(specs))
    if mode in ("component", "e2e") and not selections:
        raise ValueError("Browser requests require explicit specs")
    batches = (
        [[spec] for spec in selections]
        if mode in ("component", "e2e")
        else [selections]
    )
    preparation = None
    # Public Actions artifacts must never carry unpublished build output.
    # GitHub.dispatch issues private-bucket capabilities before any preparation.
    # Keep ordinary tests on the existing isolated cold path until the schema
    # restore and two-consumer reuse canary is green. Do not make unfinished
    # preparation a mandatory dependency of every E2E or silently credit a failed
    # preparation run as successful coverage.
    if prepared_builds:
        try:
            from scripts.ci_artifacts import preparation_key
        except ModuleNotFoundError:
            from ci_artifacts import preparation_key
        manifest = json.loads(subprocess.check_output(
            ["git", "show", f"{source}:scripts/ci_coverage_manifest.json"], cwd=source_root, text=True,
        ))
        upload_specs = set(manifest["groups"].get("uploads", {}).get("specs", []))
        include_cli = mode == "e2e"  # Real account provisioning uses the CLI, too.
        include_upload = bool(upload_specs.intersection(selections))
        preparation = {
            "key": preparation_key(source, include_cli=include_cli, include_upload=include_upload),
            "cli": include_cli,
            "upload": include_upload,
        }
        producer = queue.enqueue(owner, source, [], "prepare", nonce, candidate=candidate, preparation=preparation)
        preparation = {**preparation, "id": producer["id"]}
    jobs = [
        queue.enqueue(
            owner,
            source,
            batch,
            mode,
            nonce,
            proof_profile,
            candidate,
            preparation,
        )
        for batch in batches
    ]
    if supersede:
        for job in jobs:
            queue.supersede_pending(job)
    return jobs


def print_receipt(value, *, as_json=False):
    """Keep machine receipts available without flooding ordinary agent calls."""
    if as_json:
        def redact(item):
            if isinstance(item, dict):
                return {
                    key: ("<redacted>" if key == "candidate_patch_url" and child else redact(child))
                    for key, child in item.items()
                }
            if isinstance(item, list):
                return [redact(child) for child in item]
            return item
        print(json.dumps(redact(value)))
        return
    rows = value if isinstance(value, list) else [value]
    for row in rows:
        if not isinstance(row, dict):
            print(str(row))
            continue
        identity = row.get("id", row.get("request_id", "CI"))
        state = row.get("state", row.get("conclusion", row.get("status", "recorded")))
        print(f"{identity}: {state}")
        for key in ("phase", "phase_updated", "queue_seconds", "preparation_wait_seconds", "preparation_id", "prepared_run_id", "source_commit", "source", "run_id", "url", "run_url", "artifact_url", "reason", "error", "receipt_path", "result_command"):
            if row.get(key):
                print(f"  {key}: {str(row[key])[:500]}")
        if not any(key in row for key in ("id", "request_id", "state", "status", "conclusion")):
            for key, item in row.items():
                if key not in ("reason", "error"):
                    print(f"  {key}: {str(item)[:200]}")


def wait_for_job(queue, key, *, timeout=7200, poll=10, clock=time.monotonic, sleep=time.sleep):
    """Read the coordinator cache; the daemon owns GitHub polling and rate limits."""
    if timeout <= 0 or poll <= 0:
        raise ValueError("Timeout and poll must be positive")
    deadline = clock() + timeout
    while True:
        rows = queue.status(key)
        if not rows:
            raise ValueError("Unknown CI request")
        row = rows[0]
        if row["state"] in TERMINAL or row["state"] == "attention":
            return row
        remaining = deadline - clock()
        if remaining <= 0:
            return {**row, "state": "timeout", "last_state": row["state"]}
        sleep(min(poll, remaining))


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest="action", required=True)
    submit = sub.add_parser("submit")
    submit.add_argument("--session", required=True)
    submit.add_argument("--source", required=True)
    submit.add_argument("--spec", "--test-target", action="append", default=[])
    submit.add_argument("--keep-queued-generations", action="store_true", help="Retain older matching queued checks instead of superseding them")
    submit.add_argument("--preview-url", action="append", default=[])
    submit.add_argument("--mode", choices=["component", "e2e", "artifact", "codex", "pytest", "vitest", "selfhost", "visual-smoke"], default="e2e")
    submit.add_argument("--attempt", default="")
    submit.add_argument("--prepared-builds", action="store_true", help="Opt into the unverified private prepared-build canary; ordinary E2Es use isolated cold setup")
    submit.add_argument(
        "--proof-video-profile", choices=["web-phone", "web-laptop"], default=""
    )
    priority = sub.add_parser("prioritize")
    priority.add_argument("id")
    priority.add_argument("--session", required=True)
    priority.add_argument("--reason", required=True)
    status = sub.add_parser("status")
    status.add_argument("id", nargs="?")
    status.add_argument("--all", action="store_true", help="Include recent terminal history")
    result = sub.add_parser("result")
    result.add_argument("id")
    verify = sub.add_parser("verify-pilot")
    verify.add_argument("id")
    verify.add_argument("--activate", action="store_true", help="Enable only verified core coverage; other profiles remain held")
    health = sub.add_parser("health")
    sub.add_parser("serve")
    sub.add_parser("tick")
    wait = sub.add_parser("wait", help="Wait for a cached job result without agent polling")
    wait.add_argument("id")
    wait.add_argument("--timeout", type=float, default=7200)
    wait.add_argument("--poll", type=float, default=10)
    for command in (submit, priority, status, result, verify, health, wait):
        command.add_argument("--json", action="store_true", help="Emit complete machine-readable data")
    args = parser.parse_args()
    root = canonical_root(Path(__file__).resolve().parent.parent)
    queue = Queue(root / "logs/ci-coordinator/queue.sqlite3")
    if args.action == "submit":
        if args.mode == "visual-smoke":
            if args.spec:
                parser.error("Use --preview-url for visual-smoke")
            args.spec = args.preview_url
        elif args.preview_url:
            parser.error("--preview-url requires visual-smoke")
        if args.mode in ("component", "e2e", "artifact", "selfhost"):
            try:
                from scripts.ci_coverage import partition, execution_mode
            except ModuleNotFoundError:
                from ci_coverage import partition, execution_mode
            _, held = partition(args.spec)
            modes = [
                execution_mode(
                    spec,
                    subprocess.check_output(
                        ["git", "show", f"{args.source}:frontend/apps/web_app/tests/{spec}"],
                        cwd=root,
                        text=True,
                    ),
                )
                for spec in args.spec
            ]
            if any(mode != args.mode for mode in modes):
                raise RuntimeError("Selected specs require a different isolated runtime mode")
            if held:
                raise RuntimeError("Unsupported isolated coverage: " + json.dumps(held))
        try:
            from scripts.ci_candidate import load as load_candidate
        except ModuleNotFoundError:
            from ci_candidate import load as load_candidate
        candidate = load_candidate(root, args.source, require_fresh=True)
        receipts = enqueue_submission(
            queue,
            args.session,
            args.source,
            args.spec,
            args.mode,
            args.attempt,
            args.proof_video_profile,
            candidate,
            source_root=root,
            supersede=not args.keep_queued_generations,
            prepared_builds=args.prepared_builds,
        )
        print_receipt(receipts[0] if len(receipts) == 1 else receipts, as_json=args.json)
    elif args.action == "prioritize":
        print_receipt(queue.prioritize(args.id, args.session, args.reason), as_json=args.json)
    elif args.action == "status":
        rows = queue.status(args.id)
        if not args.id and not args.all:
            rows = [row for row in rows if row["state"] not in TERMINAL][:10]
        print_receipt(rows, as_json=args.json)
    elif args.action == "health":
        with queue.connect() as db:
            print_receipt(dict(db.execute("SELECT key, value FROM meta")), as_json=args.json)
    elif args.action == "verify-pilot":
        from ci_results import fetch
        try:
            from scripts.ci_coverage import verify_pilot
        except ModuleNotFoundError:
            from ci_coverage import verify_pilot
        receipt = queue.result(GitHub(root), args.id, root, fetch)
        checkpoint = verify_pilot(receipt)
        if args.activate:
            runtime_paths = [".github/workflows/isolated-tests.yml", "scripts/ci_environment.py",
                             "scripts/ci_run_tests.py", "scripts/ci_static_web.py"]
            drift = subprocess.check_output(
                ["git", "diff", "--name-only", receipt["harness_commit"], "HEAD", "--", *runtime_paths],
                cwd=root, text=True,
            ).strip()
            if drift:
                raise RuntimeError("CI runtime changed after pilot; new live evidence is required: " + drift)
            target = root / "logs/ci-coordinator/cutover.json"
            temporary = target.with_suffix("." + uuid.uuid4().hex + ".tmp")
            temporary.write_text(json.dumps(checkpoint, indent=2) + "\n")
            temporary.replace(target)
        print_receipt(checkpoint, as_json=args.json)
    elif args.action == "wait":
        row = wait_for_job(queue, args.id, timeout=args.timeout, poll=args.poll)
        if row["state"] == "success":
            from ci_results import fetch
            # A green workflow is not sufficient: validate exact-source artifacts once.
            row = queue.result(GitHub(root), args.id, root, fetch)
        print_receipt(row, as_json=args.json)
        return 0 if row["state"] == "success" else 1
    elif args.action == "result":
        from ci_results import fetch

        print_receipt(queue.result(GitHub(root), args.id, root, fetch), as_json=args.json)
    else:
        github = GitHub(root)
        while True:
            queue.tick(github)
            if args.action == "tick":
                break
            time.sleep(POLL_SECONDS)
    return 0


if __name__ == "__main__":
    sys.exit(main())
