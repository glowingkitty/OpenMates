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
from pathlib import Path
import re
import sqlite3
import subprocess
import sys
import time
import uuid

POLL_SECONDS = 30
MAX_ACTIVE = 4
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

    def dispatch(self, job: dict):
        self.request(
            f"repos/{self.repo}/actions/workflows/{WORKFLOW}/dispatches",
            {
                "ref": "dev",
                "inputs": {
                    "checkout_ref": job["source"],
                    "specs_json": job["specs"],
                    "mode": job["mode"],
                    "dispatch_token": job["token"],
                    "proof_video_profile": job.get("proof_profile", ""),
                },
            },
        )

    def run(self, run_id):
        return self.request(f"repos/{self.repo}/actions/runs/{run_id}")


class Queue:
    def __init__(self, path: Path):
        self.path = path
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
    ) -> dict:
        if not owner or not re.fullmatch(r"[0-9a-f]{40}", source):
            raise ValueError("Owner and full immutable source commit are required")
        if mode not in ("e2e", "artifact", "codex", "pytest", "vitest", "selfhost"):
            raise ValueError("Unknown CI mode")
        if proof_profile not in ("", "web-phone", "web-laptop") or (
            proof_profile and mode not in ("e2e", "artifact")
        ):
            raise ValueError("Invalid proof video profile")
        specs = sorted(set(specs))
        for spec in specs:
            if (
                not re.fullmatch(r"[A-Za-z0-9_./-]+\.spec\.ts", spec)
                or ".." in spec
                or spec.startswith("/")
            ):
                raise ValueError("Invalid spec path")
        if mode in ("e2e", "artifact") and not specs:
            raise ValueError("E2E requests require explicit specs")
        if mode == "selfhost" and specs != ["selfhost-smoke.spec.ts"]:
            raise ValueError("Installer runtime requires exactly its original smoke spec")
        if mode == "e2e":
            try:
                from scripts.ci_coverage import validate_runtime_batch
            except ModuleNotFoundError:
                from ci_coverage import validate_runtime_batch
            validate_runtime_batch(specs)
        encoded = json.dumps(specs, separators=(",", ":"))
        identity = [owner, source, specs, mode, nonce]
        if proof_profile:
            identity.append(proof_profile)
        key = hashlib.sha256(json.dumps(identity).encode()).hexdigest()
        now = time.time()
        with self.connect() as db:
            db.execute(
                "INSERT OR IGNORE INTO jobs(id,owner,source,specs,mode,token,state,created,updated,proof_profile) VALUES(?,?,?,?,?,?,?, ?,?,?)",
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
                ),
            )
            return dict(db.execute("SELECT * FROM jobs WHERE id=?", (key,)).fetchone())

    def status(self, key=None):
        with self.connect() as db:
            return [
                dict(row)
                for row in db.execute(
                    "SELECT * FROM jobs"
                    + (" WHERE id=?" if key else " ORDER BY created DESC LIMIT 100"),
                    (key,) if key else (),
                )
            ]

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
            return {"id": key, "reason": reason.strip(), "max_active": MAX_ACTIVE}

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
                    if int(budget["remaining"]) < RATE_RESERVE + MAX_ACTIVE + 2:
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
                    active = 0
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
                            active += 1
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
                            active += state == "running"
                        elif job["state"] in ACTIVE:
                            active += 1
                            if job["sent"] and now - job["sent"] > UNCERTAIN_SECONDS:
                                db.execute(
                                    "UPDATE jobs SET state='attention',error='Dispatch not visible; do not resubmit without remote reconciliation' WHERE id=?",
                                    (job["id"],),
                                )
                    db.commit()
                    # One writer owns admission across all callers, including daemon restarts.
                    for job in jobs:
                        if active >= MAX_ACTIVE:
                            break
                        if job["state"] != "queued" or by_token[job["token"]]:
                            continue
                        db.execute(
                            "UPDATE jobs SET state='dispatching',sent=?,updated=? WHERE id=?",
                            (now, now, job["id"]),
                        )
                        db.commit()
                        github.dispatch(job)
                        db.execute(
                            "UPDATE jobs SET state='submitted',updated=? WHERE id=?",
                            (now, job["id"]),
                        )
                        db.commit()
                        active += 1
                        # Respect GitHub's guidance to space mutating requests.
                        time.sleep(1)
                    self.set_meta(db, "last_error", "")
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


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest="action", required=True)
    submit = sub.add_parser("submit")
    submit.add_argument("--session", required=True)
    submit.add_argument("--source", required=True)
    submit.add_argument("--spec", action="append", default=[])
    submit.add_argument("--mode", choices=["e2e", "artifact", "codex", "pytest", "vitest", "selfhost"], default="e2e")
    submit.add_argument("--attempt", default="")
    submit.add_argument(
        "--proof-video-profile", choices=["web-phone", "web-laptop"], default=""
    )
    priority = sub.add_parser("prioritize")
    priority.add_argument("id")
    priority.add_argument("--session", required=True)
    priority.add_argument("--reason", required=True)
    status = sub.add_parser("status")
    status.add_argument("id", nargs="?")
    result = sub.add_parser("result")
    result.add_argument("id")
    verify = sub.add_parser("verify-pilot")
    verify.add_argument("id")
    verify.add_argument("--activate", action="store_true", help="Enable only verified core coverage; other profiles remain held")
    sub.add_parser("health")
    sub.add_parser("serve")
    sub.add_parser("tick")
    args = parser.parse_args()
    root = canonical_root(Path(__file__).resolve().parent.parent)
    queue = Queue(root / "logs/ci-coordinator/queue.sqlite3")
    if args.action == "submit":
        if args.mode in ("e2e", "artifact", "selfhost"):
            try:
                from scripts.ci_coverage import partition, execution_mode
            except ModuleNotFoundError:
                from ci_coverage import partition, execution_mode
            _, held = partition(args.spec)
            if any(execution_mode(spec) != args.mode for spec in args.spec):
                raise RuntimeError("Selected specs require a different isolated runtime mode")
            if held:
                raise RuntimeError("Unsupported isolated coverage: " + json.dumps(held))
        print(
            json.dumps(
                queue.enqueue(
                    args.session,
                    args.source,
                    args.spec,
                    args.mode,
                    args.attempt,
                    args.proof_video_profile,
                )
            )
        )
    elif args.action == "prioritize":
        print(json.dumps(queue.prioritize(args.id, args.session, args.reason)))
    elif args.action == "status":
        print(json.dumps(queue.status(args.id)))
    elif args.action == "health":
        with queue.connect() as db:
            print(json.dumps(dict(db.execute("SELECT key, value FROM meta"))))
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
        print(json.dumps(checkpoint))
    elif args.action == "result":
        from ci_results import fetch

        print(json.dumps(queue.result(GitHub(root), args.id, root, fetch)))
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
