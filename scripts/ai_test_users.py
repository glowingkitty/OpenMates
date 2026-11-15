#!/usr/bin/env python3
# contract-test-file: infrastructure
"""AI test users: simulated people use the real dev web app and report what breaks.

Dev-only test tooling, independent of Claude. Each persona
(`ai_test_users_personas.py`) gets its own throwaway dev account
(`dev_test_account.py`: real signup, gifted dev credits, chats exported and
the account deleted afterwards) and its own disposable E2B browser sandbox
(the Browse template, driven by `backend/scripts/ai_test_users/session.py`
inside the api container, where Vault secrets and the Browse model layer
live). Personas log in, use the app like a person would, and record video and
step screenshots; a Gemini judge reviews each session against a checklist and
Jev checks every finding against its screenshot.

  python3 scripts/ai_test_users.py run [--personas all|id,id] [--parallel 10] [--trial-copy]
  python3 scripts/ai_test_users.py tasks --run DIR [--exclude persona#n,...] [--dry-run]

`run` writes everything to ~/.openmates/ai-test-users/<run-id>/ (outside the
repository): per persona `result.json`, `transcript.json`, screenshots and
`video.webm`, plus `run.json` with costs and timings. `tasks` turns the kept
findings into OpenMates Tasks (label `ai-test-users`), merged within the run
and skipped when an open Task already covers them, with 48-hour signed links
to the video and screenshot and the durable local paths.

Hard budget (defaults, all enforced while running): per persona the harness
models (persona steps, judge, Jev) stop at --harness-cap-usd, the sandbox at
--e2b-cap-usd, and the app's own answers at --credit-cap dev credits (polled
through the account's CLI state; the persona is stopped when it is reached).
The run refuses to start when the sum of the caps exceeds --total-cap-usd.
Login values are passed on stdin only and never stored in the run directory.
"""

from __future__ import annotations

import argparse
import json
import os
import re
import shutil
import subprocess
import sys
import tempfile
import threading
import time
from concurrent.futures import ThreadPoolExecutor
from datetime import UTC, datetime
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import dev_test_account  # noqa: E402 - sibling script module
import e2b_dev_capacity  # noqa: E402
from ai_test_users_personas import select  # noqa: E402

ROOT = Path(__file__).resolve().parents[1]
RUNS = Path.home() / ".openmates" / "ai-test-users"
API_URL = dev_test_account.API_URL
APP_URL = "https://app.dev.openmates.org/"
ALLOWED_HOSTS = ["app.dev.openmates.org"]
CONTAINER = "api"
CONTAINER_WORKER = "/app/backend/scripts/ai_test_users/session.py"
CONTAINER_TRIAL_CODE = "/tmp/ai-test-users-code"
CONTAINER_OUTPUT = "/tmp/ai-test-users"
USD_PER_CREDIT = 0.001  # list price (backend/shared/python_utils/billing_utils.py)
CREDIT_POLL_SECONDS = 60
TASK_PROJECT = "96033196-e4b1-431e-b773-ba221e952fed"
TASK_LABEL = "ai-test-users"
STOPWORDS = set("the and for with that this when from into are not but has have was its on in of to a an is it "
                "shows shown show page app chat".split())


def log(message: str) -> None:
    print(f"[{datetime.now().strftime('%H:%M:%S')}] {message}", flush=True)


def docker(*args: str, stdin: str | None = None, timeout: int = 120) -> subprocess.CompletedProcess:
    return subprocess.run(["docker", *args], input=stdin, capture_output=True, text=True, timeout=timeout, check=False)


def credits_used(state_dir: Path) -> float | None:
    """Credits this (fresh) account has spent: the sum of the daily usage totals."""
    result = subprocess.run(
        ["openmates", "--api-url", API_URL, "settings", "billing", "usage", "daily", "--json"],
        env={**os.environ, "OPENMATES_STATE_DIR": str(state_dir), "NO_COLOR": "1"},
        capture_output=True, text=True, timeout=90, check=False,
    )
    try:
        days = json.loads(result.stdout).get("days")
    except (json.JSONDecodeError, AttributeError):
        days = None
    if not isinstance(days, list):
        log(f"credit usage unreadable: {(result.stdout or result.stderr)[:200]}")
        return None
    return float(sum(day.get("total_credits") or 0 for day in days if isinstance(day, dict)))


