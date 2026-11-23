#!/usr/bin/env python3
# contract-test-file: infrastructure
"""AI test users: simulated people use the real web app (dev, and prod when enabled) and report what breaks.

Each persona (`ai_test_users_personas.py`) signs up with a fresh account (`ai_test_users_accounts.py`),
redeems a single-use 1,000-credit gift card, uses the app in a disposable E2B browser sandbox driven by
`backend/scripts/ai_test_users/session.py` inside the api container, files up to 3 reports through the
app's own issue reporting, and deletes its account. A Gemini judge and Jev review the findings.

  python3 scripts/ai_test_users.py daily [--date YYYY-MM-DD] [--dry-run]
  python3 scripts/ai_test_users.py run [--target dev|prod] [--personas all|id,id] [--parallel 10]
  python3 scripts/ai_test_users.py tasks --run DIR [--exclude persona#n,...] [--dry-run]
  python3 scripts/ai_test_users.py message --run RUN_ID        # dry run of the run's Discord message
  python3 scripts/ai_test_users.py debug --env dev|prod --issue SHORT_ID   # Marco approved an issue

`daily` follows the rotation in `ai_test_users_schedule.py` (Monday to Friday 3 dev + 2 prod personas; no
scheduled run on Saturday or Sunday), retries failed account deletions, writes run.json and report.md, and sends the run's one
Discord message (`ai_test_users_message.py`). Clear functional errors start a debugging chat by themselves;
subjective findings wait for Marco's approval (`ai_test_users_triage.py`, owner, 23 Nov 2026). Prod runs need the flag file
~/.openmates/ai-test-users/prod-enabled and a gift card code in prod-gift-cards.txt. Everything is written
to ~/.openmates/ai-test-users/<run-id>/ (outside the repository). Cap: 3 USD per daily run.
"""

from __future__ import annotations

import argparse
import json
import re
import subprocess
import sys
import threading
import time
from concurrent.futures import ThreadPoolExecutor
from contextlib import contextmanager
from datetime import UTC, datetime
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import ai_test_users_accounts as accounts  # noqa: E402 - sibling script modules
import ai_test_users_deploy_guard as deploy_guard  # noqa: E402
import ai_test_users_exec as execution  # noqa: E402
import ai_test_users_message as message_text  # noqa: E402
import ai_test_users_report as reporting  # noqa: E402
import ai_test_users_triage as triage  # noqa: E402
import ai_test_users_scenarios as scenarios
import ai_test_users_video as video  # noqa: E402
import ai_test_users_schedule as schedule  # noqa: E402
import dev_test_account  # noqa: E402
from ai_test_users_personas import PERSONAS, select  # noqa: E402

ROOT = Path(__file__).resolve().parents[1]
RUNS = accounts.HOME
TASK_PROJECT = "96033196-e4b1-431e-b773-ba221e952fed"
TASK_LABEL = "ai-test-users"


LEASE_RENEW_SECONDS = 600  # the coordination lease expires after 30 minutes without renewal


@contextmanager
def dev_stack_lease(run_id: str):
    """Hold the shared dev-stack lease for the run: the workers live in the api container, so a coordinated
    `sessions.py docker restart` must wait for them instead of killing them mid-run."""
    import sessions  # heavy module; only the run commands need it

    lease_id = owner = f"ai-test-users-{run_id}"
    resources = {sessions.DOCKER_RESOURCE_DEV_STACK}
    sessions.acquire_test_resource_lease(lease_id, owner, resources, mode="shared", timeout=1800)
    stop = threading.Event()

    def renew() -> None:
        while not stop.wait(LEASE_RENEW_SECONDS):
            try:
                sessions.acquire_test_resource_lease(lease_id, owner, resources, mode="shared", timeout=60)
            except (RuntimeError, OSError) as exc:  # the run goes on; the next renewal tries again
                log(f"dev-stack lease renewal failed: {exc}")

    renewer = threading.Thread(target=renew, name="dev-stack-lease", daemon=True)
    renewer.start()
    try:
        yield
    finally:
        stop.set()
        sessions.release_test_resource_lease(lease_id)


