#!/usr/bin/env python3
"""
scripts/issues.py

Workflow wrapper for OpenMates user-reported issues.
The issue database stays the source of truth; this script delegates privileged
decryption, timeline, and admin API access to backend/scripts/debug.py, then
adds operator workflow helpers: recent issue views, clustering, local-only
findings notes, and local note status/link updates.
"""

from __future__ import annotations

import argparse
import json
import re
import subprocess
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any


PROJECT_ROOT = Path(__file__).resolve().parents[1]
FINDINGS_ROOT = PROJECT_ROOT / "docs" / "findings" / "issues"
DEBUG_COMMAND = [
    "docker",
    "exec",
    "api",
    "python",
    "/app/backend/scripts/debug.py",
    "issue",
]

ENV_FLAGS = {
    "prod": "--production",
    "production": "--production",
    "dev": "--dev",
    "development": "--dev",
}

REDACTED_HASH = "#key=<redacted>"
UUID_RE = re.compile(
    r"[0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{12}"
)
SHORT_ISSUE_ID_RE = re.compile(r"^[A-HJ-NP-Z2-9]{5}$")
SHARE_RE = re.compile(r"/share/(chat|embed)/([0-9a-fA-F-]{36})")


class IssueCommandError(RuntimeError):
    """Raised when the delegated debug issue command fails."""

    def __init__(self, command: list[str], output: str, returncode: int):
        super().__init__(f"debug issue command failed ({returncode}): {' '.join(command)}")
        self.command = command
        self.output = output
        self.returncode = returncode


def normalize_env(value: str) -> str:
    env = value.lower().strip()
    if env in {"production", "prod"}:
        return "prod"
    if env in {"development", "dev"}:
        return "dev"
    if env == "both":
        return "both"
    raise ValueError(f"Unsupported env: {value}")


def env_flag(env: str) -> str:
    normalized = normalize_env(env)
    if normalized == "both":
        raise ValueError("env_flag cannot be used with env=both")
    return ENV_FLAGS[normalized]


def redact_url(value: str | None) -> str:
    if not value:
        return ""
    return re.sub(r"#key=[^\s)]+", REDACTED_HASH, value)


def issue_timestamp(issue: dict[str, Any]) -> datetime | None:
    raw = str(issue.get("created_at") or issue.get("timestamp") or "")
    if not raw:
        return None
    try:
        parsed = datetime.fromisoformat(raw.replace("Z", "+00:00"))
    except ValueError:
        return None
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(timezone.utc)


def title_slug(title: str, max_len: int = 56) -> str:
    slug = re.sub(r"[^a-zA-Z0-9]+", "-", title.lower()).strip("-")
    return (slug[:max_len].strip("-") or "reported-issue")


def short_id(issue_id: str) -> str:
    return issue_id[:8] if issue_id else "unknown"


def display_issue_id(issue: dict[str, Any]) -> str:
    short_issue_id = str(issue.get("short_issue_id") or "").strip().upper()
    if SHORT_ISSUE_ID_RE.fullmatch(short_issue_id):
        return short_issue_id
    return short_id(str(issue.get("id") or ""))


def extract_json_object(output: str) -> dict[str, Any]:
    """Extract the JSON object from debug.py output that may include log lines."""
    start = output.find("{")
    end = output.rfind("}")
    if start < 0 or end < start:
        raise ValueError("No JSON object found in command output")
    return json.loads(output[start : end + 1])


def run_debug(args: list[str], *, check: bool = True) -> str:
    command = [*DEBUG_COMMAND, *args]
    result = subprocess.run(
        command,
        cwd=PROJECT_ROOT,
        capture_output=True,
        text=True,
        timeout=180,
    )
    output = "\n".join(part for part in (result.stdout, result.stderr) if part)
    if check and result.returncode != 0:
        raise IssueCommandError(command, output, result.returncode)
    return output


def run_debug_json(args: list[str]) -> dict[str, Any]:
    return extract_json_object(run_debug([*args, "--json"]))


