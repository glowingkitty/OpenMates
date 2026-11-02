#!/usr/bin/env python3
"""Prepare the weekday voice-call daily meeting brief and announce it on Discord.

Pipeline (weekday 08:45 Europe/Berlin via the dev-server crontab):
  collect  -> deterministic evidence JSON (Claude chats, git, Tasks, nightly checks)
  render   -> headless `claude -p` (no tools) writes a voice-friendly Markdown brief
  send     -> Discord webhook message with the brief attached

Outputs are private and gitignored under logs/daily-meetings/. The brief is pasted
into a regular Claude voice chat; its outcome block is imported afterwards by the
daily meeting skill. Task records carry no timestamps, so "changed since the last
meeting" is computed by diffing a saved status snapshot.
"""

from __future__ import annotations

import argparse
from datetime import datetime, timedelta, timezone
import json
import os
from pathlib import Path
import re
import subprocess
import sys
from zoneinfo import ZoneInfo

ROOT = Path(__file__).resolve().parents[1]
TZ = ZoneInfo("Europe/Berlin")
PROJECT_ID = "96033196-e4b1-431e-b773-ba221e952fed"
TRANSCRIPTS = Path.home() / ".claude" / "projects"
WEBHOOK_KEYS = ("DISCORD_WEBHOOK_DAILY_MEETING", "DISCORD_WEBHOOK_DEV_NIGHTLY")
SECRET = re.compile(
    r"(sk-[A-Za-z0-9_-]{16,}|gh[pousr]_[A-Za-z0-9]{20,}|xox[abp]-[A-Za-z0-9-]{10,}|"
    r"AKIA[0-9A-Z]{16}|eyJ[A-Za-z0-9_-]{20,}\.[A-Za-z0-9_-]{10,}\.[A-Za-z0-9_-]{10,}|"
    r"https://discord(?:app)?\.com/api/webhooks/\S+)"
)
EMAIL = re.compile(r"[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}")


def clean(text: str, limit: int) -> str:
    text = EMAIL.sub("<email>", SECRET.sub("<redacted>", text or "")).strip()
    return text if len(text) <= limit else text[: limit - 1].rstrip() + "…"


def parse_ts(value: str | None) -> datetime | None:
    try:
        return datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    except ValueError:
        return None


def configured_value(root: Path, key: str) -> str:
    if os.environ.get(key):
        return os.environ[key]
    env = root / ".env"
    if env.is_file():
        for line in env.read_text().splitlines():
            name, sep, value = line.strip().partition("=")
            if sep and name.strip() == key:
                return value.strip().strip("'\"")
    return ""


def meeting_dir(root: Path) -> Path:
    path = root / "logs" / "daily-meetings"
    path.mkdir(parents=True, exist_ok=True)
    return path


def load_state(out: Path) -> dict:
    try:
        return json.loads((out / "brief-state.json").read_text())
    except (OSError, ValueError):
        return {}


def default_since(now: datetime) -> datetime:
    """Previous weekday 08:45 Berlin (Monday reaches back to Friday)."""
    local = now.astimezone(TZ)
    day = local.date() - timedelta(days=1)
    while day.weekday() >= 5:
        day -= timedelta(days=1)
    return datetime(day.year, day.month, day.day, 8, 45, tzinfo=TZ)


# ── Claude chats ──────────────────────────────────────────────────────────────

def _text_blocks(content) -> list[str]:
    if isinstance(content, str):
        return [content]
    if isinstance(content, list):
        return [b.get("text", "") for b in content if isinstance(b, dict) and b.get("type") == "text"]
    return []


def summarize_transcript(path: Path, since: datetime) -> dict | None:
    prompts, replies, title, first, last, branch, tools = [], [], "", None, None, "", set()
    try:
        lines = path.read_text(errors="replace").splitlines()
    except OSError:
        return None
    for line in lines:
        try:
            row = json.loads(line)
        except ValueError:
            continue
        kind = row.get("type")
        if kind in ("summary", "ai-title", "custom-title"):
            title = row.get("summary") or row.get("title") or row.get("aiTitle") or title
        if kind == "tools-used":
            tools.update(row.get("tools") or [])
        if row.get("isSidechain") or kind not in ("user", "assistant"):
            continue
        ts = parse_ts(row.get("timestamp"))
        if ts is None or ts < since:
            continue
        first, last = first or ts, ts
        branch = row.get("gitBranch") or branch
        texts = [t for t in _text_blocks((row.get("message") or {}).get("content")) if t.strip()]
        if not texts:
            continue
        if kind == "user" and row.get("turnOrigin", (row.get("origin") or {}).get("kind")) == "human":
            body = "\n".join(texts)
            if not body.lstrip().startswith("<"):  # skip injected reminders/command wrappers
                prompts.append(clean(body, 1200))
        elif kind == "assistant":
            replies.append("\n".join(texts))
    if not prompts:
        return None
    return {
        "session": path.stem[:8],
        "title": clean(title, 120),
        "started": first.astimezone(TZ).strftime("%a %H:%M"),
        "last_activity": last.astimezone(TZ).strftime("%a %H:%M"),
        "branch": branch,
        "user_prompts": prompts[:12] + ([f"(+{len(prompts) - 12} more prompts)"] if len(prompts) > 12 else []),
        "final_replies": [clean(r, 2500) for r in replies[-2:]],
        "tools": sorted(tools)[:12],
        "_sort": last.isoformat(),
    }


