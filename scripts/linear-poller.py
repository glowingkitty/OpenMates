"""
Linear Issue Poller for Claude Code Investigation Pipeline.

Single-run script that queries Linear for issues labeled `claude-investigate`,
writes trigger files to the agent pipeline, and immediately removes the label
to prevent duplicate processing. Also polls for new developer comments on
active issues to trigger session resumes.

Designed to run every 30s via a systemd service loop:
  python3 scripts/linear-poller.py

Claude reads issue details (description, attachments, images, comments) directly
via the Linear MCP server during the session — this script only needs to detect
triggers and write minimal prompt files.

Runs on the HOST (not inside Docker). Sources LINEAR_API_KEY from the project
.env file via the systemd EnvironmentFile directive. httpx is available on
the host Python. Trigger files are written to scripts/.agent-triggers/ for
the host-side watcher to pick up.
"""

import datetime
import json
import logging
import os
import sys
import uuid
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
SCRIPT_DIR = Path(__file__).resolve().parent
TRIGGER_DIR = SCRIPT_DIR / ".agent-triggers"
TMP_DIR = SCRIPT_DIR / ".tmp"
PROMPT_TEMPLATE_PATH = SCRIPT_DIR / "prompts" / "linear-issue-investigation.md"

# Session-to-issue mapping and comment state
SESSIONS_DIR = TMP_DIR / "linear-sessions"
COMMENT_STATE_FILE = TMP_DIR / "linear-comment-state.json"
RESUME_PROMPT_PATH = SCRIPT_DIR / "prompts" / "linear-resume-comment.md"

# Label name constants
LABEL_INVESTIGATE = "claude-investigate"
LABEL_GSD_QUICK = "claude-gsd-quick"
LABEL_GSD_DEBUG = "claude-gsd-debug"
LABEL_GSD_ADD_PHASE = "claude-gsd-add-phase"
LABEL_WORKINGONIT = "claude-workingonit"
LABEL_COMPLETE = "claude-investigate-complete"

# Labels indicating an active/completed Claude session (for comment polling)
LABELS_WITH_SESSIONS = [LABEL_WORKINGONIT, LABEL_COMPLETE]

# Trigger labels → (mode, permission_mode, gsd_command)
TRIGGER_LABELS = {
    LABEL_INVESTIGATE: ("investigate", "plan", None),
    LABEL_GSD_QUICK: ("gsd-quick", "auto", "/gsd:quick"),
    LABEL_GSD_DEBUG: ("gsd-debug", "auto", "/gsd:debug"),
    LABEL_GSD_ADD_PHASE: ("gsd-add-phase", "auto", "/gsd:add-phase"),
}

# Issue fields fragment — minimal since Claude reads details via Linear MCP
ISSUE_FIELDS = """
      id
      identifier
      title
      url
      labels {
        nodes {
          id
          name
        }
      }
"""

# All trigger label names for the query filter
ALL_LABEL_NAMES = list(TRIGGER_LABELS.keys()) + [LABEL_WORKINGONIT, LABEL_COMPLETE]

# --- GraphQL Queries ---

QUERY_TRIGGERED_ISSUES = """
query GetTriggeredIssues($labels: [String!]!) {
  issues(filter: {
    labels: { name: { in: $labels } }
  }) {
    nodes {""" + ISSUE_FIELDS + """    }
  }
}
"""