def fetch_issue_list(env: str, *, limit: int, search: str | None, include_processed: bool) -> dict[str, Any]:
    args = ["--list", "--list-limit", str(limit), env_flag(env)]
    if search:
        args.extend(["--search", search])
    if include_processed:
        args.append("--include-processed")
    return run_debug_json(args)


def fetch_issue_detail(env: str, issue_id: str, *, include_logs: bool = False) -> dict[str, Any]:
    args = [issue_id, env_flag(env)]
    if not include_logs:
        args.append("--no-logs")
    return run_debug_json(args)


def issues_from_response(response: dict[str, Any], env: str) -> list[dict[str, Any]]:
    source = str(response.get("source") or env)
    issues = []
    for issue in response.get("issues") or []:
        if isinstance(issue, dict):
            copied = dict(issue)
            copied["_env"] = normalize_env(source)
            issues.append(copied)
    return issues


def fetch_many(env: str, *, limit: int, search: str | None, include_processed: bool) -> list[dict[str, Any]]:
    normalized = normalize_env(env)
    envs = ["prod", "dev"] if normalized == "both" else [normalized]
    issues: list[dict[str, Any]] = []
    for current_env in envs:
        try:
            response = fetch_issue_list(
                current_env,
                limit=limit,
                search=search,
                include_processed=include_processed,
            )
            issues.extend(issues_from_response(response, current_env))
        except IssueCommandError as exc:
            print(f"[{current_env}] ERROR: {exc.output.strip()[:500]}", file=sys.stderr)
    return sorted(issues, key=lambda item: issue_timestamp(item) or datetime.min.replace(tzinfo=timezone.utc), reverse=True)


def filter_recent(issues: list[dict[str, Any]], hours: int) -> list[dict[str, Any]]:
    cutoff = datetime.now(timezone.utc) - timedelta(hours=hours)
    return [issue for issue in issues if (issue_timestamp(issue) or cutoff) >= cutoff]


def get_decrypted(issue: dict[str, Any]) -> dict[str, Any]:
    decrypted = issue.get("decrypted")
    return decrypted if isinstance(decrypted, dict) else {}


def normalize_issue_detail(response: dict[str, Any], env: str) -> dict[str, Any]:
    """Normalize debug.py detail JSON into the list-style issue shape."""
    metadata = response.get("issue_metadata") or response.get("issue") or response
    issue = dict(metadata) if isinstance(metadata, dict) else {}
    issue_id = response.get("issue_id") or issue.get("id")
    if issue_id:
        issue["id"] = issue_id
    short_issue_id = response.get("short_issue_id") or issue.get("short_issue_id")
    if short_issue_id:
        issue["short_issue_id"] = str(short_issue_id).upper()
    decrypted = response.get("decrypted_fields") or response.get("decrypted") or issue.get("decrypted") or {}
    if isinstance(decrypted, dict):
        issue["decrypted"] = decrypted
    issue["_env"] = normalize_env(env)
    return issue


def related_url(issue: dict[str, Any]) -> str:
    return str(get_decrypted(issue).get("chat_or_embed_url") or issue.get("chat_or_embed_url") or "")


def cluster_key(issue: dict[str, Any]) -> str:
    url = related_url(issue)
    match = SHARE_RE.search(url)
    if match:
        return f"{match.group(1)}:{match.group(2)}"
    title = str(issue.get("title") or "")
    words = re.findall(r"[a-zA-Z0-9]+", title.lower())
    useful = [word for word in words if len(word) > 2][:8]
    return "title:" + "-".join(useful or [short_id(str(issue.get("id") or "unknown"))])


def findings_path(issue: dict[str, Any], env: str | None = None) -> Path:
    issue_id = str(issue.get("id") or "unknown")
    title = str(issue.get("title") or "reported issue")
    created = issue_timestamp(issue) or datetime.now(timezone.utc)
    note_env = normalize_env(env or str(issue.get("_env") or "prod"))
    filename = f"{issue_id}-{title_slug(title)}.md"
    return FINDINGS_ROOT / note_env / str(created.year) / filename