def log(message: str) -> None:
    print(f"[{datetime.now().strftime('%H:%M:%S')}] {message}", flush=True)


def run_groups(groups: dict[str, list[dict]], run_id: str, run_dir: Path, cfg: execution.Settings,
               parallel: int) -> list[dict]:
    """Run the dev and prod groups side by side; each group keeps its signups sequential-friendly."""
    jobs = [(p, target) for target, personas in groups.items() for p in personas]
    with ThreadPoolExecutor(max_workers=max(1, parallel)) as pool:
        return list(pool.map(lambda j: execution.run_persona(j[0], j[1], run_id, run_dir, cfg), jobs))


def prod_update_wait(wait: bool) -> str | None:
    """None when a production run may start; else why not (the daily run pauses up to 90 min first)."""
    try:
        if wait:
            return deploy_guard.wait_until_clear(log=log)
        return deploy_guard.blocker(deploy_guard.current())
    except deploy_guard.GuardUnavailable as exc:
        return f"production update state unknown: {exc}"


def mark_prod_update_overlap(run: dict, run_dir: Path, started_at: datetime) -> None:
    """Mark a run whose prod personas overlapped a production update (owner, 23 Nov 2026)."""
    if not any(r.get("target") == "prod" for r in run["personas"]):
        return
    try:
        reason = deploy_guard.overlap(started_at, datetime.now(UTC), deploy_guard.current())
    except deploy_guard.GuardUnavailable as exc:
        reason = f"production update state unknown after the run: {exc}"
    if not reason:
        return
    run["prod_update_overlap"] = reason
    run["problems"].append(f"PRODUCTION issues of this run are deploy-time ({reason}); no debug chats for them")
    (run_dir / "run.json").write_text(json.dumps(run, indent=1, ensure_ascii=False))
    (run_dir / "report.md").write_text(reporting.report_markdown(run, run_dir))
    log(f"run overlapped a production update: {reason}")


def finish_run(run_id: str, run_dir: Path, kind: str, day: str, results: list[dict], areas: list[str],
               estimate: float, cap: float, started: float, deletions: list[dict]) -> dict:
    message_text.mark_suspects(results, base=accounts.HOME)
    totals = {
        "harness_usd": sum(r.get("harness_usd") or 0 for r in results),
        "e2b_usd": sum((r.get("e2b") or {}).get("usd", 0) for r in results),
        "app_usd_list_price": sum(r.get("app_usd_list_price") or 0 for r in results),
    }
    totals["total_usd"] = round(sum(totals.values()), 3)
    undeleted = sum(1 for e in accounts.pending_deletions(accounts.HOME) if e.get("run_id") == run_id)
    run = {"run_id": run_id, "date": day, "kind": kind, "areas": areas, "estimate_usd": estimate, "cap_usd": cap,
           "wall_seconds": round(time.monotonic() - started, 1), "personas": results, "totals": totals,
           "deletion_retries": deletions, "undeleted": undeleted,
           "problems": reporting.problems(results, undeleted)}
    (run_dir / "run.json").write_text(json.dumps(run, indent=1, ensure_ascii=False))
    (run_dir / "report.md").write_text(reporting.report_markdown(run, run_dir))
    return run


