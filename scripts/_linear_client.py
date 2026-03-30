"""
_linear_client.py — Thin Linear GraphQL client for sessions.py integration.

Automates routine Linear operations (issue create/update, status changes,
labels, comments) so Claude sessions can focus on reading context and doing work
instead of manually calling MCP tools for mechanical status updates.

All public functions return None/False on failure and print warnings to stderr.
They never raise exceptions — callers wrap all calls in graceful fallback blocks.
"""

from __future__ import annotations

import os
import sys
from pathlib import Path
from typing import Any, Dict, List, Optional

import httpx

# ── Constants ────────────────────────────────────────────────────────────────

API_URL = "https://api.linear.app/graphql"
TEAM_KEY = "OPE"
REQUEST_TIMEOUT = 10  # seconds

# Hardcoded IDs from the OpenMates Linear workspace (avoids lookup queries)
TEAM_ID = "8fcbd114-657d-4a68-8c27-f18c9bf7ce7b"

STATE_IDS: Dict[str, str] = {
    "In Progress": "bc70c37f-5b24-42a4-a3bc-347babe69ba6",
    "In Review": "411aa778-9c4f-43cf-bc06-d8436b875d4b",
    "Done": "bff53127-b348-4f90-94f9-414bed44fef7",
    "Todo": "3cb6411a-81b3-49d6-a10e-e95be76f1cd7",
    "Backlog": "67fcf436-5d1b-4f63-a97f-08a9357a20cb",
}

LABEL_CLAUDE_WORKING_ID = "4223e874-eb1f-4588-be6e-e28b013b8f49"

# Mode → Linear title prefix mapping
MODE_PREFIX: Dict[str, str] = {
    "feature": "Feat",
    "bug": "Fix",
    "docs": "Docs",
    "question": "Research",
    "testing": "Test",
}


# ── API Key ──────────────────────────────────────────────────────────────────

def get_api_key() -> Optional[str]:
    """Read LINEAR_API_KEY from environment, falling back to .env file."""
    key = os.environ.get("LINEAR_API_KEY")
    if key:
        return key

    # Fallback: parse .env file (same pattern as _claude_utils.py)
    env_path = Path(__file__).parent.parent / ".env"
    if env_path.is_file():
        for line in env_path.read_text().splitlines():
            line = line.strip()
            if line.startswith("LINEAR_API_KEY="):
                return line.split("=", 1)[1].strip().strip('"').strip("'")

    return None


# ── Internal GraphQL Helper ──────────────────────────────────────────────────

def _graphql(query: str, variables: Optional[Dict[str, Any]] = None) -> Optional[Dict[str, Any]]:
    """Execute a GraphQL query against Linear API. Returns parsed data or None on failure."""
    api_key = get_api_key()
    if not api_key:
        print("Warning: LINEAR_API_KEY not set — skipping Linear operation.", file=sys.stderr)
        return None

    try:
        resp = httpx.post(
            API_URL,
            json={"query": query, "variables": variables or {}},
            headers={
                "Authorization": api_key,
                "Content-Type": "application/json",
            },
            timeout=REQUEST_TIMEOUT,
        )
        resp.raise_for_status()
        result = resp.json()

        if "errors" in result:
            errors = result["errors"]
            msg = errors[0].get("message", str(errors)) if errors else "Unknown error"
            print(f"Warning: Linear API error: {msg}", file=sys.stderr)
            return None

        return result.get("data")
    except httpx.HTTPStatusError as e:
        print(f"Warning: Linear API HTTP {e.response.status_code}: {e}", file=sys.stderr)
        return None
    except Exception as e:
        print(f"Warning: Linear API request failed: {e}", file=sys.stderr)
        return None


# ── Public Functions ─────────────────────────────────────────────────────────

def get_issue(identifier: str) -> Optional[Dict[str, Any]]:
    """
    Fetch an issue by its identifier (e.g., "OPE-42").

    Returns dict with: id, identifier, title, description, url,
    state (name), assignee (name), labels (list of names).
    """
    query = """
    query GetIssue($identifier: String!) {
        issue(id: $identifier) {
            id
            identifier
            title
            description
            url
            state { name }
            assignee { name displayName }
            labels { nodes { id name } }
        }
    }
    """
    data = _graphql(query, {"identifier": identifier})
    if not data or not data.get("issue"):
        print(f"Warning: Linear issue {identifier} not found.", file=sys.stderr)
        return None

    issue = data["issue"]
    return {
        "id": issue["id"],
        "identifier": issue["identifier"],
        "title": issue["title"],
        "description": issue.get("description") or "",
        "url": issue.get("url") or "",
        "state": issue["state"]["name"] if issue.get("state") else "Unknown",
        "assignee": (
            issue["assignee"].get("displayName") or issue["assignee"].get("name")
            if issue.get("assignee") else None
        ),
        "labels": [label["name"] for label in issue.get("labels", {}).get("nodes", [])],
        "label_ids": [label["id"] for label in issue.get("labels", {}).get("nodes", [])],
    }