class PersonaRun:
    def __init__(self, persona: dict, run_id: str, run_dir: Path, args: argparse.Namespace) -> None:
        self.persona = persona
        self.run_id = run_id
        self.dir = run_dir / persona["id"]
        self.args = args
        self.account: dict | None = None
        self.state_dir = Path(tempfile.mkdtemp(prefix=f"aitu-{persona['id']}-"))
        os.chmod(self.state_dir, 0o700)
        self.summary: dict = {"persona": persona["id"], "name": persona["name"], "device": persona["device_label"]}

    def provision(self) -> None:
        test_name = f"ai-test-user-{self.persona['id']}"
        credentials = dev_test_account.provision_throwaway(test_name)
        self.account = {
            "email": credentials["OPENMATES_TEST_ACCOUNT_EMAIL"],
            "credentials": credentials,
            "test_name": test_name,
            "created_at": datetime.now(UTC).isoformat(),
        }
        dev_test_account.login_state(credentials, self.state_dir)
        log(f"{self.persona['id']}: account ready (credits used so far: {credits_used(self.state_dir)})")

    def job(self) -> dict:
        credentials = self.account["credentials"]
        return {
            "run_id": self.run_id,
            "persona": self.persona,
            "credentials": {
                "email": credentials["OPENMATES_TEST_ACCOUNT_EMAIL"],
                "password": credentials["OPENMATES_TEST_ACCOUNT_PASSWORD"],
                "otp_key": credentials["OPENMATES_TEST_ACCOUNT_OTP_KEY"],
            },
            "app_url": APP_URL,
            "allowed_hosts": ALLOWED_HOSTS,
            "output_dir": f"{CONTAINER_OUTPUT}/{self.run_id}/{self.persona['id']}",
            "stop_file": f"{CONTAINER_OUTPUT}/{self.run_id}/{self.persona['id']}.stop",
            "max_steps": self.args.max_steps,
            "max_minutes": self.args.max_minutes,
            "harness_cap_usd": self.args.harness_cap_usd,
            "e2b_cap_usd": self.args.e2b_cap_usd,
        }

    def watch_credits(self, done: threading.Event) -> None:
        stopped = False
        while not done.wait(CREDIT_POLL_SECONDS):
            used = credits_used(self.state_dir)
            if used is None:
                continue
            self.summary["credits_used_live"] = used
            if used >= self.args.credit_cap and not stopped:
                log(f"{self.persona['id']}: credit cap reached ({used:.0f}), stopping persona")
                docker("exec", CONTAINER, "touch", self.job()["stop_file"])
                self.summary["credit_cap_reached"] = True
                stopped = True

    def execute(self, worker: str) -> None:
        slot = e2b_dev_capacity.acquire(f"ai-test-user-{self.persona['id']}", timeout=900)
        if slot is None:
            self.summary["status"] = "no_e2b_slot"
            return
        done = threading.Event()
        watcher = threading.Thread(target=self.watch_credits, args=(done,), daemon=True)
        watcher.start()
        started = time.monotonic()
        try:
            result = subprocess.run(
                ["docker", "exec", "-i", CONTAINER, "python", worker],
                input=json.dumps(self.job()), capture_output=True, text=True,
                timeout=int(self.args.max_minutes * 60 + 1500), check=False,
            )
            (self.dir.parent / f"{self.persona['id']}.worker.log").write_text(result.stderr[-20000:])
            self.summary["worker_exit"] = result.returncode
        finally:
            done.set()
            slot.release()
        self.summary["wall_seconds"] = round(time.monotonic() - started, 1)
        source = f"{CONTAINER}:{CONTAINER_OUTPUT}/{self.run_id}/{self.persona['id']}"
        copied = docker("cp", source, str(self.dir.parent), timeout=300)
        if copied.returncode:
            self.summary["copy_error"] = copied.stderr[-300:]
        docker("exec", CONTAINER, "rm", "-rf", f"{CONTAINER_OUTPUT}/{self.run_id}/{self.persona['id']}",
               f"{CONTAINER_OUTPUT}/{self.run_id}/{self.persona['id']}.stop")
        result_file = self.dir / "result.json"
        if result_file.exists():
            result = json.loads(result_file.read_text())
            self.summary.update({k: result.get(k) for k in (
                "status", "steps", "harness_usd", "e2b", "error", "judge_error", "reply_timings", "sandbox_ready_seconds")})
            self.summary["findings_total"] = len(result.get("findings", []))
            self.summary["findings_kept"] = sum(1 for f in result.get("findings", []) if f.get("kept"))
            e2b = result.get("e2b") or {}
            if e2b.get("seconds"):
                e2b_dev_capacity.record_spend(e2b["seconds"], e2b.get("cpu", 2), e2b.get("memory_mb", 4096))
        else:
            self.summary.setdefault("status", "worker_failed")

    def finish(self) -> None:
        used = credits_used(self.state_dir)
        if used is not None:
            self.summary["credits_used"] = used
            self.summary["app_usd_list_price"] = round(self.summary["credits_used"] * USD_PER_CREDIT, 3)
        if self.account and not self.args.keep_accounts:
            receipt = dev_test_account.finish_throwaway(
                self.account["email"], self.account["test_name"], self.account["created_at"],
                self.account["credentials"],
            )
            self.summary["account"] = {"export": receipt.get("export", {}).get("status"),
                                       "chats_backup": receipt.get("export", {}).get("path"),
                                       "delete": receipt.get("delete", {}).get("status")}
        shutil.rmtree(self.state_dir, ignore_errors=True)


