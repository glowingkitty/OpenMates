"""The one Discord message of an AI test-user run (owner, 20 Nov 2026).

Two summary lines (counts, then run problems or flow verdicts), then one line per finding grouped by
cause, each with its verdict and a link into the session video (private bucket, deleted after 7 days):

  bug         Jev kept the finding.
  not a bug   Jev dropped it.
  suspect     The environment, not the app, may explain it: on dev a deploy landed or the api restarted
              between the persona's start and the finding, or the test account was deleted while the
              persona still used it (another process's deletion; the persona's own deletion comes last).

Production deploys and restarts are not visible from the dev host, so production findings are only
marked suspect for deletions.
"""

from __future__ import annotations

import re
import subprocess
from datetime import UTC, datetime
from pathlib import Path

import ai_test_users_accounts as accounts
import ai_test_users_report as reporting

ROOT = Path(__file__).resolve().parents[1]
STOPWORDS = set("the and for with that this when from into are not but has have was its on in of to a an is it "
                "shows shown show page app chat".split())
SAME_CAUSE = 0.45  # title similarity at which two findings count as one cause (as the `tasks` merge)
DEPLOY_SLACK_SECONDS = 30  # a restart this soon after a finding may still be its cause
RESTART_CONTAINERS = ("api", "app-ai-worker", "task-worker")
PRODUCT_PATHS = ("frontend", "backend", "packages")  # deploys of tooling or docs never touch the running app
DELETION_STATUSES = ("deleted", "delete_failed")
MAX_CAUSES = 15
MAX_PROBLEMS = 3
PROBLEM_CHARS = 90
CONTENT_LIMIT = 2000  # Discord message content
EMBED_LIMIT = 4096  # Discord embed description
EMBED_TOTAL_LIMIT = 5800  # Discord: 6000 characters across all embeds of a message, kept with a margin
MAX_EMBEDS = 10
VERDICT_ORDER = {"bug": 0, "suspect": 1, "not a bug": 2}


def tokens(text: str) -> set[str]:
    return {w for w in re.findall(r"[a-zäöüß0-9]{3,}", text.lower()) if w not in STOPWORDS}


def similar(a: str, b: str) -> float:
    ta, tb = tokens(a), tokens(b)
    return len(ta & tb) / len(ta | tb) if ta and tb else 0.0


def _epoch(iso: str) -> float | None:
    """Docker/registry ISO time (Docker adds nanoseconds) to epoch seconds."""
    match = re.match(r"(\d{4}-\d\d-\d\dT\d\d:\d\d:\d\d)(\.\d+)?(Z|[+-]\d\d:\d\d)?", iso.strip())
    if not match:
        return None
    zone = match.group(3) or "+00:00"
    return datetime.fromisoformat(match.group(1) + ("+00:00" if zone == "Z" else zone)).timestamp()


def _clock(epoch: float) -> str:
    return datetime.fromtimestamp(epoch, UTC).strftime("%H:%M UTC")


def dev_events(start: float, end: float) -> list[dict]:
    """Dev deploys that changed product code (commits on origin/dev) and container restarts in the window."""
    events = []
    log = subprocess.run(["git", "-C", str(ROOT), "log", "origin/dev", f"--since=@{int(start)}",
                          f"--until=@{int(end) + 1}", "--format=%ct %h", "--", *PRODUCT_PATHS],
                         capture_output=True, text=True, timeout=30, check=False)
    for line in log.stdout.splitlines():
        stamp, _, sha = line.partition(" ")
        if stamp.isdigit() and start <= int(stamp) <= end:
            events.append({"at": float(stamp), "what": f"dev deploy {sha} at {_clock(float(stamp))}"})
    for container in RESTART_CONTAINERS:
        shown = subprocess.run(["docker", "inspect", "-f", "{{.State.StartedAt}}", container],
                               capture_output=True, text=True, timeout=30, check=False)
        at = _epoch(shown.stdout) if shown.returncode == 0 else None
        if at is not None and start <= at <= end:
            events.append({"at": at, "what": f"{container} restarted at {_clock(at)}"})
    return events


