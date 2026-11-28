"""The one Discord message of an AI test-user run (owner, 20 Nov 2026; layout 23 Nov 2026).

Two summary lines (issue counts per environment, debug chats started and issues waiting for Marco's
approval; then flow verdicts, harness problems and how many findings were dropped), then a DEV and a
PRODUCTION section. Each issue there shows its title on its own line, then the environment, whether a
debugging chat started (and which), is covered by an open Task or chat, or waits for approval
(`ai_test_users_triage.py`), its report id and a link into the session video (private bucket, deleted
after 7 days). Issues are the kept findings (bug or suspect) grouped by cause within one environment:

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
DEV_COLOR = 0x3B82F6
PROD_COLOR = 0xDC2626


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
    """Line-2 harness problems: at most MAX_PROBLEMS short texts without links (full list in report.md)."""
    if not problems:
        return ""
    short = [re.sub(r"\s*\[[^\]]*\]\(<?[^)>]*>?\)", "", p).strip() for p in problems[:MAX_PROBLEMS]]
    short = [p if len(p) <= PROBLEM_CHARS else p[:PROBLEM_CHARS].rstrip() + "…" for p in short]
    more = f" (+{len(problems) - MAX_PROBLEMS} more in report.md)" if len(problems) > MAX_PROBLEMS else ""
    return f"Harness problems: {'; '.join(short)}{more}."


def _embed_lines(lines: list[str]) -> list[dict]:
    """Issue lines into embeds: a `## ` line starts a titled section; long sections continue in more embeds."""
    sections: list[dict] = []
    for line in lines:
        if line.startswith("## "):
            sections.append({"title": line[3:], "lines": []})
        elif sections:
            sections[-1]["lines"].append(line)
        else:
            sections.append({"title": "", "lines": [line]})
    embeds: list[dict] = []
    used, dropped = 0, 0
    for section in sections:
        embed = {"title": section["title"], "description": ""}
        used += len(section["title"])
        for index, line in enumerate(section["lines"]):
            if used + len(line) + 61 > EMBED_TOTAL_LIMIT or len(embeds) >= MAX_EMBEDS:
                dropped += len(section["lines"]) - index
                break
            if len(embed["description"]) + len(line) + 1 > EMBED_LIMIT:
                embeds.append(embed)
                embed = {"title": "", "description": ""}
            embed["description"] = f"{embed['description']}\n{line}" if embed["description"] else line
            used += len(line) + 1
        if embed["title"] or embed["description"]:
            embeds.append(embed)
    embeds = embeds[:MAX_EMBEDS]
    if dropped and embeds:
        note = f"(+{dropped} more lines in report.md)"
        last = embeds[-1]
        last["description"] = f"{last['description']}\n{note}" if len(last["description"]) + len(note) < EMBED_LIMIT \
            else last["description"]
    for embed in embeds:
        if not embed["title"]:
            del embed["title"]
        embed["description"] = embed["description"] or "none"
        if embed.get("title", "").startswith("DEV"):
            embed["color"] = DEV_COLOR
        elif embed.get("title", "").startswith("PRODUCTION"):
            embed["color"] = PROD_COLOR
    return embeds


def discord_payload(text: str) -> dict:
    """One Discord message: the two summary lines as content, the DEV and PRODUCTION sections as embeds.

    Signed video links are ~400 characters, so the issue lines do not fit the 2000-character content
    limit; embeds add up to 6000 characters (4096 per embed, 10 embeds) and render markdown links."""
    lines = text.splitlines()
    content = "\n".join(lines[:2])[:CONTENT_LIMIT]
    rest = [re.sub(r"\]\(<([^>\s]+)>\)", r"](\1)", line) for line in lines[2:]]  # embeds never unfurl
    payload: dict = {"content": content}
    embeds = _embed_lines(rest)
    if embeds:
        payload["embeds"] = embeds
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


ENV_NAMES = {"dev": "DEV", "prod": "PRODUCTION"}


def debug_status(debug: dict) -> str:
    """What happened about a debugging chat for one issue, in plain words for Marco."""
    status, chat = debug.get("status"), debug.get("chat_title", "")
    return {
        "started": f"debug chat started: {chat}",
        "queued": f"debug chat queued, starts when a slot frees: {chat}",
        "would_start": "debug chat would start (dry run, not started)",
        "covered": f"no new chat, already covered by {debug.get('covered_by')}",
        "deferred": f"no debug chat yet: {debug.get('note', 'daily cap reached')}",
        "no_report": "no debug chat: no report was filed",
        "failed": f"debug chat failed to start ({debug.get('note', 'unknown error')})",
        "approval": f"waiting for your approval, {debug.get('why')}",
        "deploy_time": "no debug chat: filed during a production update (deploy-time, retest before acting)",
    }.get(status, str(status))


def issue_lines(issue: dict) -> list[str]:
    """Two lines per issue: the title alone, then environment, debug-chat status, report and video."""
    group = issue["group"]
    lead = group["members"][0]
    count = f" · {len(group['members'])}× ({', '.join(dict.fromkeys(m['result'].get('persona') for m in group['members']))})" \
        if len(group["members"]) > 1 else ""
    report = f" · report {issue['short_issue_id']}" if issue.get("short_issue_id") else ""
    link = reporting.video_link(lead["result"], lead["finding"].get("video_seconds"))
    title = re.sub(r"\s+", " ", issue["title"]).strip()[:150]
    return [f"**{title}**",
            f"{ENV_NAMES[issue['env']]} · {debug_status(issue['debug'])}{report}{count}" + (f" · {link}" if link else "")]


def run_message(title: str, results: list[dict], problems: list[str], flows: dict | None = None,
                issues: list[dict] | None = None) -> str:
    """The run's single push: two summary lines, then a DEV and a PRODUCTION section with one entry per issue.

    `issues` comes from `ai_test_users_triage.triage` (with the debug-chat outcome); without it the routes
    are computed here and nothing is started."""
    import ai_test_users_triage as triage

    if issues is None:
        issues = triage.triage(results, None, dispatch=False)
    ran = [r for r in results if r.get("status") not in ("skipped", "prod_disabled", "no_gift_card")]
    per_env = {env: [i for i in issues if i["env"] == env] for env in ENV_NAMES}
    statuses = [i["debug"]["status"] for i in issues]
    chats = sum(1 for s in statuses if s in ("started", "queued"))
    waiting = statuses.count("approval")
    covered = statuses.count("covered")
    dropped = sum(1 for r in results for f in r.get("findings") or [] if verdict(f) == "not a bug")
    broken = [f for f, v in (flows or {}).items() if v.get("verdict") != "working"]
    icon = "❌" if issues or problems or broken else "✅"
    first = (f"{icon} {title}: {len(ran)} personas ran, {len(per_env['dev'])} DEV and {len(per_env['prod'])} "
             f"PRODUCTION issues; {chats} debug chat{'s' if chats != 1 else ''} started, "
             + (f"{covered} already covered by an open Task or chat, " if covered else "")
             + f"{waiting} waiting for your approval.")
    parts = []
    if flows:
        parts.append("Flows: " + ", ".join(f"{f.split('_', 1)[0]} {v['verdict']} {v['passed']}/{v['runs']}"
                                           for f, v in sorted(flows.items())) + ".")
    if problems:
        parts.append(problem_text(problems))
    parts.append(f"{dropped} finding{'s' if dropped != 1 else ''} dropped as not a bug (report.md).")
    lines = [first, " ".join(parts)]
    if problems and not issues:
        return "\n".join(lines)
    for env, name in ENV_NAMES.items():
        lines.append(f"## {name} issues ({len(per_env[env])})")
        for index, issue in enumerate(per_env[env][:MAX_CAUSES]):
            lines += ([""] if index else []) + issue_lines(issue)
        if len(per_env[env]) > MAX_CAUSES:
            lines.append(f"(+{len(per_env[env]) - MAX_CAUSES} more issues in report.md)")
    return "\n".join(lines)