def command_daily(args: argparse.Namespace) -> int:
    day = reporting.parse_date(args.date)
    plan = schedule.personas_for(day, [p["id"] for p in PERSONAS])
    by_id = {p["id"]: p for p in PERSONAS}
    groups = {t: [by_id[i] for i in plan[t]] for t in ("dev", "prod") if plan[t]}
    if plan["kind"] == "none":
        log("no scheduled run on Saturdays and Sundays")
        return 0
    chosen = [i for t in groups for i in plan[t]]
    areas = schedule.areas_for(chosen, PERSONAS)
    count = sum(len(v) for v in groups.values())
    cfg = execution.Settings(base=accounts.HOME)
    reporting.check_cap(count, cfg.harness_cap_usd, cfg.e2b_cap_usd, args.total_cap_usd)
    estimate = reporting.estimate_usd(count, cfg.harness_cap_usd, cfg.e2b_cap_usd)
    cap = reporting.cap_for(args.total_cap_usd)
    log(f"{plan['kind']} run {day}: dev {plan['dev']} prod {plan['prod']} estimate {estimate} USD; areas {areas}")
    if args.dry_run:
        return 0
    if not dev_test_account.server_is_development():
        raise SystemExit("the AI test users run from the development server.")
    prod_skipped = prod_update_wait(wait=True) if "prod" in groups else None
    if prod_skipped:
        log(f"prod personas skipped: {prod_skipped}")
        groups.pop("prod")
        if not groups:
            return 0
    run_id = datetime.now(UTC).strftime("%Y%m%d-%H%M%S")
    run_dir = accounts.home() / run_id
    run_dir.mkdir(parents=True)
    started = time.monotonic()
    started_at = datetime.now(UTC)
    with dev_stack_lease(run_id):
        results = run_groups(groups, run_id, run_dir, cfg, args.parallel)
        deletions = execution.retry_deletions(run_id, run_dir, cfg)
    run = finish_run(run_id, run_dir, plan["kind"], day.isoformat(), results, areas, estimate, cap, started,
                     deletions)
    if prod_skipped:
        run["problems"].append(f"PRODUCTION personas skipped: {prod_skipped}")
        (run_dir / "run.json").write_text(json.dumps(run, indent=1, ensure_ascii=False))
    mark_prod_update_overlap(run, run_dir, started_at)
    log(f"done: {run_dir / 'report.md'} total {run['totals']['total_usd']} USD")
    issues = triage_run(run, run_dir, dispatch=True)
    if reporting.push_due(accounts.HOME, day.isoformat()):
        message_text.push(message_text.run_message(f"AI test users daily run {day.isoformat()}", results,
                                                   run["problems"], issues=issues))
        reporting.mark_pushed(accounts.HOME, day.isoformat())
    return 0


def triage_run(run: dict, run_dir: Path, dispatch: bool) -> list[dict]:
    """Route the run's issues, link open Tasks and chats that cover them, start the automatic debug chats
    (`dispatch`), and keep the outcome in run.json (owner, 23 Nov 2026)."""
    try:
        tasks = open_tasks()
    except (RuntimeError, json.JSONDecodeError, subprocess.TimeoutExpired) as exc:
        log(f"open Tasks could not be checked for duplicates: {exc}")
        tasks = None  # no automatic chat starts without the duplicate check
    chats = triage.running_chats()
    if run.get("prod_update_overlap"):
        # Deploy-time PRODUCTION issues start no chat; they are retested after the update instead.
        dev = [r for r in run["personas"] if r.get("target") != "prod"]
        prod = [r for r in run["personas"] if r.get("target") == "prod"]
        issues = triage.triage(dev, accounts.HOME, dispatch, tasks=tasks, chats=chats)
        deploy_time = triage.triage(prod, accounts.HOME, False, tasks=tasks, chats=chats)
        for issue in deploy_time:
            issue["debug"]["status"] = "deploy_time"
            issue["during_prod_update"] = True
        issues += deploy_time
    else:
        issues = triage.triage(run["personas"], accounts.HOME, dispatch, tasks=tasks, chats=chats)
    for issue in issues:
        log(f"{issue['env']} {issue.get('short_issue_id') or '-'}: {issue['debug']['status']} ({issue['title'][:80]})")
    if dispatch:
        run["issues"] = [{k: i.get(k) for k in ("env", "title", "short_issue_id", "issue_id", "debug",
                                                "during_prod_update")} for i in issues]
        (run_dir / "run.json").write_text(json.dumps(run, indent=1, ensure_ascii=False))
    return issues