def frontmatter_value(note: str, key: str) -> str | None:
    if not note.startswith("---\n"):
        return None
    end = note.find("\n---", 4)
    if end < 0:
        return None
    for line in note[4:end].splitlines():
        if line.startswith(f"{key}:"):
            return line.split(":", 1)[1].strip()
    return None


def set_frontmatter_value(note: str, key: str, value: str) -> str:
    if not note.startswith("---\n"):
        return f"---\n{key}: {value}\n---\n\n{note}"
    end = note.find("\n---", 4)
    if end < 0:
        return f"---\n{key}: {value}\n---\n\n{note}"
    header = note[4:end].splitlines()
    body = note[end:]
    replaced = False
    updated = []
    for line in header:
        if line.startswith(f"{key}:"):
            updated.append(f"{key}: {value}")
            replaced = True
        else:
            updated.append(line)
    if not replaced:
        updated.append(f"{key}: {value}")
    return "---\n" + "\n".join(updated) + body


def append_list_frontmatter_value(note: str, key: str, value: str) -> str:
    current = frontmatter_value(note, key)
    if not current or current == "[]":
        return set_frontmatter_value(note, key, f"[{value}]")
    if value in current:
        return note
    if current.startswith("[") and current.endswith("]"):
        inner = current[1:-1].strip()
        next_value = f"[{inner}, {value}]" if inner else f"[{value}]"
        return set_frontmatter_value(note, key, next_value)
    return set_frontmatter_value(note, key, f"[{current}, {value}]")


def format_note(issue: dict[str, Any], env: str) -> str:
    issue_id = str(issue.get("id") or "")
    short_issue_id = str(issue.get("short_issue_id") or "").upper()
    title = str(issue.get("title") or "")
    created = (issue_timestamp(issue) or datetime.now(timezone.utc)).strftime("%Y-%m-%dT%H:%M:%SZ")
    url = redact_url(related_url(issue))
    key = cluster_key(issue)
    linear = issue.get("linear_issue_identifier") or ""
    linear_items = f"[{linear}]" if linear else "[]"
    return f"""---
issue_id: {issue_id}
short_issue_id: {short_issue_id or 'null'}
env: {normalize_env(env)}
status: open
title: {json.dumps(title, ensure_ascii=False)}
reported_at: {created}
github: []
linear: {linear_items}
cluster_key: {key}
resolved_by: []
verified_by: []
---

# {title or short_issue_id or issue_id}

## Summary

## Symptoms

## First Anomaly

## Root Cause Hypothesis

## Related Reports

- Cluster key: `{key}`
- Related URL: `{url or 'none'}`

## Related Commits

## Attempts

## Tests Run

## Current Status

Open.

## Next Step

"""


def ensure_findings_note(issue: dict[str, Any], env: str) -> Path:
    path = findings_path(issue, env)
    if not path.exists():
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(format_note(issue, env), encoding="utf-8")
    return path


def print_issue_table(issues: list[dict[str, Any]]) -> None:
    if not issues:
        print("No issues found.")
        return
    for index, issue in enumerate(issues, start=1):
        created = issue_timestamp(issue)
        created_text = created.strftime("%Y-%m-%d %H:%M") if created else "unknown"
        display_id = display_issue_id(issue)
        title = str(issue.get("title") or "")
        env = str(issue.get("_env") or "?")
        linear = issue.get("linear_issue_identifier") or "-"
        processed = "processed" if issue.get("processed") else "open"
        print(f"{index:>3}. [{env}] {display_id}  {created_text}  {processed}  Linear:{linear}")
        print(f"     {title}")
        url = redact_url(related_url(issue))
        if url:
            print(f"     URL: {url}")


def command_list(args: argparse.Namespace) -> int:
    issues = fetch_many(
        args.env,
        limit=args.limit,
        search=args.search,
        include_processed=args.include_processed,
    )
    if args.json:
        print(json.dumps({"issues": issues}, indent=2, default=str))
    else:
        print_issue_table(issues)
    return 0