def claude_chats(since: datetime, base: Path = TRANSCRIPTS) -> list[dict]:
    chats = []
    for path in sorted(base.glob("*/*.jsonl")):
        try:
            if datetime.fromtimestamp(path.stat().st_mtime, timezone.utc) < since:
                continue
        except OSError:
            continue
        summary = summarize_transcript(path, since)
        if summary:
            chats.append(summary)
    chats.sort(key=lambda c: c["_sort"])
    for chat in chats:
        chat.pop("_sort")
    return chats


# ── Git, Tasks, nightly checks ────────────────────────────────────────────────

def git(root: Path, *args: str) -> str:
    return subprocess.run(["git", *args], cwd=root, capture_output=True, text=True, timeout=120).stdout.strip()


def git_summary(root: Path, since: datetime, gaps: list[str]) -> dict:
    if subprocess.run(["git", "fetch", "-q", "origin", "dev", "main"], cwd=root,
                      capture_output=True, timeout=120).returncode:
        gaps.append("git fetch failed; commit data may be stale")
    log = git(root, "log", "origin/dev", f"--since={since.isoformat()}", "--no-merges",
              "--format=%h%x1f%cI%x1f%s")
    commits = []
    for line in log.splitlines():
        sha, when, subject = (line.split("\x1f") + ["", ""])[:3]
        commits.append({"sha": sha, "when": parse_ts(when).astimezone(TZ).strftime("%a %H:%M"),
                        "subject": clean(subject, 160)})
    return {
        "commits_on_dev": commits,
        "dev_ahead_of_main": int(git(root, "rev-list", "--count", "origin/main..origin/dev") or 0),
        "last_main_commit": git(root, "log", "origin/main", "-1", "--format=%h %cs %s"),
    }


def task_snapshot(gaps: list[str], project: str = PROJECT_ID) -> list[dict] | None:
    try:
        run = subprocess.run(["openmates", "tasks", "list", "--project", project, "--json"],
                             capture_output=True, text=True, timeout=180)
        data = json.loads(run.stdout)
    except (OSError, subprocess.TimeoutExpired, ValueError) as error:
        gaps.append(f"OpenMates Tasks unavailable ({type(error).__name__})")
        return None
    if not data.get("complete", True):
        gaps.append("OpenMates Tasks list reported an incomplete page")
    return [{
        "id": t.get("short_id"), "title": clean(t.get("title", ""), 160), "status": t.get("status"),
        "priority": t.get("priority_level") or "none",
        "blocked": t.get("blocked_reason_code") or "", "due": t.get("due_at") or "",
        "assignee": t.get("assignee_type") or "",
    } for t in data.get("tasks", [])]


def task_summary(tasks: list[dict] | None, previous: list[dict] | None) -> dict:
    if tasks is None:
        return {}
    by_status: dict[str, list] = {}
    for task in tasks:
        by_status.setdefault(task["status"], []).append(task)
    old = {t["id"]: t["status"] for t in previous or []}
    changes = [{"id": t["id"], "title": t["title"], "from": old.get(t["id"], "new"), "to": t["status"]}
               for t in tasks if old.get(t["id"]) != t["status"]] if previous else []
    return {
        "counts": {k: len(v) for k, v in by_status.items()},
        "open": {s: by_status.get(s, []) for s in ("in_progress", "blocked", "todo", "backlog")},
        "changed_since_last_meeting": changes,
        "baseline": "previous snapshot" if previous else "none (first run; no change diff)",
    }


