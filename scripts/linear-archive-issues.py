"""
Linear Issue Archive Script — Daily Free Plan Limit Management.

Checks if the total number of issues in the Linear workspace is approaching
the free plan limit (250). When the count reaches 230+, exports the oldest
completed/canceled issues to .planning/linear-archive.md and archives them
in Linear to free up capacity.

Target: bring count down to 200 (50 issues of buffer).

Usage (from host via docker exec):
    docker exec api python3 /app/scripts/linear-archive-issues.py

Runs INSIDE the `api` Docker container. Designed to be called once daily
via a systemd timer.
"""

import datetime
import logging
import os
import sys
from pathlib import Path
from typing import Any, Dict, List, Optional

import httpx

logger = logging.getLogger(__name__)
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(name)s] %(levelname)s: %(message)s",
)

# --- Constants ---

LINEAR_API_URL = "https://api.linear.app/graphql"
ARCHIVE_FILE = Path("/app/.planning/linear-archive.md")
ARCHIVE_THRESHOLD = 230
ARCHIVE_TARGET = 200
WARNING_THRESHOLD = 200

PRIORITY_MAP = {
    0: "None",
    1: "Urgent",
    2: "High",
    3: "Medium",
    4: "Low",
}

# --- GraphQL Queries ---

QUERY_ALL_ISSUES_COUNT = """
query AllIssuesCount {
  issues(first: 250) {
    nodes {
      id
    }
  }
}
"""

QUERY_CLOSED_ISSUES = """
query ClosedIssues {
  issues(
    filter: {
      state: { type: { in: ["completed", "canceled"] } }
    },
    first: 250,
    orderBy: createdAt
  ) {
    nodes {
      id
      identifier
      title
      createdAt
      completedAt
      priority
      url
    }
  }
}
"""

MUTATION_ARCHIVE_ISSUE = """
mutation ArchiveIssue($id: String!) {
  issueArchive(id: $id) {
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


def ensure_archive_file() -> None:
    """Create the archive file with a header if it does not exist."""
    ARCHIVE_FILE.parent.mkdir(parents=True, exist_ok=True)
    if not ARCHIVE_FILE.is_file():
        ARCHIVE_FILE.write_text(
            "# Linear Issue Archive\n\n"
            "Archived issues from Linear free plan (250 issue limit management).\n\n"
        )
        logger.info("Created archive file: %s", ARCHIVE_FILE)


def append_to_archive(issue: Dict[str, Any]) -> None:
    """
    Append a single issue's metadata to the archive markdown file.

    Args:
        issue: Linear issue node dict with identifier, title, createdAt, etc.
    """
    priority_str = PRIORITY_MAP.get(issue.get("priority", 0), "None")
    entry = (
        f"## {issue['identifier']}: {issue['title']}\n"
        f"- **Created:** {issue.get('createdAt', 'unknown')}\n"
        f"- **Completed:** {issue.get('completedAt', 'unknown')}\n"
        f"- **Priority:** {priority_str}\n"
        f"- **URL:** {issue.get('url', '')}\n"
        "---\n\n"
    )
    with open(ARCHIVE_FILE, "a") as f:
        f.write(entry)


def main() -> None:
    """
    Check issue count against threshold and archive oldest closed issues
    if the workspace is approaching the free plan limit.
    """
    api_key = os.environ.get("LINEAR_API_KEY", "")
    if not api_key:
        logger.error("LINEAR_API_KEY environment variable is not set")
        sys.exit(1)

    # Count total issues
    result = linear_query(api_key, QUERY_ALL_ISSUES_COUNT)
    total_count = len(result.get("issues", {}).get("nodes", []))
    logger.info("Total issues in workspace: %d", total_count)

    if total_count >= WARNING_THRESHOLD:
        logger.warning(
            "Issue count (%d) is above warning threshold (%d)",
            total_count,
            WARNING_THRESHOLD,
        )

    if total_count < ARCHIVE_THRESHOLD:
        logger.info(
            "Issue count (%d) is below archive threshold (%d) -- nothing to do",
            total_count,
            ARCHIVE_THRESHOLD,
        )
        return

    # Calculate how many to archive to reach target
    to_archive_count = total_count - ARCHIVE_TARGET
    logger.info(
        "Need to archive %d issues to bring count from %d to %d",
        to_archive_count,
        total_count,
        ARCHIVE_TARGET,
    )

    # Fetch closed issues sorted by creation date (oldest first)
    closed_result = linear_query(api_key, QUERY_CLOSED_ISSUES)
    closed_issues = closed_result.get("issues", {}).get("nodes", [])

    if len(closed_issues) < to_archive_count:
        logger.warning(
            "Only %d closed issues available, but need to archive %d. "
            "Archiving all available closed issues.",
            len(closed_issues),
            to_archive_count,
        )
        to_archive_count = len(closed_issues)

    issues_to_archive = closed_issues[:to_archive_count]

    # Ensure archive file exists with header
    ensure_archive_file()

    archived_count = 0
    for issue in issues_to_archive:
        identifier = issue.get("identifier", "unknown")
        try:
            # Export to archive file
            append_to_archive(issue)

            # Archive in Linear (reversible)
            linear_query(
                api_key,
                MUTATION_ARCHIVE_ISSUE,
                variables={"id": issue["id"]},
            )
            archived_count += 1
            logger.info("Archived %s: %s", identifier, issue.get("title", ""))

        except Exception:
            logger.error(
                "Failed to archive issue %s",
                identifier,
                exc_info=True,
            )
            # Continue to next issue

    logger.info(
        "Archive sweep complete: %d/%d issues archived",
        archived_count,
        to_archive_count,
    )


if __name__ == "__main__":
    main()
