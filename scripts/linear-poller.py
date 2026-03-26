"""
Linear Issue Poller for Claude Code Investigation Pipeline.

Single-run script that queries Linear for issues labeled `claude-investigate`,
writes trigger files to the agent pipeline, and immediately removes the label
to prevent duplicate processing. Designed to run every 30s via a systemd
service loop: `docker exec api python3 /app/scripts/linear-poller.py`.

Runs INSIDE the `api` Docker container where httpx and Vault-injected
LINEAR_API_KEY are available. Trigger files are written to the bind-mounted
scripts/.agent-triggers/ directory for the host-side watcher to pick up.
"""

import datetime
import json
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
TRIGGER_DIR = Path("/app/scripts/.agent-triggers")
PROMPT_TEMPLATE_PATH = Path("/app/scripts/prompts/linear-issue-investigation.md")

PRIORITY_MAP = {
    0: "None",
    1: "Urgent",
    2: "High",
    3: "Medium",
    4: "Low",
}

# Label name constants
LABEL_INVESTIGATE = "claude-investigate"
LABEL_INVESTIGATED = "claude-investigated"

# --- GraphQL Queries ---

QUERY_INVESTIGATE_ISSUES = """
query GetInvestigateIssues {
  issues(filter: {
    labels: { name: { eq: "claude-investigate" } }
  }) {
    nodes {
      id
      identifier
      title
      description
      priority
      url
      labels {
        nodes {
          id
          name
        }
      }
    }
  }
}
"""