def command_recent(args: argparse.Namespace) -> int:
    issues = fetch_many(
        args.env,
        limit=args.limit,
        search=args.search,
        include_processed=args.include_processed,
    )
    recent = filter_recent(issues, args.hours)
    if args.json:
        print(json.dumps({"hours": args.hours, "issues": recent}, indent=2, default=str))
    else:
        print_issue_table(recent)
    return 0


def command_show(args: argparse.Namespace) -> int:
    response = fetch_issue_detail(args.env, args.issue_id, include_logs=args.full)
    if args.json:
        print(json.dumps(response, indent=2, default=str))
        return 0
    issue = normalize_issue_detail(response, args.env)
    decrypted = get_decrypted(issue)
    print(f"Issue: {display_issue_id(issue)}")
    if issue.get("id"):
        print(f"UUID: {issue.get('id')}")
    print(f"Env: {normalize_env(args.env)}")
    print(f"Title: {issue.get('title') or ''}")
    print(f"Reported: {issue.get('created_at') or issue.get('timestamp') or ''}")
    print(f"Processed: {issue.get('processed', 'unknown')}")
    print(f"Linear: {issue.get('linear_issue_identifier') or '-'}")
    url = redact_url(str(decrypted.get("chat_or_embed_url") or issue.get("chat_or_embed_url") or ""))
    print(f"Cluster: {cluster_key(issue)}")
    if url:
        print(f"URL: {url}")
    print(f"Findings: {findings_path(issue, args.env).relative_to(PROJECT_ROOT)}")
    return 0


def command_timeline(args: argparse.Namespace) -> int:
    command_args = [
        args.issue_id,
        env_flag(args.env),
        "--timeline",
        "--before",
        str(args.before),
        "--after",
        str(args.after),
    ]
    if args.compact:
        command_args.append("--compact")
    print(run_debug(command_args), end="")
    return 0


def command_cluster(args: argparse.Namespace) -> int:
    issues = fetch_many(
        args.env,
        limit=args.limit,
        search=args.search,
        include_processed=args.include_processed,
    )
    if args.hours:
        issues = filter_recent(issues, args.hours)
    clusters: dict[str, list[dict[str, Any]]] = {}
    for issue in issues:
        clusters.setdefault(cluster_key(issue), []).append(issue)
    shown = 0
    for key, group in sorted(clusters.items(), key=lambda item: (-len(item[1]), item[0])):
        if len(group) == 1 and not args.all:
            continue
        shown += 1
        print(f"{key} ({len(group)} issue{'s' if len(group) != 1 else ''})")
        for issue in group:
            created = issue_timestamp(issue)
            created_text = created.strftime("%Y-%m-%d %H:%M") if created else "unknown"
            print(f"  - [{issue.get('_env')}] {display_issue_id(issue)} {created_text}: {issue.get('title')}")
    if shown == 0:
        print("No multi-issue clusters found.")
    return 0


def command_findings(args: argparse.Namespace) -> int:
    response = fetch_issue_detail(args.env, args.issue_id, include_logs=False)
    issue = normalize_issue_detail(response, args.env)
    path = ensure_findings_note(issue, args.env)
    print(path.relative_to(PROJECT_ROOT))
    if args.print:
        print(path.read_text(encoding="utf-8"))
    return 0


def command_mark(args: argparse.Namespace) -> int:
    response = fetch_issue_detail(args.env, args.issue_id, include_logs=False)
    issue = normalize_issue_detail(response, args.env)
    path = ensure_findings_note(issue, args.env)
    note = path.read_text(encoding="utf-8")
    note = set_frontmatter_value(note, "status", args.status)
    path.write_text(note, encoding="utf-8")
    print(path.relative_to(PROJECT_ROOT))
    return 0


