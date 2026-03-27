"""
Linear Session Start Hook — Creates or updates a Linear issue for the Claude session.

Receives SessionStart event JSON on stdin. For Linear-triggered sessions (env var
CLAUDE_LINEAR_ISSUE_ID set), updates the existing issue. For interactive sessions,
creates a new issue with the claude-session label.

Writes CLAUDE_LINEAR_ISSUE_ID and CLAUDE_LINEAR_SOURCE to CLAUDE_ENV_FILE so
subsequent hooks (SubagentStop, SessionEnd) can reference the same issue.

Silently exits if LINEAR_API_KEY is not set (non-Linear environments).
"""

import json
import logging
import os
import sys
from pathlib import Path
from typing import Any, Dict, Optional

import httpx

logger = logging.getLogger(__name__)
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [linear-hook] %(levelname)s: %(message)s",
)

LINEAR_API_URL = "https://api.linear.app/graphql"
LABEL_SESSION = "claude-session"

QUERY_FIND_BY_SESSION = """
query FindBySession($sessionKey: String!) {
  issues(filter: { description: { contains: $sessionKey } }, first: 1) {
    nodes {
      id
      identifier
    }
  }
}
"""

QUERY_LABEL_ID = """
query GetLabel($name: String!) {
  issueLabels(filter: { name: { eq: $name } }) {
    nodes { id }
  }
}
"""

QUERY_WORKFLOW_STATES = """
query GetWorkflowStates {
  workflowStates {
    nodes { id name type }
  }
}
"""

MUTATION_CREATE_ISSUE = """
mutation CreateIssue($title: String!, $description: String, $labelIds: [String!], $stateId: String, $teamId: String!) {
  issueCreate(input: {
    title: $title
    description: $description
    labelIds: $labelIds
    stateId: $stateId
    teamId: $teamId
  }) {
    success
    issue { id identifier url }
  }
}
"""

MUTATION_UPDATE_STATE = """
mutation UpdateState($id: String!, $stateId: String!) {
  issueUpdate(id: $id, input: { stateId: $stateId }) {
    success
  }
}
"""