QUERY_LABEL_IDS = """
query GetLabels {
  issueLabels(filter: {
    name: { in: ["claude-investigate", "claude-investigated"] }
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
    issue {
      id
      labels { nodes { id name } }
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


def get_label_ids(api_key: str) -> Dict[str, str]:
    """
    Fetch the UUIDs for claude-investigate and claude-investigated labels.

    Returns:
        Dict mapping label name to label UUID, e.g.
        {"claude-investigate": "uuid1", "claude-investigated": "uuid2"}.
    """
    result = linear_query(api_key, QUERY_LABEL_IDS)
    label_map: Dict[str, str] = {}
    for node in result.get("issueLabels", {}).get("nodes", []):
        label_map[node["name"]] = node["id"]
    return label_map


def render_prompt(issue: Dict[str, Any]) -> str:
    """
    Render the investigation prompt template with issue data.

    Args:
        issue: Linear issue node dict with id, identifier, title, etc.

    Returns:
        Rendered prompt string ready for the trigger file.
    """
    if PROMPT_TEMPLATE_PATH.is_file():
        template = PROMPT_TEMPLATE_PATH.read_text()
    else:
        logger.error("Prompt template not found at %s", PROMPT_TEMPLATE_PATH)
        sys.exit(1)

    priority_str = PRIORITY_MAP.get(issue.get("priority", 0), "None")

    # Build labels string (excluding claude-investigate)
    label_names = [
        lbl["name"]
        for lbl in issue.get("labels", {}).get("nodes", [])
        if lbl["name"] != LABEL_INVESTIGATE
    ]
    labels_str = ", ".join(label_names) if label_names else "None"

    date_str = datetime.datetime.utcnow().strftime("%Y-%m-%d %H:%M UTC")

    return (
        template
        .replace("{{LINEAR_IDENTIFIER}}", issue.get("identifier", ""))
        .replace("{{TITLE}}", issue.get("title", ""))
        .replace("{{DESCRIPTION}}", issue.get("description", "") or "(no description provided)")
        .replace("{{PRIORITY}}", priority_str)
        .replace("{{LABELS}}", labels_str)
        .replace("{{URL}}", issue.get("url", ""))
        .replace("{{DATE}}", date_str)
    )


def write_trigger_file(issue: Dict[str, Any], prompt: str) -> Path:
    """
    Write an atomic trigger JSON file for the agent-trigger-watcher.

    Writes to a .tmp file first, then renames to .json for atomicity.
    The watcher only globs *.json, so partial writes are never picked up.

    Args:
        issue: Linear issue node dict.
        prompt: Rendered investigation prompt.

    Returns:
        Path to the written trigger file.
    """
    TRIGGER_DIR.mkdir(parents=True, exist_ok=True)

    identifier = issue.get("identifier", "unknown")
    linear_id = issue["id"]
    date_str = datetime.datetime.utcnow().strftime("%Y-%m-%d")

    payload = {
        "issue_id": f"linear-{identifier}",
        "linear_issue_id": linear_id,
        "linear_identifier": identifier,
        "session_title": f"Linear {identifier}: {issue.get('title', 'Investigation')}",
        "prompt": prompt,
        "source": "linear-poller",
        "created_at": datetime.datetime.utcnow().isoformat() + "Z",
    }

    # Atomic write: .tmp then rename
    trigger_file = TRIGGER_DIR / f"linear-{identifier}.json"
    tmp_file = TRIGGER_DIR / f"linear-{identifier}.json.tmp"

    tmp_file.write_text(json.dumps(payload, indent=2))
    os.rename(str(tmp_file), str(trigger_file))

    return trigger_file


def remove_investigate_label(
    api_key: str,
    issue: Dict[str, Any],
    label_ids: Dict[str, str],
) -> None:
    """
    Remove claude-investigate label and add claude-investigated label.

    Uses the read-then-write pattern required by Linear's API: reads current
    label IDs from the issue, filters out claude-investigate, adds
    claude-investigated, then sends the full label list via issueUpdate.

    Args:
        api_key: Linear API key.
        issue: Linear issue node dict (must include labels.nodes[].id).
        label_ids: Dict mapping label names to UUIDs.
    """
    investigate_label_id = label_ids.get(LABEL_INVESTIGATE)
    investigated_label_id = label_ids.get(LABEL_INVESTIGATED)

    # Build new label list: remove investigate, add investigated
    current_label_ids = [
        lbl["id"]
        for lbl in issue.get("labels", {}).get("nodes", [])
        if lbl["id"] != investigate_label_id
    ]

    if investigated_label_id and investigated_label_id not in current_label_ids:
        current_label_ids.append(investigated_label_id)

    linear_query(
        api_key,
        MUTATION_UPDATE_LABELS,
        variables={"id": issue["id"], "labelIds": current_label_ids},
    )


def main() -> None:
    """
    Main polling loop entry point. Fetches issues with claude-investigate label,
    writes trigger files, and removes the label immediately to prevent duplicates.
    """
    api_key = os.environ.get("LINEAR_API_KEY", "")
    if not api_key:
        logger.error("LINEAR_API_KEY environment variable is not set")
        sys.exit(1)

    # Fetch label UUIDs once at startup
    label_ids = get_label_ids(api_key)
    if LABEL_INVESTIGATE not in label_ids:
        logger.warning(
            "Label '%s' not found in Linear workspace. "
            "Create it before using the poller.",
            LABEL_INVESTIGATE,
        )
        return

    if LABEL_INVESTIGATED not in label_ids:
        logger.warning(
            "Label '%s' not found in Linear workspace. "
            "Create it before using the poller.",
            LABEL_INVESTIGATED,
        )

    # Fetch issues with claude-investigate label
    result = linear_query(api_key, QUERY_INVESTIGATE_ISSUES)
    issues = result.get("issues", {}).get("nodes", [])

    if not issues:
        logger.info("No issues with '%s' label found", LABEL_INVESTIGATE)
        return

    logger.info("Found %d issue(s) with '%s' label", len(issues), LABEL_INVESTIGATE)

    for issue in issues:
        identifier = issue.get("identifier", "unknown")
        title = issue.get("title", "")

        try:
            # Step 1: Render prompt
            prompt = render_prompt(issue)
            logger.info("Rendered prompt for %s: %s", identifier, title)

            # Step 2: Write atomic trigger file
            trigger_path = write_trigger_file(issue, prompt)
            logger.info("Wrote trigger file: %s", trigger_path)

            # Step 3: Immediately remove label to prevent duplicate processing
            # This is the critical duplicate-prevention step
            remove_investigate_label(api_key, issue, label_ids)
            logger.info(
                "Removed '%s' label from %s",
                LABEL_INVESTIGATE,
                identifier,
            )

        except Exception:
            logger.error(
                "Failed to process issue %s: %s",
                identifier,
                title,
                exc_info=True,
            )
            # Continue to next issue -- don't let one failure block others


if __name__ == "__main__":
    main()
