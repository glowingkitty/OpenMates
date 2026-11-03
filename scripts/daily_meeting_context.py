#!/usr/bin/env python3
"""Collect the evidence the daily meeting (a Claude Code chat on the dev server) starts from.

Run by the `daily-meeting-and-orchestration` skill at the start of each meeting:
  python3 scripts/daily_meeting_context.py collect
writes logs/daily-meetings/YYYY-MM-DD-context.json (gitignored, private) with
Claude chats since the previous meeting, git activity incl. the marketing repo,
the work-type mix, OpenMates Tasks changes, nightly test status, and the Apple
Reminders overview (via scripts/mac_reminders.py). Task records carry no
timestamps, so "changed since the last meeting" diffs a saved status snapshot.
Docs: docs/contributing/guides/daily-meeting.md
"""

from __future__ import annotations

import argparse
from collections import Counter
from datetime import datetime, timedelta, timezone
import json
from pathlib import Path
import re
import subprocess
import sys
import urllib.request
from zoneinfo import ZoneInfo

ROOT = Path(__file__).resolve().parents[1]
TZ = ZoneInfo("Europe/Berlin")
PROJECT_ID = "96033196-e4b1-431e-b773-ba221e952fed"
TRANSCRIPTS = Path.home() / ".claude" / "projects"
MARKETING_REPO = next((p / "openmates-marketing" for p in ROOT.parents
                       if (p / "openmates-marketing" / ".git").exists()), ROOT.parent / "openmates-marketing")
MEETING_HOUR = 10
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


def meeting_dir(root: Path) -> Path:
    path = root / "logs" / "daily-meetings"
    path.mkdir(parents=True, exist_ok=True)
    return path


def load_state(out: Path) -> dict:
    try:
        return json.loads((out / "context-state.json").read_text())
    except (OSError, ValueError):
        return {}


def window_start(state: dict, now: datetime) -> datetime:
    """End of the latest collection on an earlier day, else the previous weekday's meeting."""
    today = now.astimezone(TZ).date().isoformat()
    earlier = [until for day, until in state.get("collected", {}).items() if day < today]
    return parse_ts(max(earlier)) if earlier else default_since(now)


def default_since(now: datetime) -> datetime:
    """Previous weekday's meeting time in Berlin (Monday reaches back to Friday)."""
    local = now.astimezone(TZ)
    day = local.date() - timedelta(days=1)
    while day.weekday() >= 5:
        day -= timedelta(days=1)
    return datetime(day.year, day.month, day.day, MEETING_HOUR, 0, tzinfo=TZ)


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
                prompts.append(clean(body, 600))
        elif kind == "assistant":
            replies.append("\n".join(texts))
    if not prompts or (len(prompts) == 1 and len(prompts[0]) < 25):
        return None  # empty or trivial chats ("login", "hi") are noise
    return {
        "session": path.stem,
        "title": clean(title, 120),
        "started": first.astimezone(TZ).strftime("%a %H:%M"),
        "last_activity": last.astimezone(TZ).strftime("%a %H:%M"),
        "branch": branch,
        "user_prompts": prompts[:6] + ([f"(+{len(prompts) - 6} more prompts)"] if len(prompts) > 6 else []),
        "final_reply": clean(replies[-1], 1500) if replies else "",
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
        "chat": _chat_ref(t.get("external_chat")),
    } for t in data.get("tasks", [])]


def _chat_ref(chat: dict | None) -> str:
    return f"{chat.get('provider')}:{chat.get('id')}" if isinstance(chat, dict) and chat.get("id") else ""


def chat_state(task: dict, active_chats: set[str]) -> str:
    """Whether an in-progress Task has a Claude chat that was active in the meeting window."""
    provider, _, chat_id = task.get("chat", "").partition(":")
    if not chat_id:
        return "no_chat"
    if provider != "claude":
        return f"{provider}_legacy"  # Codex is retired; such Tasks need a Claude owner or a decision
    return "active" if chat_id in active_chats else "idle"


PRIORITY_ORDER = {"urgent": 0, "high": 1, "medium": 2, "low": 3}


def _by_priority(tasks: list[dict]) -> list[dict]:
    return sorted(tasks, key=lambda t: (PRIORITY_ORDER.get(t.get("priority"), 4), str(t.get("due") or "9999")))