def command_run(args: argparse.Namespace) -> int:
    if not dev_test_account.server_is_development():
        raise SystemExit("AI test users run only against the development server.")
    personas = select(args.personas)
    per_persona = args.harness_cap_usd + args.e2b_cap_usd + args.credit_cap * USD_PER_CREDIT
    budget = per_persona * len(personas)
    if budget > args.total_cap_usd:
        raise SystemExit(f"caps add up to {budget:.2f} USD, above --total-cap-usd {args.total_cap_usd}")
    run_id = datetime.now(UTC).strftime("%Y%m%d-%H%M%S")
    run_dir = RUNS / run_id
    run_dir.mkdir(parents=True)
    worker = CONTAINER_WORKER
    if args.trial_copy:
        code = ROOT / "backend/scripts/ai_test_users"
        docker("exec", CONTAINER, "rm", "-rf", CONTAINER_TRIAL_CODE)
        docker("exec", CONTAINER, "mkdir", "-p", CONTAINER_TRIAL_CODE)
        copied = docker("cp", str(code), f"{CONTAINER}:{CONTAINER_TRIAL_CODE}/")
        if copied.returncode:
            raise SystemExit(f"could not copy the worker: {copied.stderr}")
        worker = f"{CONTAINER_TRIAL_CODE}/ai_test_users/session.py"
    log(f"run {run_id}: {len(personas)} personas, budget cap {budget:.2f} USD, output {run_dir}")
    started = time.monotonic()
    runs = [PersonaRun(p, run_id, run_dir, args) for p in personas]
    ready = []
    for run in runs:  # sequential: signup and login are rate limited
        try:
            run.provision()
            ready.append(run)
        except (dev_test_account.ThrowawayAccountError, subprocess.SubprocessError, KeyError) as exc:
            run.summary["status"] = "account_failed"
            run.summary["error"] = f"{type(exc).__name__}: {exc}"
            log(f"{run.persona['id']}: account failed: {exc}")
    with ThreadPoolExecutor(max_workers=args.parallel) as pool:
        list(pool.map(lambda r: r.execute(worker), ready))
    for run in runs:
        run.finish()
    summary = {
        "run_id": run_id,
        "started": run_id,
        "wall_seconds": round(time.monotonic() - started, 1),
        "budget_cap_usd": round(budget, 2),
        "caps": {"harness_usd": args.harness_cap_usd, "e2b_usd": args.e2b_cap_usd, "credits": args.credit_cap},
        "personas": [r.summary for r in runs],
    }
    totals = {
        "harness_usd": sum(r.summary.get("harness_usd") or 0 for r in runs),
        "e2b_usd": sum((r.summary.get("e2b") or {}).get("usd", 0) for r in runs),
        "app_usd_list_price": sum(r.summary.get("app_usd_list_price") or 0 for r in runs),
    }
    totals["total_usd"] = round(sum(totals.values()), 3)
    summary["totals"] = totals
    (run_dir / "run.json").write_text(json.dumps(summary, indent=1, ensure_ascii=False))
    log(f"done: {run_dir / 'run.json'} total {totals['total_usd']} USD")
    return 0


# --- Tasks ----------------------------------------------------------------------


def tokens(text: str) -> set[str]:
    return {w for w in re.findall(r"[a-zäöüß0-9]{3,}", text.lower()) if w not in STOPWORDS}


def similar(a: str, b: str) -> float:
    ta, tb = tokens(a), tokens(b)
    return len(ta & tb) / len(ta | tb) if ta and tb else 0.0


def open_tasks() -> list[dict]:
    result = subprocess.run(["openmates", "tasks", "list", "--json"], capture_output=True, text=True, timeout=120,
                            check=False)
    data = json.loads(result.stdout or "[]")
    rows = data.get("tasks", data) if isinstance(data, dict) else data
    return [t for t in rows if isinstance(t, dict) and str(t.get("status", "")).lower() not in ("done", "skipped")]


def upload(path: Path, alt: str) -> str:
    result = subprocess.run(
        [sys.executable, str(ROOT / "scripts/response_media.py"), str(path), "--alt", alt, "--output", "url"],
        capture_output=True, text=True, timeout=600, check=False,
    )
    return result.stdout.strip().splitlines()[-1] if result.returncode == 0 and result.stdout.strip() else ""