def command_message(args: argparse.Namespace) -> int:
    """Dry run of an earlier run's push: routes, Task/chat coverage and the Discord payload; starts nothing."""
    run_dir = accounts.home() / args.run
    run = json.loads((run_dir / "run.json").read_text())
    issues = triage_run(run, run_dir, dispatch=False)
    text = message_text.run_message(f"AI test users daily run {run['date']}", run["personas"],
                                    run.get("problems") or [], run.get("flows"), issues=issues)
    print(json.dumps(message_text.discord_payload(text), indent=1, ensure_ascii=False))
    return 0


def command_debug(args: argparse.Namespace) -> int:
    """Marco approved an issue that waited for approval: start its debugging chat (no daily cap)."""
    import claude_dispatch
    import issues as issue_api

    issue_id = issue_api.resolve_issue_identifier(args.env, args.issue)
    outcome = claude_dispatch.launch_test_user_chat(issue_id, args.issue.upper(), args.env, ignore_cap=True)
    log(f"{args.env} {args.issue}: {outcome['status']} {outcome.get('chat_title', '')} {outcome.get('note', '')}")
    return 0 if outcome["status"] in ("started", "queued") else 1


DAILY_UNIT = "ai-test-users.service"


def failure_detail(unit: str) -> str:
    """systemd result plus the last error line of the unit's journal (logs never carry codes or passwords)."""
    shown = subprocess.run(["systemctl", "--user", "show", unit, "-p", "Result", "-p", "ExecMainStatus", "--value"],
                           capture_output=True, text=True, timeout=30, check=False).stdout.split()
    journal = subprocess.run(["journalctl", "--user", "-u", unit, "-n", "40", "--no-pager", "-o", "cat"],
                             capture_output=True, text=True, timeout=30, check=False).stdout.splitlines()
    lines = [line.strip() for line in journal if line.strip()]
    errors = [line for line in lines if "Error" in line or "Exit" in line or "error" in line]
    last = (errors or lines or ["no log"])[-1]
    return f"{' '.join(shown) or 'unknown result'}: {last}"


def command_notify_failure(args: argparse.Namespace) -> int:
    """OnFailure hook of the daily unit: one alert push for a run that crashed, timed out or was killed."""
    day = datetime.now(UTC).date().isoformat()
    accounts._push(reporting.crash_text(day, failure_detail(args.unit)), "AI test users")
    return 0


WORKER_COPY_DIR = "/tmp/ai-test-users-code"


def copy_worker_into_container() -> str:
    """Copy this checkout's worker into the api container (a check before the deploy lands)."""
    code = ROOT / "backend/scripts/ai_test_users"
    execution.docker("exec", execution.CONTAINER, "rm", "-rf", WORKER_COPY_DIR)
    execution.docker("exec", execution.CONTAINER, "mkdir", "-p", WORKER_COPY_DIR)
    copied = execution.docker("cp", str(code), f"{execution.CONTAINER}:{WORKER_COPY_DIR}/")
    if copied.returncode:
        raise SystemExit(f"could not copy the worker: {copied.stderr}")
    return f"{WORKER_COPY_DIR}/ai_test_users/session.py"