def _compact(task: dict) -> dict:
    return {key: value for key, value in task.items() if value and value != "none" and key != "status"}


def task_summary(tasks: list[dict] | None, previous: list[dict] | None,
                 active_chats: set[str] | None = None) -> dict:
    """OpenMates Tasks are the agents' work queue (Reminders are the user's capture inbox)."""
    if tasks is None:
        return {}
    active_chats = active_chats or set()
    tasks = [t | {"chat_state": chat_state(t, active_chats)} if t["status"] == "in_progress" else t
             for t in tasks]
    by_status: dict[str, list] = {}
    for task in tasks:
        by_status.setdefault(task["status"], []).append(task)
    old = {t["id"]: t["status"] for t in previous or []}
    changes = [{"id": t["id"], "title": t["title"], "from": old.get(t["id"], "new"), "to": t["status"]}
               for t in tasks if old.get(t["id"]) != t["status"]] if previous else []
    done_now = [c for c in changes if c["to"] == "done"]
    return {
        "counts": {k: len(v) for k, v in by_status.items()},
        "done_since_last_meeting": done_now,
        "in_progress_by_chat_state": dict(Counter(t["chat_state"] for t in by_status.get("in_progress", []))),
        "open": {
            "in_progress": [_compact(t) for t in by_status.get("in_progress", [])],
            "blocked": [_compact(t) for t in by_status.get("blocked", [])],
            "todo_top": [_compact(t) for t in _by_priority(by_status.get("todo", []))[:40]],
            "backlog_top": [_compact(t) for t in _by_priority(by_status.get("backlog", []))[:15]],
            "more": "full lists: openmates tasks list --project " + PROJECT_ID + " --json",
        },
        "changed_since_last_meeting": [c for c in changes if c["to"] != "done"],
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


WORK_TYPES = {"feat": "feature", "fix": "debugging/fixes", "test": "tests/CI", "ci": "tests/CI",
              "docs": "docs", "refactor": "refactor", "perf": "performance", "chore": "chore"}


def work_mix(root: Path, days: int = 10) -> dict:
    """Commit types on dev over recent days, to spot feature/debugging drift."""
    log = git(root, "log", "origin/dev", f"--since={days}.days", "--no-merges", "--format=%s")
    mix = Counter(WORK_TYPES.get(re.split(r"[(:!]", line, 1)[0].strip().lower(), "other")
                  for line in log.splitlines() if line.strip())
    return {"window_days": days, "commits_by_type": dict(mix.most_common())}


def marketing(since: datetime, repo: Path = MARKETING_REPO) -> dict:
    if not (repo / ".git").exists():
        return {"available": False}
    def count(spec: str) -> int:
        return len(git(repo, "log", "--all", f"--since={spec}", "--format=%h").splitlines())
    recent = git(repo, "log", "--all", f"--since={since.isoformat()}", "--format=%cs %s")
    last = git(repo, "log", "--all", "-1", "--format=%cs %s")
    return {"available": True, "commits_since_last_meeting": [clean(x, 140) for x in recent.splitlines()[:20]],
            "commits_last_7_days": count("7.days"), "commits_last_30_days": count("30.days"),
            "last_commit": clean(last, 160)}


def reminders(gaps: list[str]) -> dict | None:
    """Live from the Mac when it is online, else the copy synced every 30 minutes."""
    sys.path.insert(0, str(Path(__file__).resolve().parent))
    import mac_reminders  # noqa: E402 - sibling script, path set just above

    try:
        items, source, fetched_at = mac_reminders.load()
    except (mac_reminders.RemindersError, ValueError, OSError) as error:
        gaps.append(f"Apple Reminders unavailable: {clean(str(error), 300)}")
        return None
    if source == "cache":
        gaps.append(f"Mac offline: reminders are the copy synced at {fetched_at[:16]} UTC")
    return mac_reminders.overview(items, datetime.now(TZ).date()) | {
        "source": source, "fetched_at": fetched_at}


def claude_usage(gaps: list[str]) -> dict | None:
    """Subscription usage as Claude Code's /usage shows it (account endpoint, read-only).

    The endpoint is not a documented public API; a failure is reported as a gap.
    """
    try:
        token = json.loads((Path.home() / ".claude/.credentials.json").read_text())["claudeAiOauth"]["accessToken"]
        request = urllib.request.Request("https://api.anthropic.com/api/oauth/usage", headers={
            "Authorization": f"Bearer {token}", "anthropic-beta": "oauth-2025-04-20"})
        data = json.loads(urllib.request.urlopen(request, timeout=30).read())
    except (OSError, KeyError, ValueError) as error:
        gaps.append(f"Claude subscription usage unavailable ({type(error).__name__})")
        return None

    def window(key: str) -> dict | None:
        value = data.get(key) or {}
        if value.get("utilization") is None:
            return None
        resets = parse_ts(value.get("resets_at"))
        return {"used_percent": value["utilization"],
                "resets": resets.astimezone(TZ).strftime("%a %d %b %H:%M") if resets else ""}

    return {"weekly": window("seven_day"), "five_hour": window("five_hour")}


def focus(root: Path) -> str:
    path = root / "FOCUS.md"
    return path.read_text()[:12000] if path.exists() else ""


def previous_meeting(root: Path, today: str) -> dict | None:
    """Most recent earlier meeting record written by daily_meeting.py --record."""
    for path in sorted((root / "logs/daily-meetings").glob("????-??-??.json"), reverse=True):
        if path.stem < today:
            meetings = json.loads(path.read_text()).get("meetings", {})
            return {"date": path.stem, "meetings": [
                {key: clean(str(m.get(key, "")), 3000) for key in ("priorities", "proposal", "approval")}
                | {"answers": [clean(a.get("text", ""), 600) for a in m.get("answers", [])]}
                for m in meetings.values()]}
    return None


def collect(root: Path, now: datetime, since: datetime, out: Path) -> tuple[dict, list | None]:
    gaps: list[str] = []
    today = now.astimezone(TZ).date().isoformat()
    tasks = task_snapshot(gaps)
    snapshots = sorted(p for p in out.glob("*-tasks.json") if p.name[:10] < today)
    previous = json.loads(snapshots[-1].read_text()) if snapshots else None
    chats = claude_chats(since)
    if not chats:
        gaps.append("no Claude Code chats found on the dev server for this window")
    evidence = {
        "meeting_date": now.astimezone(TZ).strftime("%A %Y-%m-%d"),
        "window": {"since": since.astimezone(TZ).isoformat(timespec="minutes"),
                   "until": now.astimezone(TZ).isoformat(timespec="minutes")},
        "focus_file": focus(root),
        "claude_usage": claude_usage(gaps),
        "previous_meeting": previous_meeting(root, today),
        "claude_chats": chats,
        "git": git_summary(root, since, gaps),
        "work_mix": work_mix(root),
        "marketing": marketing(since),
        "tasks": task_summary(tasks, previous, {c["session"] for c in chats}),
        "nightly": nightly(root, since),
        "reminders": reminders(gaps),
        "gaps": gaps,
    }
    return evidence, tasks


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("command", choices=("collect",))
    parser.add_argument("--root", type=Path, help="default: the canonical checkout (also from a worktree)")
    parser.add_argument("--out-dir", type=Path)
    parser.add_argument("--since", help="ISO timestamp; default: end of the previous meeting's collection")
    args = parser.parse_args(argv)

    if args.root:
        root = args.root.resolve()
    else:
        sys.path.insert(0, str(Path(__file__).resolve().parent))
        from agent_state import canonical_root  # noqa: E402 - sibling script, path set just above

        root = canonical_root(ROOT)
    out = args.out_dir.resolve() if args.out_dir else meeting_dir(root)
    out.mkdir(parents=True, exist_ok=True)
    now = datetime.now(timezone.utc)
    day = now.astimezone(TZ).date().isoformat()
    state = load_state(out)
    since = parse_ts(args.since) or window_start(state, now)
    evidence, tasks = collect(root, now, since, out)
    path = out / f"{day}-context.json"
    path.write_text(json.dumps(evidence, indent=1, ensure_ascii=False))
    if tasks is not None:
        (out / f"{day}-tasks.json").write_text(json.dumps(tasks))
    state.setdefault("collected", {})[day] = now.isoformat()
    (out / "context-state.json").write_text(json.dumps(state, indent=1))
    print(path)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
