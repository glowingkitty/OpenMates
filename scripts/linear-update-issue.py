"""
Linear Issue Update Script — Post-Investigation Comment Writer.

Called by agent-trigger-watcher.sh after a Claude Code investigation session
completes for a Linear-sourced issue. Posts a comment to the Linear issue with
the session ID, resume command, and GSD workflow recommendation.

Also adds the `claude-investigated` label to the issue.

Usage (from host):
    LINEAR_API_KEY=... python3 scripts/linear-update-issue.py \
        --issue-id <linear-uuid> \
        --session-id <claude-session-id>

Runs on the HOST with LINEAR_API_KEY passed via environment variable.
"""

import argparse
import logging
import os
import sys
from typing import Any, Dict, List, Optional

import httpx

logger = logging.getLogger(__name__)
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(name)s] %(levelname)s: %(message)s",
)

# --- Constants ---

LINEAR_API_URL = "https://api.linear.app/graphql"
LABEL_WORKINGONIT = "claude-workingonit"
LABEL_COMPLETE = "claude-investigate-complete"

# --- GraphQL Mutations ---

MUTATION_CREATE_COMMENT = """
mutation AddComment($issueId: String!, $body: String!) {
  commentCreate(input: {
    issueId: $issueId
    body: $body
  }) {
    success
    comment {
      id
    }
  }
}
"""

QUERY_ISSUE_LABELS = """
query GetIssueLabels($id: String!) {
  issue(id: $id) {
    labels {
      nodes {
        id
        name
      }
    }
  }
}
"""

QUERY_CLAUDE_LABELS = """
query GetClaudeLabels {
  issueLabels(filter: {
    name: { in: ["claude-workingonit", "claude-investigate-complete"] }
  }) {
    nodes {
      id
      name
    }
  }
}
"""

MUTATION_UPDATE_ISSUE = """
mutation UpdateIssue($id: String!, $labelIds: [String!]!, $stateId: String) {
  issueUpdate(id: $id, input: {
    labelIds: $labelIds
    stateId: $stateId
  }) {
    success
  }
}
"""

QUERY_WORKFLOW_STATES = """
query GetWorkflowStates {
  workflowStates {
    nodes {
      id
      name
      type
    }
  }
}
"""