def command_run(args: argparse.Namespace) -> int:
    if args.target == "prod" and not accounts.prod_enabled():
        raise SystemExit("prod_disabled: create ~/.openmates/ai-test-users/prod-enabled first")
    if args.target == "prod" and not args.during_prod_update:
        blocked = prod_update_wait(wait=False)
        if blocked:
            raise SystemExit(f"prod_update: {blocked} (rerun later, or pass --during-prod-update on purpose)")
    if not dev_test_account.server_is_development():
        raise SystemExit("AI test users run from the development server.")
    personas = scenarios.personas_for(args.scenario, args.repeat, args.flows) if args.scenario else select(args.personas)
    cfg = execution.Settings(max_steps=args.max_steps, max_minutes=args.max_minutes,
                             harness_cap_usd=args.harness_cap_usd, e2b_cap_usd=args.e2b_cap_usd,
                             base=accounts.HOME)
    if args.worker_copy:
        cfg.worker = copy_worker_into_container()
    budget = reporting.estimate_usd(len(personas), cfg.harness_cap_usd, cfg.e2b_cap_usd)
    if budget > args.total_cap_usd:
        raise SystemExit(f"caps add up to {budget:.2f} USD, above --total-cap-usd {args.total_cap_usd}")
    run_id = datetime.now(UTC).strftime("%Y%m%d-%H%M%S")
    run_dir = accounts.home() / run_id
    run_dir.mkdir(parents=True)
    log(f"run {run_id}: {len(personas)} personas on {args.target}, budget cap {budget:.2f} USD, output {run_dir}")
    started = time.monotonic()
    started_at = datetime.now(UTC)
    with dev_stack_lease(run_id):
        results = run_groups({args.target: personas}, run_id, run_dir, cfg, args.parallel)
        deletions = execution.retry_deletions(run_id, run_dir, cfg)
    run = finish_run(run_id, run_dir, "manual", datetime.now(UTC).date().isoformat(), results,
                     schedule.areas_for([p["id"] for p in personas], PERSONAS), budget, args.total_cap_usd,
                     started, deletions)
    mark_prod_update_overlap(run, run_dir, started_at)
    log(f"done: {run_dir / 'run.json'} total {run['totals']['total_usd']} USD")
    title = f"AI test users manual run on {args.target} {run['date']}"
    if args.scenario:
        run["flows"] = scenarios.flow_verdicts(results)
        (run_dir / "run.json").write_text(json.dumps(run, indent=1, ensure_ascii=False))
        (run_dir / "report.md").write_text(reporting.report_markdown(run, run_dir))
        for flow, entry in run["flows"].items():
            log(f"flow {flow}: {entry['verdict']} ({entry['passed']}/{entry['runs']})")
        title = f"AI test users {args.scenario} run on {args.target} {run['date']}"
    message = message_text.run_message(title, results, run["problems"], run.get("flows"))
    if args.notify:
        message_text.push(message)
    return 0


# --- Tasks ----------------------------------------------------------------------


def persona_dir(run_dir: Path, persona: dict) -> Path:
    """Run layout is <run>/<target>/<persona>; older dev-only runs used <run>/<persona>."""
    nested = run_dir / persona.get("target", "dev") / persona["persona"]
    return nested if nested.exists() else run_dir / persona["persona"]


similar = message_text.similar


def id_set(text: str | None) -> set[str]:
    return {e.strip() for e in (text or "").split(",") if e.strip()}


def merge_groups(text: str | None) -> list[list[str]]:
    """`a#1+b#2,c#1+d#3`: reviewer-confirmed groups of findings that are one defect."""
    return [[i.strip() for i in group.split("+") if i.strip()] for group in (text or "").split(",") if "+" in group]


def is_slow(finding: dict) -> bool:
    return str(finding.get("category", "")).lower().startswith("slow")


def slow_title(cluster: list[dict]) -> str:
    seconds = [float(v) for f in cluster for v in re.findall(r"(\d+(?:\.\d+)?)\s?s\b", str(f.get("evidence", "")))]
    seconds = [v for v in seconds if v >= 20] or [0.0]
    sessions = len({f["persona"]["persona"] for f in cluster})
    return f"Slow chat replies on dev: {sessions} test users waited {min(seconds):.0f}-{max(seconds):.0f} s for answers"


def cluster_findings(findings: list[dict], groups: list[list[str]]) -> list[list[dict]]:
    """One cluster per defect: reviewer groups first, all slow replies together, then similar titles."""
    by_id = {f["id"]: f for f in findings}
    clusters: list[list[dict]] = []
    placed: set[str] = set()
    for group in groups:
        members = [by_id[i] for i in group if i in by_id and i not in placed]
        if members:
            clusters.append(members)
            placed.update(f["id"] for f in members)
    slow = [f for f in findings if is_slow(f) and f["id"] not in placed]
    if slow:
        clusters.append([{**f, "auto_slow": True} for f in slow])
        placed.update(f["id"] for f in slow)
    for finding in findings:
        if finding["id"] in placed:
            continue
        for cluster in clusters:
            if similar(finding["title"], cluster[0]["title"]) >= 0.45:
                cluster.append(finding)
                break
        else:
            clusters.append([finding])
    return clusters