QUERY_LABEL_IDS = """
query GetLabels($names: [String!]!) {
  issueLabels(filter: {
    name: { in: $names }
  }) {
    nodes {
      id
      name
    }
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

MUTATION_UPDATE_ISSUE = """
mutation UpdateIssue($id: String!, $labelIds: [String!]!, $stateId: String) {
  issueUpdate(id: $id, input: {
    labelIds: $labelIds
    stateId: $stateId
  }) {
    success
    issue {
      id
      labels { nodes { id name } }
    }
  }
}
"""

QUERY_ISSUES_WITH_COMMENTS = """
query GetIssuesWithComments($labels: [String!]!) {
  issues(filter: {
    labels: { name: { in: $labels } }
  }) {
    nodes {
      id
      identifier
      title
      comments(orderBy: createdAt) {
        nodes {
          id
          body
          createdAt
          user {
            id
            name
            isMe
          }
        }
      }
    }
  }
}
"""

MUTATION_CREATE_COMMENT = """
mutation AddComment($issueId: String!, $body: String!) {
  commentCreate(input: {
    issueId: $issueId
    body: $body
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


def get_label_ids(api_key: str) -> Dict[str, str]:
    """
    Fetch the UUIDs for all claude-* labels.

    Returns:
        Dict mapping label name to label UUID, e.g.
        {"claude-investigate": "uuid1", "claude-workingonit": "uuid2", ...}.
    """
    result = linear_query(api_key, QUERY_LABEL_IDS, {"names": ALL_LABEL_NAMES})
    label_map: Dict[str, str] = {}
    for node in result.get("issueLabels", {}).get("nodes", []):
        label_map[node["name"]] = node["id"]
    return label_map


def get_in_progress_state_id(api_key: str) -> Optional[str]:
    """
    Find the 'In Progress' workflow state ID. Returns None if not found.
    """
    result = linear_query(api_key, QUERY_WORKFLOW_STATES)
    for node in result.get("workflowStates", {}).get("nodes", []):
        if node["name"] == "In Progress" and node["type"] == "started":
            return node["id"]
    return None


def render_prompt(
    issue: Dict[str, Any],
    template_path: Optional[Path] = None,
) -> str:
    """
    Render a prompt template with issue metadata.

    The prompt is minimal — it tells Claude which Linear issue to investigate.
    Claude reads the full issue (description, attachments, images, comments)
    directly via the Linear MCP server during the session.

    Args:
        issue: Linear issue node dict with identifier, title, url.
        template_path: Optional override for the template file. Defaults to
            the investigation prompt template.

    Returns:
        Rendered prompt string ready for the trigger file.
    """
    path = template_path or PROMPT_TEMPLATE_PATH
    if path.is_file():
        template = path.read_text()
    else:
        logger.error("Prompt template not found at %s", path)
        sys.exit(1)

    date_str = datetime.datetime.now(datetime.UTC).strftime("%Y-%m-%d %H:%M UTC")

    return (
        template
        .replace("{{LINEAR_IDENTIFIER}}", issue.get("identifier", ""))
        .replace("{{TITLE}}", issue.get("title", ""))
        .replace("{{URL}}", issue.get("url", ""))
        .replace("{{DATE}}", date_str)
    )


def write_trigger_file(
    issue: Dict[str, Any],
    prompt: str,
    session_id: str,
    mode: str = "investigate",
) -> Path:
    """
    Write an atomic trigger JSON file for the agent-trigger-watcher.

    Writes to a .tmp file first, then renames to .json for atomicity.
    The watcher only globs *.json, so partial writes are never picked up.

    Args:
        issue: Linear issue node dict.
        prompt: Rendered investigation prompt.
        session_id: Pre-generated UUID for the Claude session.
        mode: Execution mode — "investigate" (plan) or "gsd-quick" (auto).

    Returns:
        Path to the written trigger file.
    """
    TRIGGER_DIR.mkdir(parents=True, exist_ok=True)

    identifier = issue.get("identifier", "unknown")
    linear_id = issue["id"]

    payload = {
        "issue_id": f"linear-{identifier}",
        "linear_issue_id": linear_id,
        "linear_identifier": identifier,
        "session_id": session_id,
        "mode": mode,
        "session_title": f"Linear {identifier}: {issue.get('title', 'Investigation')}",
        "prompt": prompt,
        "source": "linear-poller",
        "created_at": datetime.datetime.now(datetime.UTC).isoformat() + "Z",
    }

    # Atomic write: .tmp then rename
    trigger_file = TRIGGER_DIR / f"linear-{identifier}.json"
    tmp_file = TRIGGER_DIR / f"linear-{identifier}.json.tmp"

    tmp_file.write_text(json.dumps(payload, indent=2))
    os.rename(str(tmp_file), str(trigger_file))

    return trigger_file


def start_investigation(
    api_key: str,
    issue: Dict[str, Any],
    label_ids: Dict[str, str],
    session_id: str,
    in_progress_state_id: Optional[str],
    trigger_label: str = LABEL_INVESTIGATE,
    mode: str = "investigate",
) -> None:
    """
    Mark issue as being worked on: swap labels and set In Progress.

    Swaps the trigger label → claude-workingonit and moves to In Progress.
    No comment is posted — labels are the status indicator. Claude posts
    its own findings via the Linear MCP when the investigation completes.

    Args:
        api_key: Linear API key.
        issue: Linear issue node dict (must include labels.nodes[].id).
        label_ids: Dict mapping label names to UUIDs.
        session_id: Pre-generated Claude session UUID.
        in_progress_state_id: Workflow state ID for "In Progress" (or None).
        trigger_label: The label that triggered this (to remove).
        mode: Execution mode (unused, kept for call-site compatibility).
    """
    investigate_label_id = label_ids.get(trigger_label)
    workingonit_label_id = label_ids.get(LABEL_WORKINGONIT)

    # Build new label list: remove investigate, add workingonit
    current_label_ids = [
        lbl["id"]
        for lbl in issue.get("labels", {}).get("nodes", [])
        if lbl["id"] != investigate_label_id
    ]

    if workingonit_label_id and workingonit_label_id not in current_label_ids:
        current_label_ids.append(workingonit_label_id)

    # Update labels + status in one API call
    variables: Dict[str, Any] = {"id": issue["id"], "labelIds": current_label_ids}
    if in_progress_state_id:
        variables["stateId"] = in_progress_state_id

    linear_query(api_key, MUTATION_UPDATE_ISSUE, variables=variables)

    # Post a minimal "started" comment with just the resume command
    identifier = issue.get("identifier", "unknown")
    comment_body = f"`claude --resume {session_id}`"
    linear_query(
        api_key,
        MUTATION_CREATE_COMMENT,
        variables={"issueId": issue["id"], "body": comment_body},
    )
    logger.info("Marked %s as in-progress (session %s)", identifier, session_id)


def find_session_for_issue(issue_id: str) -> Optional[str]:
    """
    Find the Claude session ID associated with a Linear issue UUID.

    Scans the session-to-issue mapping files in scripts/.tmp/linear-sessions/.
    Each file is named after the session UUID and contains the Linear issue UUID.

    Args:
        issue_id: Linear issue UUID to look up.

    Returns:
        Session UUID string if found, None otherwise.
    """
    if not SESSIONS_DIR.is_dir():
        return None
    for f in SESSIONS_DIR.iterdir():
        if f.is_file():
            try:
                if f.read_text().strip() == issue_id:
                    return f.name
            except OSError:
                continue
    return None


def render_resume_prompt(identifier: str) -> str:
    """
    Render the resume prompt template for a comment-triggered resume.

    The prompt is minimal — it tells Claude to check the Linear issue for new
    comments via the MCP server and continue working based on what was said.

    Args:
        identifier: Linear issue identifier (e.g., OPE-42).

    Returns:
        Rendered prompt string for the resume trigger.
    """
    if RESUME_PROMPT_PATH.is_file():
        template = RESUME_PROMPT_PATH.read_text()
    else:
        # Inline fallback if template file doesn't exist
        template = (
            "The developer left new comments on Linear issue "
            "{{LINEAR_IDENTIFIER}}.\n\n"
            "Use your Linear MCP tools to read the latest comments, then "
            "continue working based on what the developer said."
        )

    return template.replace("{{LINEAR_IDENTIFIER}}", identifier)


def load_comment_state() -> Dict[str, str]:
    """
    Load the comment state file tracking last-seen comment IDs per issue.

    Returns:
        Dict mapping Linear issue UUID to the last-seen comment ID.
    """
    if COMMENT_STATE_FILE.is_file():
        try:
            return json.loads(COMMENT_STATE_FILE.read_text())
        except (json.JSONDecodeError, OSError):
            return {}
    return {}


def save_comment_state(state: Dict[str, str]) -> None:
    """Save the comment state file atomically."""
    TMP_DIR.mkdir(parents=True, exist_ok=True)
    tmp = COMMENT_STATE_FILE.with_suffix(".json.tmp")
    tmp.write_text(json.dumps(state, indent=2))
    os.rename(str(tmp), str(COMMENT_STATE_FILE))


def check_comment_triggers(api_key: str) -> None:
    """
    Poll for new developer comments on issues with active Claude sessions.

    Queries issues labeled claude-workingonit or claude-investigate-complete,
    checks for comments newer than the last-seen comment, skips bot comments
    (isMe=true), and writes resume trigger files for new human comments.

    Args:
        api_key: Linear API key for GraphQL queries.
    """
    result = linear_query(
        api_key, QUERY_ISSUES_WITH_COMMENTS, {"labels": LABELS_WITH_SESSIONS}
    )
    issues = result.get("issues", {}).get("nodes", [])

    if not issues:
        return

    state = load_comment_state()
    state_changed = False

    for issue in issues:
        issue_id = issue["id"]
        identifier = issue.get("identifier", "unknown")
        comments = issue.get("comments", {}).get("nodes", [])

        if not comments:
            continue

        last_seen_id = state.get(issue_id, "")

        # Find new comments after the last-seen one
        new_comments: List[Dict[str, Any]] = []
        found_last_seen = not last_seen_id  # If no last seen, all are new
        for comment in comments:
            if comment["id"] == last_seen_id:
                found_last_seen = True
                continue
            if found_last_seen:
                new_comments.append(comment)

        if not new_comments:
            continue

        # Update state to the latest comment ID
        state[issue_id] = comments[-1]["id"]
        state_changed = True

        # Filter to human comments only (skip bot/API-created ones)
        human_comments = [
            c for c in new_comments
            if not c.get("user", {}).get("isMe", False)
        ]

        if not human_comments:
            logger.debug("Skipping %d bot comment(s) on %s", len(new_comments), identifier)
            continue

        # Find the session ID for this issue
        session_id = find_session_for_issue(issue_id)
        if not session_id:
            logger.warning(
                "New comment on %s but no session mapping found — skipping",
                identifier,
            )
            continue

        # Write a resume trigger — Claude reads comments directly via MCP
        prompt = render_resume_prompt(identifier)

        TRIGGER_DIR.mkdir(parents=True, exist_ok=True)
        payload = {
            "issue_id": f"linear-{identifier}",
            "linear_issue_id": issue_id,
            "linear_identifier": identifier,
            "session_id": session_id,
            "mode": "resume",
            "session_title": f"Linear {identifier}: Resume (comment)",
            "prompt": prompt,
            "source": "linear-poller-comment",
            "created_at": datetime.datetime.now(datetime.UTC).isoformat() + "Z",
        }

        trigger_file = TRIGGER_DIR / f"linear-{identifier}-resume.json"
        tmp_file = TRIGGER_DIR / f"linear-{identifier}-resume.json.tmp"
        tmp_file.write_text(json.dumps(payload, indent=2))
        os.rename(str(tmp_file), str(trigger_file))

        logger.info(
            "Comment-triggered resume for %s (session %s, %d new comment(s))",
            identifier, session_id, len(human_comments),
        )

    if state_changed:
        save_comment_state(state)


def main() -> None:
    """
    Main polling loop entry point. Fetches issues with trigger labels, writes
    trigger files, removes labels, and checks for comment-triggered resumes.
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

    for label_name in [LABEL_WORKINGONIT, LABEL_COMPLETE]:
        if label_name not in label_ids:
            logger.warning(
                "Label '%s' not found in Linear workspace. Create it.",
                label_name,
            )

    # Look up "In Progress" workflow state (optional — skip if not found)
    in_progress_state_id = get_in_progress_state_id(api_key)
    if not in_progress_state_id:
        logger.warning("'In Progress' workflow state not found — will skip status update")

    # Single query: fetch all issues with any claude trigger label
    trigger_label_names = list(TRIGGER_LABELS.keys())
    result = linear_query(api_key, QUERY_TRIGGERED_ISSUES, {"labels": trigger_label_names})
    all_issues = result.get("issues", {}).get("nodes", [])

    # Route each issue by its FIRST matching trigger label (prevents processing conflicts)
    jobs = []
    seen_ids = set()
    for issue in all_issues:
        issue_id = issue["id"]
        if issue_id in seen_ids:
            continue
        seen_ids.add(issue_id)

        # Find the first trigger label on this issue
        issue_label_names = [lbl["name"] for lbl in issue.get("labels", {}).get("nodes", [])]
        trigger_label = None
        for label_name in trigger_label_names:
            if label_name in issue_label_names:
                trigger_label = label_name
                break

        if not trigger_label:
            continue

        mode, _perm, gsd_command = TRIGGER_LABELS[trigger_label]
        jobs.append((issue, mode, trigger_label, gsd_command))

    if not jobs:
        logger.info("No issues with claude trigger labels found")
    else:
        logger.info("Found %d issue(s) to process", len(jobs))

    for issue, mode, trigger_label, gsd_command in jobs:
        identifier = issue.get("identifier", "unknown")
        title = issue.get("title", "")

        try:
            # Step 1: Pre-generate session UUID and persist mapping
            session_id = str(uuid.uuid4())
            SESSIONS_DIR.mkdir(parents=True, exist_ok=True)
            (SESSIONS_DIR / session_id).write_text(issue["id"])

            # Step 2: Render prompt based on mode (Claude reads full issue via MCP)
            if mode == "investigate":
                prompt = render_prompt(issue)
            else:
                # GSD commands use the generic GSD prompt template
                gsd_prompt_path = SCRIPT_DIR / "prompts" / "linear-gsd-command.md"
                if gsd_prompt_path.is_file():
                    prompt = render_prompt(issue, template_path=gsd_prompt_path)
                    # Inject the specific GSD command
                    prompt = prompt.replace("{{GSD_COMMAND}}", gsd_command or "/gsd:quick")
                else:
                    prompt = render_prompt(issue)
                    logger.warning("GSD command prompt template not found, using investigation template")
            logger.info("Rendered %s prompt for %s: %s", mode, identifier, title)

            # Step 3: Write atomic trigger file
            trigger_path = write_trigger_file(issue, prompt, session_id, mode=mode)
            logger.info("Wrote trigger file: %s", trigger_path)

            # Step 4: Update Linear immediately — swap labels, set In Progress, post comment
            start_investigation(
                api_key, issue, label_ids, session_id, in_progress_state_id,
                trigger_label=trigger_label, mode=mode,
            )
            logger.info(
                "Started %s for %s (session %s)",
                mode, identifier, session_id,
            )

        except Exception:
            logger.error(
                "Failed to process issue %s: %s",
                identifier,
                title,
                exc_info=True,
            )
            # Continue to next issue -- don't let one failure block others

    # --- Comment-triggered resumes ---
    # Check for new developer comments on issues with active/completed sessions
    try:
        check_comment_triggers(api_key)
    except Exception:
        logger.error("Comment trigger check failed", exc_info=True)


if __name__ == "__main__":
    main()