def command_link(args: argparse.Namespace) -> int:
    response = fetch_issue_detail(args.env, args.issue_id, include_logs=False)
    issue = normalize_issue_detail(response, args.env)
    path = ensure_findings_note(issue, args.env)
    note = path.read_text(encoding="utf-8")
    if args.github:
        note = append_list_frontmatter_value(note, "github", str(args.github))
    if args.linear:
        note = append_list_frontmatter_value(note, "linear", str(args.linear))
    path.write_text(note, encoding="utf-8")
    print(path.relative_to(PROJECT_ROOT))
    return 0


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Workflow CLI for OpenMates reported issues")
    subparsers = parser.add_subparsers(dest="command", required=True)

    def add_common_list(sub: argparse.ArgumentParser) -> None:
        sub.add_argument("--env", default="prod", choices=["prod", "production", "dev", "development", "both"])
        sub.add_argument("--limit", type=int, default=30)
        sub.add_argument("--search", default=None)
        sub.add_argument("--include-processed", action="store_true")
        sub.add_argument("--json", action="store_true")

    list_parser = subparsers.add_parser("list", help="List issue reports")
    add_common_list(list_parser)
    list_parser.set_defaults(func=command_list)

    recent_parser = subparsers.add_parser("recent", help="List recent issue reports")
    add_common_list(recent_parser)
    recent_parser.add_argument("--hours", type=int, default=24)
    recent_parser.set_defaults(func=command_recent)

    show_parser = subparsers.add_parser("show", help="Show one issue report")
    show_parser.add_argument("issue_id")
    show_parser.add_argument("--env", default="prod", choices=["prod", "production", "dev", "development"])
    show_parser.add_argument("--full", action="store_true", help="Include full S3 report when available")
    show_parser.add_argument("--json", action="store_true")
    show_parser.set_defaults(func=command_show)

    timeline_parser = subparsers.add_parser("timeline", help="Print debug.py issue timeline")
    timeline_parser.add_argument("issue_id")
    timeline_parser.add_argument("--env", default="prod", choices=["prod", "production", "dev", "development"])
    timeline_parser.add_argument("--before", type=int, default=10)
    timeline_parser.add_argument("--after", type=int, default=5)
    timeline_parser.add_argument("--compact", action="store_true")
    timeline_parser.set_defaults(func=command_timeline)

    cluster_parser = subparsers.add_parser("cluster", help="Group reports by share URL or title fingerprint")
    cluster_parser.add_argument("--env", default="prod", choices=["prod", "production", "dev", "development", "both"])
    cluster_parser.add_argument("--limit", type=int, default=100)
    cluster_parser.add_argument("--search", default=None)
    cluster_parser.add_argument("--include-processed", action="store_true")
    cluster_parser.add_argument("--hours", type=int, default=72)
    cluster_parser.add_argument("--all", action="store_true", help="Show single-issue clusters too")
    cluster_parser.set_defaults(func=command_cluster)

    findings_parser = subparsers.add_parser("findings", help="Create or print a durable findings note")
    findings_parser.add_argument("issue_id")
    findings_parser.add_argument("--env", default="prod", choices=["prod", "production", "dev", "development"])
    findings_parser.add_argument("--print", action="store_true", help="Print the note content after creating it")
    findings_parser.set_defaults(func=command_findings)

    mark_parser = subparsers.add_parser("mark", help="Set findings note status")
    mark_parser.add_argument("issue_id")
    mark_parser.add_argument("--env", default="prod", choices=["prod", "production", "dev", "development"])
    mark_parser.add_argument("--status", required=True)
    mark_parser.set_defaults(func=command_mark)

    link_parser = subparsers.add_parser("link", help="Add GitHub or Linear references to findings note")
    link_parser.add_argument("issue_id")
    link_parser.add_argument("--env", default="prod", choices=["prod", "production", "dev", "development"])
    link_parser.add_argument("--github")
    link_parser.add_argument("--linear")
    link_parser.set_defaults(func=command_link)

    return parser


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    try:
        return args.func(args)
    except IssueCommandError as exc:
        print(exc.output.strip() or str(exc), file=sys.stderr)
        return exc.returncode or 1
    except ValueError as exc:
        print(f"Error: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    sys.exit(main())