def open_tasks() -> list[dict]:
    result = subprocess.run(["openmates", "tasks", "list", "--json"], capture_output=True, text=True, timeout=120,
                            check=False)
    if result.returncode:
        raise RuntimeError(f"openmates tasks list failed: {(result.stderr or result.stdout).strip()[-200:]}")
    data = json.loads(result.stdout or "[]")
    rows = data.get("tasks", data) if isinstance(data, dict) else data
    return [t for t in rows if isinstance(t, dict) and str(t.get("status", "")).lower() not in ("done", "skipped")]


UPLOADED: dict[Path, str] = {}


def upload(path: Path, alt: str) -> str:
    if path in UPLOADED:
        return UPLOADED[path]
    result = subprocess.run(
        [sys.executable, str(ROOT / "scripts/response_media.py"), str(path), "--alt", alt, "--output", "url"],
        capture_output=True, text=True, timeout=600, check=False,
    )
    url = result.stdout.strip().splitlines()[-1] if result.returncode == 0 and result.stdout.strip() else ""
    if url:
        UPLOADED[path] = url
    return url


def command_tasks(args: argparse.Namespace) -> int:
    run_dir = Path(args.run)
    summary = json.loads((run_dir / "run.json").read_text())
    excluded = id_set(args.exclude)
    included = id_set(args.include)
    findings = []
    for persona in summary["personas"]:
        result_file = persona_dir(run_dir, persona) / "result.json"
        if not result_file.exists():
            continue
        for index, finding in enumerate(json.loads(result_file.read_text()).get("findings", []), 1):
            finding_id = f"{persona['persona']}#{index}"
            if (finding.get("kept") or finding_id in included) and finding_id not in excluded:
                findings.append({**finding, "id": finding_id, "persona": persona})
    clusters = cluster_findings(findings, merge_groups(args.merge))
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
        title = slow_title(cluster) if len(cluster) > 1 and all(f.get("auto_slow") for f in cluster) else head["title"]
        ids = ", ".join(f["id"] for f in cluster)
        if duplicate:
            log(f"skip (covered by {duplicate.get('short_id') or duplicate.get('id')}): {head['title']} [{ids}]")
            created.append({"findings": ids, "duplicate_of": duplicate.get("short_id") or duplicate.get("id")})
            continue
        if args.dry_run:
            log(f"would create: {title} [{ids}]")
            continue
        lines = [
            f"Found by the AI test-user trial (run {summary['run_id']}, web app). Not fixed by the run.",
            "",
            f"What happened: {head.get('evidence', '')}",
            f"Expected: {head.get('expected', '')}",
            f"Area: {head.get('surface', '')} · category {head.get('category', '')} · severity {head.get('severity', '')}",
            "",
        ]
        for finding in cluster:
            pdir = persona_dir(run_dir, finding["persona"])
            shot = pdir / finding["screenshot"] if finding.get("screenshot") else None
            video = pdir / "video.webm"
            lines.append(f"- {finding['id']} ({finding['persona']['name']}, {finding["persona"].get("device", finding["persona"].get("target", ""))}), "
                         f"step {finding.get('step')}, Jev score {finding.get('jev_score')}")
            if shot and shot.exists():
                lines.append(f"  Screenshot (48 h link): {upload(shot, finding['title'])} · local: {shot}")
            if video.exists():
                lines.append(f"  Video (48 h link): {upload(video, finding['persona']['name'])} · local: {video}")
        lines.append("")
        lines.append(f"Transcript: {persona_dir(run_dir, cluster[0]['persona']) / 'transcript.json'} (local)")
        priority = {"high": "high", "medium": "medium", "low": "low"}.get(str(head.get("severity")), "medium")
        result = subprocess.run(
            ["openmates", "tasks", "create", "--title", title[:150], "--description", "\n".join(lines),
             "--label", TASK_LABEL, "--priority", priority, "--project", TASK_PROJECT, "--assign", "unassigned",
             "--json"],
            capture_output=True, text=True, timeout=120, check=False,
        )
        task = json.loads(result.stdout).get("task", {}) if result.returncode == 0 else {}
        log(f"created {task.get('short_id') or task.get('id') or 'FAILED'}: {title} [{ids}]")
        created.append({"findings": ids, "task": task.get("short_id") or task.get("id"), "title": title,
                        "error": result.stderr[-300:] if result.returncode else None})
    if not args.dry_run:
        (run_dir / "tasks.json").write_text(json.dumps(created, indent=1, ensure_ascii=False))
    return 0