def deletion_events(email: str, start: float, end: float, base: Path | None = None) -> list[dict]:
    """Deletion lines in the account registry while the persona's worker ran (written by another process)."""
    out = []
    for entry in accounts.registry_entries(base):
        if entry.get("email") != email or entry.get("status") not in DELETION_STATUSES:
            continue
        at = _epoch(str(entry.get("created_at", "")))
        if at is not None and start <= at <= end:
            out.append({"at": at, "what": f"test account deleted at {_clock(at)} during the run"})
    return out


def mark_suspects(results: list[dict], events=dev_events, base: Path | None = None) -> None:
    """Set `suspect` (reason text) on findings the environment may explain; see the module docstring."""
    for r in results:
        start, end = r.get("started_at"), r.get("finished_at")
        if not isinstance(start, (int, float)) or not isinstance(end, (int, float)):
            continue
        env = events(start, end) if r.get("target") == "dev" else []
        deleted = deletion_events(r["email"], start, end, base) if r.get("email") else []
        for finding in r.get("findings") or []:
            moment = finding.get("at_epoch") if isinstance(finding.get("at_epoch"), (int, float)) else end
            reasons = [e["what"] for e in env if e["at"] <= moment + DEPLOY_SLACK_SECONDS]
            reasons += [e["what"] for e in deleted]
            if reasons:
                finding["suspect"] = "; ".join(dict.fromkeys(reasons))


def verdict(finding: dict) -> str:
    if finding.get("suspect"):
        return "suspect"
    return "bug" if finding.get("kept") else "not a bug"


def causes(results: list[dict]) -> list[dict]:
    """Findings of the run grouped by cause (similar titles), most severe verdict first."""
    groups: list[dict] = []
    for r in results:
        report_of = {i: rep.get("short_issue_id") for rep in r.get("reports") or [] if rep.get("short_issue_id")
                     for i in rep.get("finding_ids") or []}
        for index, finding in enumerate(r.get("findings") or []):
            member = {"result": r, "finding": finding, "report": report_of.get(index)}
            title = str(finding.get("title") or "")
            group = next((g for g in groups if similar(title, g["title"]) >= SAME_CAUSE), None)
            if group is None:
                groups.append({"title": title, "members": [member]})
            else:
                group["members"].append(member)
    for group in groups:
        verdicts = [verdict(m["finding"]) for m in group["members"]]
        group["verdict"] = min(verdicts, key=VERDICT_ORDER.__getitem__)
        group["suspect"] = "; ".join(dict.fromkeys(
            m["finding"]["suspect"] for m in group["members"] if m["finding"].get("suspect")))
    return sorted(groups, key=lambda g: (VERDICT_ORDER[g["verdict"]], -len(g["members"])))


def cause_line(group: dict) -> str:
    lead = group["members"][0]
    who = ", ".join(dict.fromkeys(f"{m['result'].get('target')}/{m['result'].get('persona')}"
                                  for m in group["members"]))
    count = f"{len(group['members'])}× " if len(group["members"]) > 1 else ""
    label = f"suspect ({group['suspect']})" if group["verdict"] == "suspect" else group["verdict"]
    reports = " ".join(m["report"] for m in group["members"] if m["report"])
    link = reporting.video_link(lead["result"], lead["finding"].get("video_seconds")) or "no video"
    return f"• {label}: {group['title'][:110]} ({count}{who}) {link}" + (f" {reports}" if reports else "")


def problem_text(problems: list[str]) -> str:
    """Line-2 problems: at most MAX_PROBLEMS short texts without links (full list in report.md)."""
    if not problems:
        return "No run problems."
    short = [re.sub(r"\s*\[[^\]]*\]\(<?[^)>]*>?\)", "", p).strip() for p in problems[:MAX_PROBLEMS]]
    short = [p if len(p) <= PROBLEM_CHARS else p[:PROBLEM_CHARS].rstrip() + "…" for p in short]
    more = f" (+{len(problems) - MAX_PROBLEMS} more in report.md)" if len(problems) > MAX_PROBLEMS else ""
    return f"Problems: {'; '.join(short)}{more}."