def _run_results(root: Path, run: dict) -> dict:
    """Per-test outcome of one nightly run from its CI receipts and held reasons."""
    passed, failed, missing = [], [], []
    for job in run.get("jobs") or []:
        try:
            receipt = json.loads((root / "test-results" / "ci-runs" / job / "receipt.json").read_text())
        except (OSError, ValueError):
            missing.append(job[:12])
            continue
        results = (receipt.get("report") or {}).get("results") or []
        if not results:
            failed.append({"test": ", ".join(receipt.get("selected_specs") or []) or f"job {job[:12]}",
                           "reason": f"no test report (receipt state {receipt.get('state')})"})
        for result in results:
            name = result.get("spec") or result.get("suite") or f"job {job[:12]}"
            if result.get("exit_code") == 0:
                passed.append(name)
            else:
                tests = result.get("failed_tests") or []
                failed.append({"test": name, "reason": clean("; ".join(map(str, tests[:3])) or
                                                             f"exit code {result.get('exit_code')}", 200)})
    held = run.get("held_reasons") or {}
    return {
        "passed_count": len(passed), "failed_count": len(failed),
        "not_run_count": len(run.get("held_specs") or []), "missing_receipts": missing,
        "failed": failed, "passed": sorted(passed),
        "not_run": [{"test": s, "reason": clean(held.get(s, "held"), 160)} for s in run.get("held_specs") or []],
    }


def nightly(root: Path, since: datetime) -> dict:
    out: dict = {}
    runs = []
    for path in (root / "test-results" / "daily-runs").glob("*.json"):
        try:
            run = json.loads(path.read_text())
        except ValueError:
            continue
        if run.get("run_date"):
            runs.append(run)
    runs.sort(key=lambda r: r.get("created", 0))
    if runs:
        out["nightly_test_runs_last_14"] = [
            {"date": r["run_date"], "status": r.get("status"), "jobs": len(r.get("jobs") or []),
             "error": clean(r.get("selection_error") or "", 200)} for r in runs[-14:]]
        broken = 0
        for run in reversed(runs):
            if run.get("jobs"):
                break
            broken += 1
        out["nights_without_any_test_jobs"] = broken
        last = next((r for r in reversed(runs) if r.get("jobs")), None)
        if last:
            out["last_nightly_run_with_tests"] = {"date": last["run_date"],
                                                  "source_commit": (last.get("source_commit") or "")[:10],
                                                  **_run_results(root, last)}
    reports = {}
    cutoff = since - timedelta(hours=12)
    for path in sorted((root / "logs" / "nightly-reports").glob("*")):
        if not path.is_file() or datetime.fromtimestamp(path.stat().st_mtime, timezone.utc) < cutoff:
            continue
        if path.suffix == ".json" and path.with_suffix(".md").exists():
            continue  # the Markdown twin is the readable summary
        reports[path.name] = clean(path.read_text(errors="replace"), 1500)
    out["reports_updated_recently"] = reports
    return out


def previous_outcome(out: Path, today: str) -> str:
    outcomes = sorted(p for p in out.glob("*-outcome.md") if not p.name.startswith(today))
    return clean(outcomes[-1].read_text(), 6000) if outcomes else ""


def collect(root: Path, now: datetime, since: datetime, out: Path) -> tuple[dict, list | None]:
    gaps: list[str] = []
    tasks = task_snapshot(gaps)
    snapshots = sorted(out.glob("*-tasks.json"))
    previous = json.loads(snapshots[-1].read_text()) if snapshots else None
    chats = claude_chats(since)
    if not chats:
        gaps.append("no Claude Code chats found on the dev server for this window")
    gaps.append("only Claude Code chats stored on the dev server are included; claude.ai chats and "
                "Apple Calendar/Reminders are not visible to the server")
    evidence = {
        "meeting_date": now.astimezone(TZ).strftime("%A %Y-%m-%d"),
        "window": {"since": since.astimezone(TZ).isoformat(timespec="minutes"),
                   "until": now.astimezone(TZ).isoformat(timespec="minutes")},
        "previous_meeting_outcome": previous_outcome(out, now.astimezone(TZ).date().isoformat()),
        "claude_chats": chats,
        "git": git_summary(root, since, gaps),
        "tasks": task_summary(tasks, previous),
        "nightly": nightly(root, since),
        "gaps": gaps,
    }
    return evidence, tasks


# ── Render + Discord ──────────────────────────────────────────────────────────