def command_videos(args: argparse.Namespace) -> int:
    run = video.attach_run(accounts.home() / args.run)
    for r in run["personas"]:
        reports = ", ".join(f"{rep.get('short_issue_id')} {reporting.video_link(r, reporting.report_moment(r, rep))}"
                            for rep in r.get("reports", []) if rep.get("short_issue_id"))
        print(f"{r['target']}/{r['persona']}: {reporting.video_link(r) or r.get('video_error')}"
              + (f" | reports: {reports}" if reports else ""))
    return 0


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = parser.add_subparsers(dest="command", required=True)
    run = sub.add_parser("run")
    run.add_argument("--target", choices=("dev", "prod"), default="dev")
    run.add_argument("--personas", default="all")
    run.add_argument("--parallel", type=int, default=10)
    run.add_argument("--max-steps", type=int, default=40)
    run.add_argument("--max-minutes", type=float, default=22)
    run.add_argument("--harness-cap-usd", type=float, default=0.5)
    run.add_argument("--e2b-cap-usd", type=float, default=0.2)
    run.add_argument("--total-cap-usd", type=float, default=20.0)
    run.add_argument("--worker-copy", action="store_true", help="run the worker from this checkout (before deploy)")
    run.add_argument("--scenario", choices=sorted(scenarios.SCENARIOS), default=None,
                     help="run a fixed-goal scenario instead of --personas (unmet goals count as problems)")
    run.add_argument("--flows", default="", help="scenario flows to run, e.g. b,c,e (default: all)")
    run.add_argument("--repeat", type=int, default=2, help="accounts per scenario flow (flaky = mixed results)")
    run.add_argument("--notify", action="store_true",
                     help="send the run summary push (an alert listing the problems when anything failed)")
    run.add_argument("--during-prod-update", action="store_true",
                     help="start a prod run although production is updating (its issues are still marked)")
    notify = sub.add_parser("notify-failure")
    notify.add_argument("--unit", default=DAILY_UNIT)
    daily = sub.add_parser("daily")
    daily.add_argument("--date", default=None)
    daily.add_argument("--dry-run", action="store_true")
    daily.add_argument("--parallel", type=int, default=5)
    daily.add_argument("--total-cap-usd", type=float, default=None, help="override the daily cap")
    videos = sub.add_parser("videos", help="upload an earlier run's recordings and link them in its report")
    videos.add_argument("--run", required=True)
    message = sub.add_parser("message", help="dry run of an earlier run's Discord message (starts no chat)")
    message.add_argument("--run", required=True)
    debug = sub.add_parser("debug", help="start the debugging chat for an issue Marco approved")
    debug.add_argument("--env", choices=("dev", "prod"), required=True)
    debug.add_argument("--issue", required=True, help="short issue id from the run message")
    tasks = sub.add_parser("tasks")
    tasks.add_argument("--run", required=True)
    tasks.add_argument("--exclude", default="", help="finding ids a reviewer rejected (persona#n,...)")
    tasks.add_argument("--include", default="", help="finding ids Jev dropped that a reviewer confirmed")
    tasks.add_argument("--merge", default="", help="reviewer groups of one defect: a#1+b#2,c#1+d#3")
    tasks.add_argument("--dry-run", action="store_true")
    args = parser.parse_args(argv)
    return {"run": command_run, "daily": command_daily, "tasks": command_tasks,
            "notify-failure": command_notify_failure, "videos": command_videos,
            "message": command_message, "debug": command_debug}[args.command](args)


if __name__ == "__main__":
    raise SystemExit(main())