def discord_payload(text: str) -> dict:
    """One Discord message: the two summary lines as content, the cause lines in embeds.

    Signed video links are ~400 characters, so the cause lines do not fit the 2000-character content
    limit; embeds add up to 6000 characters (4096 per embed, 10 embeds) and render markdown links."""
    lines = text.splitlines()
    content = "\n".join(lines[:2])[:CONTENT_LIMIT]
    causes_lines = [re.sub(r"\]\(<([^>\s]+)>\)", r"](\1)", line) for line in lines[2:]]  # embeds never unfurl
    descriptions: list[str] = []
    used, dropped = 0, 0
    for index, line in enumerate(causes_lines):
        left = len(causes_lines) - index - 1
        reserve = 60 if left else 0  # room for the "+N more" line
        if used + len(line) + 1 + reserve > EMBED_TOTAL_LIMIT or (
                len(descriptions) == MAX_EMBEDS and len(descriptions[-1]) + len(line) + 1 > EMBED_LIMIT):
            dropped = len(causes_lines) - index
            break
        if descriptions and len(descriptions[-1]) + len(line) + 1 <= EMBED_LIMIT:
            descriptions[-1] += "\n" + line
        else:
            descriptions.append(line)
        used += len(line) + 1
    if dropped:
        note = f"(+{dropped} more causes in report.md)"
        if descriptions and len(descriptions[-1]) + len(note) + 1 <= EMBED_LIMIT:
            descriptions[-1] += "\n" + note
        else:
            descriptions.append(note)
    payload: dict = {"content": content}
    if descriptions:
        payload["embeds"] = [{"description": d} for d in descriptions]
    return payload


def push(text: str, title: str = "AI test users", post=None, sleep=None) -> None:
    """Send the run message as one Discord message (content + embeds) and log it like other pushes."""
    import time

    import agent_question
    import discord_webhook
    from pending_work_gate import canonical_root

    root = canonical_root()
    post = post or discord_webhook.post_message
    payload, url = discord_payload(text), agent_question.webhook(root)
    for delay in (*agent_question.RETRY_DELAYS, None):
        if post(webhook_url=url, payload=payload):
            break
        if delay is not None:
            (sleep or time.sleep)(delay)
    else:
        raise agent_question.QuestionError("Discord delivery of the AI test-user run message was not confirmed")
    agent_question.record_push(root, text, time.time(), title=title, source=accounts.PUSH_SOURCE)


def run_message(title: str, results: list[dict], problems: list[str], flows: dict | None = None) -> str:
    """The run's single push: two summary lines, then one line per cause."""
    ran = [r for r in results if r.get("status") not in ("skipped", "prod_disabled", "no_gift_card")]
    groups = causes(results)
    count = {v: sum(1 for g in groups if g["verdict"] == v) for v in VERDICT_ORDER}
    findings = sum(len(g["members"]) for g in groups)
    filed = sum(1 for r in results for rep in r.get("reports") or [] if rep.get("short_issue_id"))
    broken = [f for f, v in (flows or {}).items() if v.get("verdict") != "working"]
    icon = "❌" if problems or broken else "✅"
    first = (f"{icon} {title}: {len(ran)} personas ran, {findings} findings in {len(groups)} causes "
             f"({count['bug']} bug, {count['suspect']} suspect, {count['not a bug']} not a bug), {filed} reports filed.")
    parts = []
    if flows:
        parts.append("Flows: " + ", ".join(f"{f.split('_', 1)[0]} {v['verdict']} {v['passed']}/{v['runs']}"
                                           for f, v in sorted(flows.items())) + ".")
    parts.append(problem_text(problems))
    lines = [first, " ".join(parts)] + [cause_line(g) for g in groups[:MAX_CAUSES]]
    if len(groups) > MAX_CAUSES:
        lines.append(f"(+{len(groups) - MAX_CAUSES} more causes in report.md)")
    return "\n".join(lines)