def render(evidence: dict, prompt_path: Path, timeout: int = 900) -> str:
    prompt = prompt_path.read_text() + "\n\n<evidence>\n" + json.dumps(evidence, indent=1) + "\n</evidence>\n"
    run = subprocess.run(
        ["claude", "-p", "--tools", "", "--no-session-persistence", "--output-format", "text"],
        input=prompt, capture_output=True, text=True, timeout=timeout, cwd=prompt_path.parent,
    )
    brief = run.stdout.strip()
    if run.returncode or len(brief) < 500:
        raise RuntimeError(f"brief generation failed (exit {run.returncode}): {clean(run.stderr, 300)}")
    return brief + "\n"


def send(root: Path, brief_path: Path, headline: str) -> dict:
    sys.path.insert(0, str(root / "scripts"))
    import discord_webhook  # noqa: E402 - repo-local helper, path set just above

    for key in WEBHOOK_KEYS:
        url = configured_value(root, key)
        if url:
            result = discord_webhook.post_attachment(
                webhook_url=url, payload={"content": headline[:1900]},
                content=brief_path.read_bytes(), filename=brief_path.name)
            if not result:
                raise RuntimeError(f"Discord delivery via {key} was not confirmed")
            return {"channel": key, **result}
    raise RuntimeError(f"no Discord webhook configured ({', '.join(WEBHOOK_KEYS)})")


def notify_failure(root: Path, message: str) -> None:
    sys.path.insert(0, str(root / "scripts"))
    import discord_webhook  # noqa: E402 - repo-local helper, path set just above

    for key in WEBHOOK_KEYS:
        url = configured_value(root, key)
        if url:
            discord_webhook.post_message(webhook_url=url, payload={"content": message[:1900]})
            return


def headline_for(brief: str, day: str) -> str:
    match = re.search(r"^##\s*(?:\d+\.\s*)?(?:TL;?DR|Summary)[^\n]*\n(.*?)(?=^## |\Z)", brief, re.M | re.S | re.I)
    summary = match.group(1).strip() if match else ""
    return (f"**Daily meeting brief ready — {day}**\nOpen the attachment, paste it into a Claude "
            f"voice chat and start the call.\n\n{summary}").strip()


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("command", choices=("collect", "run", "send"))
    parser.add_argument("--root", type=Path, default=ROOT)
    parser.add_argument("--out-dir", type=Path)
    parser.add_argument("--since", help="ISO timestamp; default: last brief or previous weekday 08:45")
    parser.add_argument("--brief", type=Path, help="send: existing brief file")
    parser.add_argument("--scheduled", action="store_true",
                        help="cron mode: only weekdays in the 08:xx Berlin hour, once per day")
    parser.add_argument("--force", action="store_true", help="regenerate even if today's brief exists")
    parser.add_argument("--no-send", action="store_true")
    args = parser.parse_args(argv)

    root = args.root.resolve()
    out = args.out_dir.resolve() if args.out_dir else meeting_dir(root)
    out.mkdir(parents=True, exist_ok=True)
    now = datetime.now(timezone.utc)
    local = now.astimezone(TZ)
    day = local.date().isoformat()
    brief_path = out / f"{day}-brief.md"

    if args.command == "send":
        path = args.brief or brief_path
        print(json.dumps(send(root, path, headline_for(path.read_text(), day))))
        return 0
    if args.scheduled and (local.weekday() >= 5 or local.hour != 8):
        return 0  # crontab fires in both CET/CEST candidate hours; only 08:xx Berlin proceeds
    if args.command == "run" and brief_path.exists() and not args.force:
        print(f"brief already exists: {brief_path}")
        return 0

    state = load_state(out)
    since = parse_ts(args.since) or parse_ts(state.get("last_brief_until")) or default_since(now)
    evidence, tasks = collect(root, now, since, out)
    (out / f"{day}-evidence.json").write_text(json.dumps(evidence, indent=1))
    if args.command == "collect":
        print(out / f"{day}-evidence.json")
        return 0
    try:
        brief = render(evidence, Path(__file__).with_name("daily_meeting_brief_prompt.md"))
    except (RuntimeError, OSError, subprocess.TimeoutExpired) as error:
        if not args.no_send:
            notify_failure(root, f"⚠️ Daily meeting brief for {day} failed: {clean(str(error), 400)}")
        raise
    brief_path.write_text(brief)
    if tasks is not None:
        (out / f"{day}-tasks.json").write_text(json.dumps(tasks))
    state.update(last_brief_until=now.isoformat(), last_brief=str(brief_path))
    (out / "brief-state.json").write_text(json.dumps(state, indent=1))
    result = {"brief": str(brief_path)}
    if not args.no_send:
        result["discord"] = send(root, brief_path, headline_for(brief, day))
    print(json.dumps(result))
    return 0


if __name__ == "__main__":
    sys.exit(main())