def command_tasks(args: argparse.Namespace) -> int:
    run_dir = Path(args.run)
    summary = json.loads((run_dir / "run.json").read_text())
    excluded = {e.strip() for e in (args.exclude or "").split(",") if e.strip()}
    findings = []
    for persona in summary["personas"]:
        result_file = run_dir / persona["persona"] / "result.json"
        if not result_file.exists():
            continue
        for index, finding in enumerate(json.loads(result_file.read_text()).get("findings", []), 1):
            finding_id = f"{persona['persona']}#{index}"
            if finding.get("kept") and finding_id not in excluded:
                findings.append({**finding, "id": finding_id, "persona": persona})
    clusters: list[list[dict]] = []
    for finding in findings:
        for cluster in clusters:
            if similar(finding["title"], cluster[0]["title"]) >= 0.45:
                cluster.append(finding)
                break
        else:
            clusters.append([finding])
    existing = open_tasks()
    plan = []
    for cluster in clusters:
        head = cluster[0]
        duplicate = max(existing, key=lambda t: similar(head["title"], str(t.get("title", ""))), default=None)
        score = similar(head["title"], str(duplicate.get("title", ""))) if duplicate else 0
        plan.append({"cluster": cluster, "duplicate": duplicate if score >= 0.5 else None})
    created = []
    for item in plan:
        cluster, duplicate = item["cluster"], item["duplicate"]
        head = cluster[0]
        ids = ", ".join(f["id"] for f in cluster)
        if duplicate:
            log(f"skip (covered by {duplicate.get('short_id') or duplicate.get('id')}): {head['title']} [{ids}]")
            created.append({"findings": ids, "duplicate_of": duplicate.get("short_id") or duplicate.get("id")})
            continue
        if args.dry_run:
            log(f"would create: {head['title']} [{ids}]")
            continue
        lines = [
            f"Found by the AI test-user trial (run {summary['run_id']}, dev web app). Not fixed by the run.",
            "",
            f"What happened: {head.get('evidence', '')}",
            f"Expected: {head.get('expected', '')}",
            f"Area: {head.get('surface', '')} · category {head.get('category', '')} · severity {head.get('severity', '')}",
            "",
        ]
        for finding in cluster:
            persona_dir = run_dir / finding["persona"]["persona"]
            shot = persona_dir / finding["screenshot"] if finding.get("screenshot") else None
            video = persona_dir / "video.webm"
            lines.append(f"- {finding['id']} ({finding['persona']['name']}, {finding['persona']['device']}), "
                         f"step {finding.get('step')}, Jev score {finding.get('jev_score')}")
            if shot and shot.exists():
                lines.append(f"  Screenshot (48 h link): {upload(shot, finding['title'])} · local: {shot}")
            if video.exists():
                lines.append(f"  Video (48 h link): {upload(video, finding['persona']['name'])} · local: {video}")
        lines.append("")
        lines.append(f"Transcript: {run_dir / cluster[0]['persona']['persona'] / 'transcript.json'} (dev server)")
        priority = {"high": "high", "medium": "medium", "low": "low"}.get(str(head.get("severity")), "medium")
        result = subprocess.run(
            ["openmates", "tasks", "create", "--title", head["title"][:150], "--description", "\n".join(lines),
             "--label", TASK_LABEL, "--priority", priority, "--project", TASK_PROJECT, "--assign", "unassigned",
             "--json"],
            capture_output=True, text=True, timeout=120, check=False,
        )
        task = json.loads(result.stdout).get("task", {}) if result.returncode == 0 else {}
        log(f"created {task.get('short_id') or task.get('id') or 'FAILED'}: {head['title']} [{ids}]")
        created.append({"findings": ids, "task": task.get("short_id") or task.get("id"), "title": head["title"],
                        "error": result.stderr[-300:] if result.returncode else None})
    if not args.dry_run:
        (run_dir / "tasks.json").write_text(json.dumps(created, indent=1, ensure_ascii=False))
    return 0


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = parser.add_subparsers(dest="command", required=True)
    run = sub.add_parser("run")
    run.add_argument("--personas", default="all")
    run.add_argument("--parallel", type=int, default=10)
    run.add_argument("--max-steps", type=int, default=40)
    run.add_argument("--max-minutes", type=float, default=22)
    run.add_argument("--harness-cap-usd", type=float, default=0.5)
    run.add_argument("--e2b-cap-usd", type=float, default=0.2)
    run.add_argument("--credit-cap", type=int, default=1300)
    run.add_argument("--total-cap-usd", type=float, default=20.0)
    run.add_argument("--trial-copy", action="store_true", help="run the worker from this checkout (before deploy)")
    run.add_argument("--keep-accounts", action="store_true")
    tasks = sub.add_parser("tasks")
    tasks.add_argument("--run", required=True)
    tasks.add_argument("--exclude", default="")
    tasks.add_argument("--dry-run", action="store_true")
    args = parser.parse_args(argv)
    return command_run(args) if args.command == "run" else command_tasks(args)


if __name__ == "__main__":
    raise SystemExit(main())
