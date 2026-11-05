#!/usr/bin/env python3
"""Open GitHub issues and Linear issues for the daily meeting briefing.

GitHub: `gh issue list` (the dev server's authenticated gh). Linear: the GraphQL API
with LINEAR_API_KEY from the environment; without a key Linear is reported as a gap
instead of failing the briefing. Both return compact rows, newest activity first.
Docs: docs/contributing/guides/daily-meeting.md
"""

from __future__ import annotations

from datetime import date, timedelta
import json
import os
import subprocess
import urllib.error
import urllib.request

LIMIT = 200
LINEAR_URL = "https://api.linear.app/graphql"
LINEAR_QUERY = """query($first: Int!) { issues(first: $first, orderBy: updatedAt,
  filter: {state: {type: {nin: ["completed", "canceled"]}}}) { nodes {
  identifier title url priority priorityLabel updatedAt state { name type }
  assignee { name } labels { nodes { name } } } } }"""


def github_issues(gaps: list[str]) -> list[dict] | None:
    try:
        run = subprocess.run(
            ["gh", "issue", "list", "--state", "open", "--limit", str(LIMIT), "--json",
             "number,title,labels,assignees,updatedAt,url"],
            capture_output=True, text=True, timeout=60, check=True)
        rows = json.loads(run.stdout)
    except (OSError, subprocess.SubprocessError, ValueError) as error:
        gaps.append(f"GitHub issues unavailable ({type(error).__name__})")
        return None
    return [{"id": f"#{r['number']}", "title": r["title"][:160], "url": r["url"],
             "labels": [label["name"] for label in r.get("labels", [])],
             "assignees": [a["login"] for a in r.get("assignees", [])],
             "updated": r["updatedAt"][:10]} for r in rows]


def linear_issues(gaps: list[str], api_key: str | None = None) -> list[dict] | None:
    key = api_key or os.environ.get("LINEAR_API_KEY", "")
    if not key:
        gaps.append("Linear issues unavailable (set LINEAR_API_KEY on the dev server)")
        return None
    request = urllib.request.Request(
        LINEAR_URL, data=json.dumps({"query": LINEAR_QUERY, "variables": {"first": LIMIT}}).encode(),
        headers={"Content-Type": "application/json", "Authorization": key})
    try:
        with urllib.request.urlopen(request, timeout=30) as response:
            data = json.load(response)
    except (OSError, urllib.error.URLError, ValueError) as error:
        gaps.append(f"Linear issues unavailable ({type(error).__name__})")
        return None
    if data.get("errors"):
        gaps.append(f"Linear issues unavailable ({data['errors'][0].get('message', 'API error')[:80]})")
        return None
    return [{"id": n["identifier"], "title": n["title"][:160], "url": n["url"],
             "state": n["state"]["name"], "state_type": n["state"]["type"],
             "priority": n.get("priorityLabel") or "", "assignee": (n.get("assignee") or {}).get("name", ""),
             "labels": [label["name"] for label in n["labels"]["nodes"]],
             "updated": n["updatedAt"][:10]} for n in data["data"]["issues"]["nodes"]]


BATCH = 10
REVIEW_PAUSE_DAYS = 30


def _task_number(task: dict) -> int:
    digits = "".join(ch for ch in str(task.get("id") or "") if ch.isdigit())
    return int(digits) if digits else 10**9


def cleanup_candidates(tasks: list[dict] | None, github: list[dict] | None, linear: list[dict] | None,
                       reviewed: dict[str, str], today: date, batch: int = BATCH) -> dict:
    """Oldest open items per tracker for the backlog cleanup part of the meeting.

    Items the user kept in a recent meeting (`reviewed`: id -> ISO date) are skipped for
    REVIEW_PAUSE_DAYS so the same keepers do not return every day. Tasks have no
    timestamps, so the lowest Task numbers (created first) count as oldest.
    """
    cutoff = (today - timedelta(days=REVIEW_PAUSE_DAYS)).isoformat()

    def fresh(item: dict) -> bool:
        return reviewed.get(str(item["id"]), "") < cutoff

    open_tasks = [t for t in (tasks or []) if t.get("status") in {"todo", "backlog", "blocked"}]
    return {
        "tasks": {"total": len(open_tasks),
                  "batch": sorted(filter(fresh, open_tasks), key=_task_number)[:batch]},
        "github": {"total": len(github or []),
                   "batch": sorted(filter(fresh, github or []), key=lambda i: i["updated"])[:batch]},
        "linear": {"total": len(linear or []),
                   "batch": sorted(filter(fresh, linear or []), key=lambda i: i["updated"])[:batch]},
    }


def load_reviewed(path) -> dict[str, str]:
    try:
        data = json.loads(path.read_text())
    except (OSError, ValueError):
        return {}
    return {str(k): str(v) for k, v in data.items()} if isinstance(data, dict) else {}