def linear_query(api_key: str, query: str, variables: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
    """Execute a Linear GraphQL query."""
    headers = {"Authorization": api_key, "Content-Type": "application/json"}
    payload: Dict[str, Any] = {"query": query}
    if variables:
        payload["variables"] = variables
    resp = httpx.post(LINEAR_API_URL, headers=headers, json=payload, timeout=8.0)
    resp.raise_for_status()
    data = resp.json()
    if "errors" in data:
        raise RuntimeError(f"Linear API error: {data['errors']}")
    return data["data"]


def get_state_id(api_key: str, name: str) -> Optional[str]:
    """Find a workflow state ID by name."""
    result = linear_query(api_key, QUERY_WORKFLOW_STATES)
    for node in result.get("workflowStates", {}).get("nodes", []):
        if node["name"] == name:
            return node["id"]
    return None


def write_env(env_file: str, key: str, value: str) -> None:
    """Append a key=value line to the CLAUDE_ENV_FILE."""
    with open(env_file, "a") as f:
        f.write(f"{key}={value}\n")


def main() -> None:
    api_key = os.environ.get("LINEAR_API_KEY", "")
    if not api_key:
        sys.exit(0)

    # Auto-discover team ID if not set
    team_id = os.environ.get("LINEAR_TEAM_ID", "")
    if not team_id:
        try:
            result = linear_query(api_key, "query { teams { nodes { id } } }")
            teams = result.get("teams", {}).get("nodes", [])
            if teams:
                team_id = teams[0]["id"]
            else:
                sys.exit(0)
        except Exception:
            sys.exit(0)

    env_file = os.environ.get("CLAUDE_ENV_FILE", "")
    if not env_file:
        sys.exit(0)

    # Read event data from stdin
    try:
        event = json.load(sys.stdin)
    except (json.JSONDecodeError, EOFError):
        sys.exit(0)

    session_id = event.get("session_id", "")
    if not session_id:
        sys.exit(0)

    # Always persist session ID so other hooks (FileChanged) can reference it
    write_env(env_file, "CLAUDE_SESSION_ID", session_id)

    # Check if this is a Linear-triggered session
    existing_issue_id = os.environ.get("CLAUDE_LINEAR_ISSUE_ID", "")

    if existing_issue_id:
        # Linear-triggered: update existing issue to In Progress
        in_progress_id = get_state_id(api_key, "In Progress")
        if in_progress_id:
            try:
                linear_query(api_key, MUTATION_UPDATE_STATE, {
                    "id": existing_issue_id, "stateId": in_progress_id,
                })
            except Exception:
                logger.debug("Failed to update Linear issue state", exc_info=True)

        write_env(env_file, "CLAUDE_LINEAR_ISSUE_ID", existing_issue_id)
        write_env(env_file, "CLAUDE_LINEAR_SOURCE", "linear")
        sys.exit(0)

    # Fallback: check session-to-issue mapping file (covers resumed Linear-triggered sessions)
    # The poller writes scripts/.tmp/linear-sessions/<session_id> containing the issue UUID
    mapping_file = Path(__file__).resolve().parent.parent / ".tmp" / "linear-sessions" / session_id
    if mapping_file.is_file():
        mapped_issue_id = mapping_file.read_text().strip()
        if mapped_issue_id:
            write_env(env_file, "CLAUDE_LINEAR_ISSUE_ID", mapped_issue_id)
            write_env(env_file, "CLAUDE_LINEAR_SOURCE", "linear")
            in_progress_id = get_state_id(api_key, "In Progress")
            if in_progress_id:
                try:
                    linear_query(api_key, MUTATION_UPDATE_STATE, {
                        "id": mapped_issue_id, "stateId": in_progress_id,
                    })
                except Exception:
                    logger.debug("Failed to update Linear issue state on resume", exc_info=True)
            sys.exit(0)

    # Interactive sessions: only track if explicitly opted in via env var
    # Set CLAUDE_LINEAR_ENABLE=1 in .env to auto-create Linear issues for all sessions
    if not os.environ.get("CLAUDE_LINEAR_ENABLE", ""):
        sys.exit(0)

    # Check if issue already exists for this session (resume case)
    try:
        search_key = f"claude-session-id:{session_id}"
        result = linear_query(api_key, QUERY_FIND_BY_SESSION, {"sessionKey": search_key})
        nodes = result.get("issues", {}).get("nodes", [])

        if nodes:
            # Resume: update existing issue
            issue_id = nodes[0]["id"]
            in_progress_id = get_state_id(api_key, "In Progress")
            if in_progress_id:
                linear_query(api_key, MUTATION_UPDATE_STATE, {
                    "id": issue_id, "stateId": in_progress_id,
                })
            write_env(env_file, "CLAUDE_LINEAR_ISSUE_ID", issue_id)
            write_env(env_file, "CLAUDE_LINEAR_SOURCE", "interactive")
            sys.exit(0)

        # New session: create issue
        label_result = linear_query(api_key, QUERY_LABEL_ID, {"name": LABEL_SESSION})
        label_nodes = label_result.get("issueLabels", {}).get("nodes", [])
        label_ids = [label_nodes[0]["id"]] if label_nodes else []

        in_progress_id = get_state_id(api_key, "In Progress")

        # Build title from session name or short ID
        short_id = session_id[:8]
        title = f"Claude session {short_id}"

        description = (
            f"Auto-created by Claude Code session hook.\n\n"
            f"**claude-session-id:{session_id}**\n\n"
            f"Resume: `claude --resume {session_id}`"
        )

        variables: Dict[str, Any] = {
            "title": title,
            "description": description,
            "labelIds": label_ids,
            "teamId": team_id,
        }
        if in_progress_id:
            variables["stateId"] = in_progress_id

        result = linear_query(api_key, MUTATION_CREATE_ISSUE, variables)
        issue = result.get("issueCreate", {}).get("issue", {})
        issue_id = issue.get("id", "")

        if issue_id:
            write_env(env_file, "CLAUDE_LINEAR_ISSUE_ID", issue_id)
            write_env(env_file, "CLAUDE_LINEAR_SOURCE", "interactive")
            identifier = issue.get("identifier", "")
            url = issue.get("url", "")
            # Stdout is added to Claude's context
            print(f"Linear issue created: {identifier} — {url}")

    except Exception:
        # Never block Claude — silently fail
        logger.debug("Linear session-start hook failed", exc_info=True)

    sys.exit(0)


if __name__ == "__main__":
    main()