def linear_query(api_key: str, query: str, variables: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
    """
    Execute a Linear GraphQL query or mutation.

    Args:
        api_key: Linear API key (Bearer token).
        query: GraphQL query/mutation string.
        variables: Optional variables dict for parameterized queries.

    Returns:
        The `data` field from the GraphQL response.

    Raises:
        RuntimeError: If the Linear API returns errors in the response body.
        httpx.HTTPStatusError: If the HTTP request fails.
    """
    headers = {
        "Authorization": api_key,
        "Content-Type": "application/json",
    }
    payload: Dict[str, Any] = {"query": query}
    if variables:
        payload["variables"] = variables

    resp = httpx.post(LINEAR_API_URL, headers=headers, json=payload, timeout=10.0)
    resp.raise_for_status()
    data = resp.json()

    if "errors" in data:
        raise RuntimeError(f"Linear API error: {data['errors']}")

    return data["data"]


def build_comment_body(response_text: str = "") -> Optional[str]:
    """
    Build a clean comment body from Claude's response, or None to skip.

    Only returns content if Claude produced substantive findings. This is a
    fallback — Claude normally posts its own findings via the Linear MCP
    during the session. This catches cases where Claude crashed or couldn't
    access MCP.

    Args:
        response_text: Full Claude response text (optional).

    Returns:
        Formatted markdown string, or None if no substantive content.
    """
    if not response_text or not response_text.strip():
        return None

    text = response_text.strip()

    # Skip non-substantive responses (permission errors, file-not-found, etc.)
    skip_phrases = [
        "need permission",
        "could you approve",
        "file doesn't exist",
        "file does not exist",
        "isn't available",
        "not available in this session",
    ]
    text_lower = text.lower()
    if any(phrase in text_lower for phrase in skip_phrases):
        return None

    # Truncate long responses
    max_len = 5000
    if len(text) > max_len:
        text = text[:max_len] + "\n\n<details><summary>Truncated</summary>\n\nResume the session for full output.\n</details>"

    return f"**Claude:**\n{text}"


def get_in_review_state_id(api_key: str) -> Optional[str]:
    """Find the 'In Review' workflow state ID. Returns None if not found."""
    result = linear_query(api_key, QUERY_WORKFLOW_STATES)
    for node in result.get("workflowStates", {}).get("nodes", []):
        if node["name"] == "In Review":
            return node["id"]
    return None


def complete_investigation(api_key: str, issue_id: str) -> None:
    """
    Finalize issue: swap labels, move to "In Review".

    Swaps claude-workingonit → claude-investigate-complete and sets
    the issue status to "In Review" in one API call.

    Args:
        api_key: Linear API key.
        issue_id: Linear issue UUID.
    """
    label_result = linear_query(api_key, QUERY_CLAUDE_LABELS)
    label_map: Dict[str, str] = {}
    for node in label_result.get("issueLabels", {}).get("nodes", []):
        label_map[node["name"]] = node["id"]

    complete_label_id = label_map.get(LABEL_COMPLETE)
    workingonit_label_id = label_map.get(LABEL_WORKINGONIT)

    if not complete_label_id:
        logger.warning(
            "Label '%s' not found in workspace -- skipping label update",
            LABEL_COMPLETE,
        )
        return

    # Get current issue labels
    issue_result = linear_query(
        api_key, QUERY_ISSUE_LABELS, variables={"id": issue_id}
    )
    current_labels: List[Dict[str, str]] = (
        issue_result.get("issue", {}).get("labels", {}).get("nodes", [])
    )

    # Remove workingonit, keep everything else
    current_ids = [
        lbl["id"] for lbl in current_labels
        if lbl["id"] != workingonit_label_id
    ]

    # Add complete if not already present
    if complete_label_id not in current_ids:
        current_ids.append(complete_label_id)

    # Combine labels + "In Review" status in one API call
    in_review_state_id = get_in_review_state_id(api_key)
    variables: Dict[str, Any] = {"id": issue_id, "labelIds": current_ids}
    if in_review_state_id:
        variables["stateId"] = in_review_state_id

    linear_query(api_key, MUTATION_UPDATE_ISSUE, variables=variables)

    status_msg = " + status → In Review" if in_review_state_id else ""
    logger.info(
        "Swapped '%s' → '%s' on issue %s%s",
        LABEL_WORKINGONIT, LABEL_COMPLETE, issue_id, status_msg,
    )


def main() -> None:
    """Parse CLI args and post investigation comment to Linear issue."""
    parser = argparse.ArgumentParser(
        description="Post Claude investigation results to a Linear issue"
    )
    parser.add_argument(
        "--issue-id",
        required=True,
        help="Linear issue UUID",
    )
    parser.add_argument(
        "--session-id",
        required=True,
        help="Claude Code session ID from the completed investigation",
    )
    parser.add_argument(
        "--status",
        default="completed",
        choices=["completed", "timeout", "error"],
        help="Investigation outcome (default: completed)",
    )
    parser.add_argument(
        "--response-file",
        default="",
        help="Path to file containing Claude's full response text",
    )
    args = parser.parse_args()

    api_key = os.environ.get("LINEAR_API_KEY", "")
    if not api_key:
        logger.error("LINEAR_API_KEY environment variable is not set")
        sys.exit(1)

    # Read full response if provided
    response_text = ""
    if args.response_file and os.path.isfile(args.response_file):
        try:
            response_text = open(args.response_file).read().strip()
        except Exception:
            logger.warning("Could not read response file: %s", args.response_file)

    # Post a comment only if Claude produced substantive findings
    # (Claude normally posts its own via MCP — this is the fallback)
    comment_body = build_comment_body(response_text)
    if comment_body:
        try:
            result = linear_query(
                api_key,
                MUTATION_CREATE_COMMENT,
                variables={"issueId": args.issue_id, "body": comment_body},
            )
            success = result.get("commentCreate", {}).get("success", False)
            if success:
                logger.info(
                    "Posted findings comment to issue %s", args.issue_id
                )
            else:
                logger.error(
                    "Comment creation returned success=false for issue %s",
                    args.issue_id,
                )
        except Exception:
            logger.error(
                "Failed to post comment to issue %s",
                args.issue_id,
                exc_info=True,
            )
    else:
        logger.info("No substantive findings to post for issue %s", args.issue_id)

    # Swap labels + move to "In Review"
    try:
        complete_investigation(api_key, args.issue_id)
    except Exception:
        logger.error(
            "Failed to swap label on issue %s",
            args.issue_id,
            exc_info=True,
        )
        # Non-fatal: comment was already posted


if __name__ == "__main__":
    main()