def create_issue(title: str, description: str = "", mode: str = "feature") -> Optional[Dict[str, Any]]:
    """
    Create a new issue in the OpenMates team.

    Args:
        title: Issue title (will be prefixed with mode prefix if not already)
        description: Optional issue description
        mode: Session mode (feature/bug/docs/question/testing) for title prefix

    Returns dict with: id, identifier, title, url — or None on failure.
    """
    # Apply mode prefix if title doesn't already start with one
    prefix = MODE_PREFIX.get(mode, "Feat")
    if not any(title.startswith(f"{p}:") or title.startswith(f"{p} :") for p in MODE_PREFIX.values()):
        title = f"{prefix}: {title}"

    # Truncate to 200 chars (Linear's limit is generous but keep it readable)
    title = title[:200]

    query = """
    mutation CreateIssue($input: IssueCreateInput!) {
        issueCreate(input: $input) {
            success
            issue {
                id
                identifier
                title
                url
            }
        }
    }
    """
    variables = {
        "input": {
            "teamId": TEAM_ID,
            "title": title,
            "description": description or None,
        }
    }

    data = _graphql(query, variables)
    if not data or not data.get("issueCreate", {}).get("success"):
        print("Warning: Failed to create Linear issue.", file=sys.stderr)
        return None

    issue = data["issueCreate"]["issue"]
    return {
        "id": issue["id"],
        "identifier": issue["identifier"],
        "title": issue["title"],
        "url": issue.get("url") or "",
    }


def update_issue_status(issue_id: str, state_name: str) -> bool:
    """
    Update an issue's workflow status.

    Args:
        issue_id: The issue's UUID (not the OPE-XX identifier)
        state_name: One of "In Progress", "In Review", "Done", "Todo", "Backlog"
    """
    state_id = STATE_IDS.get(state_name)
    if not state_id:
        print(f"Warning: Unknown Linear state '{state_name}'.", file=sys.stderr)
        return False

    query = """
    mutation UpdateIssue($id: String!, $input: IssueUpdateInput!) {
        issueUpdate(id: $id, input: $input) {
            success
        }
    }
    """
    data = _graphql(query, {"id": issue_id, "input": {"stateId": state_id}})
    return bool(data and data.get("issueUpdate", {}).get("success"))


def add_label(issue_id: str, current_label_ids: Optional[List[str]] = None) -> bool:
    """
    Add the "claude-is-working" label to an issue.

    Args:
        issue_id: The issue's UUID
        current_label_ids: Existing label IDs on the issue (to preserve them)
    """
    label_ids = list(current_label_ids or [])
    if LABEL_CLAUDE_WORKING_ID not in label_ids:
        label_ids.append(LABEL_CLAUDE_WORKING_ID)

    query = """
    mutation UpdateIssue($id: String!, $input: IssueUpdateInput!) {
        issueUpdate(id: $id, input: $input) {
            success
        }
    }
    """
    data = _graphql(query, {"id": issue_id, "input": {"labelIds": label_ids}})
    return bool(data and data.get("issueUpdate", {}).get("success"))


def remove_label(issue_id: str, current_label_ids: Optional[List[str]] = None) -> bool:
    """
    Remove the "claude-is-working" label from an issue.

    Args:
        issue_id: The issue's UUID
        current_label_ids: Existing label IDs on the issue
    """
    label_ids = [lid for lid in (current_label_ids or []) if lid != LABEL_CLAUDE_WORKING_ID]

    query = """
    mutation UpdateIssue($id: String!, $input: IssueUpdateInput!) {
        issueUpdate(id: $id, input: $input) {
            success
        }
    }
    """
    data = _graphql(query, {"id": issue_id, "input": {"labelIds": label_ids}})
    return bool(data and data.get("issueUpdate", {}).get("success"))


def post_comment(issue_id: str, body: str) -> bool:
    """
    Post a comment on an issue.

    Args:
        issue_id: The issue's UUID
        body: Markdown comment body
    """
    query = """
    mutation CreateComment($input: CommentCreateInput!) {
        commentCreate(input: $input) {
            success
        }
    }
    """
    data = _graphql(query, {"input": {"issueId": issue_id, "body": body}})
    return bool(data and data.get("commentCreate", {}).get("success"))
