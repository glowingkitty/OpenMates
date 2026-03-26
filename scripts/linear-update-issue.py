"""
Linear Issue Update Script — Post-Investigation Comment Writer.

Called by agent-trigger-watcher.sh after a Claude Code investigation session
completes for a Linear-sourced issue. Posts a comment to the Linear issue with
the session ID, resume command, and GSD workflow recommendation.

Also adds the `claude-investigated` label to the issue.

Usage (from host via docker exec):
    docker exec api python3 /app/scripts/linear-update-issue.py \
        --issue-id <linear-uuid> \
        --session-id <claude-session-id>

Runs INSIDE the `api` Docker container where httpx and LINEAR_API_KEY are available.
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
LABEL_INVESTIGATED = "claude-investigated"

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

QUERY_INVESTIGATED_LABEL = """
query GetInvestigatedLabel {
  issueLabels(filter: {
    name: { eq: "claude-investigated" }
  }) {
    nodes {
      id
      name
    }
  }
}
"""

MUTATION_UPDATE_LABELS = """
mutation UpdateIssueLabels($id: String!, $labelIds: [String!]!) {
  issueUpdate(id: $id, input: {
    labelIds: $labelIds
  }) {
    success
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
        "Authorization": f"Bearer {api_key}",
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


def build_comment_body(session_id: str) -> str:
    """
    Build the markdown comment body posted to the Linear issue.

    Args:
        session_id: Claude Code session ID from the completed investigation.

    Returns:
        Formatted markdown string for the Linear comment.
    """
    return (
        "## Claude Code Investigation Complete\n\n"
        f"**Session ID:** `{session_id}`\n\n"
        "**Resume command:**\n"
        "```\n"
        f"claude --resume {session_id}\n"
        "```\n\n"
        "**Recommended next step:**\n"
        "Review the investigation session, then run the appropriate GSD command:\n"
        "- `/gsd:debug` -- if the issue is a bug that needs fixing\n"
        "- `/gsd:quick` -- if the issue needs a small feature or refactor\n"
        "- `/gsd:execute-phase` -- if the issue relates to a roadmap phase\n\n"
        "**Status:** Awaiting developer review"
    )


def add_investigated_label(api_key: str, issue_id: str) -> None:
    """
    Add the claude-investigated label to the issue using read-then-write pattern.

    Linear requires the full set of labelIds on update (no addLabel mutation).
    Reads current labels, appends the investigated label, writes back.

    Args:
        api_key: Linear API key.
        issue_id: Linear issue UUID.
    """
    # Look up investigated label UUID
    label_result = linear_query(api_key, QUERY_INVESTIGATED_LABEL)
    label_nodes = label_result.get("issueLabels", {}).get("nodes", [])
    if not label_nodes:
        logger.warning(
            "Label '%s' not found in workspace -- skipping label update",
            LABEL_INVESTIGATED,
        )
        return
    investigated_label_id = label_nodes[0]["id"]

    # Get current issue labels
    issue_result = linear_query(
        api_key, QUERY_ISSUE_LABELS, variables={"id": issue_id}
    )
    current_labels: List[Dict[str, str]] = (
        issue_result.get("issue", {}).get("labels", {}).get("nodes", [])
    )
    current_ids = [lbl["id"] for lbl in current_labels]

    # Add investigated label if not already present
    if investigated_label_id not in current_ids:
        current_ids.append(investigated_label_id)

    linear_query(
        api_key,
        MUTATION_UPDATE_LABELS,
        variables={"id": issue_id, "labelIds": current_ids},
    )
    logger.info("Added '%s' label to issue %s", LABEL_INVESTIGATED, issue_id)


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
    args = parser.parse_args()

    api_key = os.environ.get("LINEAR_API_KEY", "")
    if not api_key:
        logger.error("LINEAR_API_KEY environment variable is not set")
        sys.exit(1)

    # Post the investigation comment
    comment_body = build_comment_body(args.session_id)
    try:
        result = linear_query(
            api_key,
            MUTATION_CREATE_COMMENT,
            variables={"issueId": args.issue_id, "body": comment_body},
        )
        success = result.get("commentCreate", {}).get("success", False)
        if success:
            logger.info(
                "Posted investigation comment to issue %s", args.issue_id
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
        sys.exit(1)

    # Add investigated label
    try:
        add_investigated_label(api_key, args.issue_id)
    except Exception:
        logger.error(
            "Failed to add investigated label to issue %s",
            args.issue_id,
            exc_info=True,
        )
        # Non-fatal: comment was already posted


if __name__ == "__main__":
    main()
