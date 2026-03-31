# backend/core/api/app/tasks/linear_issue_task.py
"""
Celery task for auto-creating Linear issues when users report bugs.

When a user submits an issue report through the frontend, this task creates a
corresponding Linear issue in the OpenMates team. The Linear issue identifier
(e.g., "OPE-78") is stored back in the Directus record so admins can cross-reference
between the internal issue database and the Linear project board.

Architecture:
- Dispatched fire-and-forget from the issue report API route (alongside the email task)
- Uses Linear's GraphQL API directly (no dependency on scripts/_linear_client.py)
- Stores the Linear issue identifier back in Directus for cross-reference
- Never blocks the user-facing response — failures are logged but not retried
"""

import logging
import asyncio
import os
from typing import Optional

import httpx

from backend.core.api.app.tasks.celery_config import app
from backend.core.api.app.tasks.base_task import BaseServiceTask

logger = logging.getLogger(__name__)

# ── Linear API Constants ──────────────────────────────────────────────────────

LINEAR_API_URL = "https://api.linear.app/graphql"
LINEAR_TEAM_ID = "8fcbd114-657d-4a68-8c27-f18c9bf7ce7b"
LINEAR_REQUEST_TIMEOUT = 15  # seconds

# Linear label name to apply to user-reported issues.
# Looked up by name at runtime via the Linear GraphQL API so it survives
# workspace migrations without hardcoded UUIDs.
LINEAR_BUG_LABEL_NAME = "Bug"

# Linear state name for newly created issue reports.
# "Todo" keeps them visible in the backlog (not "Triage" which can be overlooked).
LINEAR_ISSUE_STATE_NAME = "Todo"


def _get_linear_api_key() -> Optional[str]:
    """Read LINEAR_API_KEY from environment (injected via .env → docker-compose)."""
    return os.environ.get("LINEAR_API_KEY")


async def _find_label_id_by_name(
    client: httpx.AsyncClient,
    api_key: str,
    label_name: str,
) -> Optional[str]:
    """
    Look up a Linear label UUID by its display name within the team.

    Args:
        client: Active httpx client
        api_key: Linear API key
        label_name: Label name to search for (case-insensitive match)

    Returns:
        Label UUID if found, None otherwise.
    """
    query = """
    query TeamLabels($teamId: String!) {
        team(id: $teamId) {
            labels {
                nodes {
                    id
                    name
                }
            }
        }
    }
    """
    try:
        resp = await client.post(
            LINEAR_API_URL,
            json={"query": query, "variables": {"teamId": LINEAR_TEAM_ID}},
            headers={"Authorization": api_key, "Content-Type": "application/json"},
        )
        resp.raise_for_status()
        result = resp.json()
        nodes = (
            result.get("data", {})
            .get("team", {})
            .get("labels", {})
            .get("nodes", [])
        )
        for node in nodes:
            if node.get("name", "").lower() == label_name.lower():
                return node["id"]
    except Exception as e:
        logger.warning(f"Failed to look up Linear label '{label_name}': {e}")
    return None


async def _find_state_id_by_name(
    client: httpx.AsyncClient,
    api_key: str,
    state_name: str,
) -> Optional[str]:
    """
    Look up a Linear workflow state UUID by its display name within the team.

    Args:
        client: Active httpx client
        api_key: Linear API key
        state_name: State name to search for (case-insensitive match)

    Returns:
        State UUID if found, None otherwise.
    """
    query = """
    query TeamStates($teamId: String!) {
        team(id: $teamId) {
            states {
                nodes {
                    id
                    name
                }
            }
        }
    }
    """
    try:
        resp = await client.post(
            LINEAR_API_URL,
            json={"query": query, "variables": {"teamId": LINEAR_TEAM_ID}},
            headers={"Authorization": api_key, "Content-Type": "application/json"},
        )
        resp.raise_for_status()
        result = resp.json()
        nodes = (
            result.get("data", {})
            .get("team", {})
            .get("states", {})
            .get("nodes", [])
        )
        for node in nodes:
            if node.get("name", "").lower() == state_name.lower():
                return node["id"]
    except Exception as e:
        logger.warning(f"Failed to look up Linear state '{state_name}': {e}")
    return None


async def _create_linear_issue(
    *,
    title: str,
    description: str,
    priority: int = 2,
) -> Optional[dict]:
    """
    Create a Linear issue via GraphQL API.

    Args:
        title: Issue title (max 200 chars, truncated if longer)
        description: Markdown description for the Linear issue
        priority: Linear priority (0=none, 1=urgent, 2=high, 3=medium, 4=low)

    Returns:
        Dict with id, identifier, url on success, None on failure.
    """
    api_key = _get_linear_api_key()
    if not api_key:
        logger.warning("LINEAR_API_KEY not set — skipping Linear issue creation")
        return None

    title = title[:200]

    mutation = """
    mutation CreateIssue($input: IssueCreateInput!) {
        issueCreate(input: $input) {
            success
            issue {
                id
                identifier
                url
            }
        }
    }
    """

    input_data = {
        "teamId": LINEAR_TEAM_ID,
        "title": title,
        "description": description,
        "priority": priority,
    }

    try:
        async with httpx.AsyncClient(timeout=LINEAR_REQUEST_TIMEOUT) as client:
            # Look up "Bug" label and "Todo" state by name (resilient to workspace changes)
            bug_label_id = await _find_label_id_by_name(client, api_key, LINEAR_BUG_LABEL_NAME)
            if bug_label_id:
                input_data["labelIds"] = [bug_label_id]
            else:
                logger.warning(f"Could not find Linear label '{LINEAR_BUG_LABEL_NAME}' — creating issue without label")

            todo_state_id = await _find_state_id_by_name(client, api_key, LINEAR_ISSUE_STATE_NAME)
            if todo_state_id:
                input_data["stateId"] = todo_state_id
            else:
                logger.warning(f"Could not find Linear state '{LINEAR_ISSUE_STATE_NAME}' — using default state")

            resp = await client.post(
                LINEAR_API_URL,
                json={"query": mutation, "variables": {"input": input_data}},
                headers={
                    "Authorization": api_key,
                    "Content-Type": "application/json",
                },
            )
            resp.raise_for_status()
            result = resp.json()

            if "errors" in result:
                errors = result["errors"]
                msg = errors[0].get("message", str(errors)) if errors else "Unknown"
                logger.error(f"Linear API error creating issue: {msg}")
                return None

            data = result.get("data", {}).get("issueCreate", {})
            if not data.get("success"):
                logger.error("Linear issueCreate returned success=false")
                return None

            issue = data["issue"]
            logger.info(
                f"Created Linear issue {issue['identifier']} with Bug label for user-reported bug: {title[:60]}"
            )
            return {
                "id": issue["id"],
                "identifier": issue["identifier"],
                "url": issue["url"],
            }

    except httpx.HTTPStatusError as e:
        logger.error(f"Linear API HTTP {e.response.status_code}: {e}")
        return None
    except Exception as e:
        logger.error(f"Failed to create Linear issue: {e}", exc_info=True)
        return None


@app.task(
    name="app.tasks.linear_issue_task.create_linear_issue_for_report",
    base=BaseServiceTask,
    bind=True,
)
def create_linear_issue_for_report(
    self: BaseServiceTask,
    issue_id: Optional[str],
    issue_title: str,
    issue_description: Optional[str] = None,
    chat_or_embed_url: Optional[str] = None,
    is_from_admin: bool = False,
    contact_email: Optional[str] = None,
) -> bool:
    """
    Celery task to create a Linear issue when a user reports a bug.

    Creates a Linear issue with the report details and stores the Linear identifier
    (e.g., "OPE-78") back in the Directus issues record for cross-reference.

    Args:
        issue_id: Directus issue record UUID (for updating with Linear identifier)
        issue_title: The user-provided issue title
        issue_description: Optional issue description
        chat_or_embed_url: Optional related chat/embed URL (included in Linear description)
        is_from_admin: Whether the reporter is an admin user
        contact_email: Optional reporter email (included in Linear description for context)

    Returns:
        True if Linear issue was created successfully, False otherwise.
    """
    logger.info(f"Creating Linear issue for report: '{issue_title[:60]}...'")
    try:
        result = asyncio.run(
            _async_create_linear_issue_for_report(
                self,
                issue_id=issue_id,
                issue_title=issue_title,
                issue_description=issue_description,
                chat_or_embed_url=chat_or_embed_url,
                is_from_admin=is_from_admin,
                contact_email=contact_email,
            )
        )
        if result:
            logger.info(f"Linear issue created for report: '{issue_title[:60]}...'")
        else:
            logger.warning(f"Failed to create Linear issue for report: '{issue_title[:60]}...'")
        return result
    except Exception as e:
        logger.error(f"Linear issue task failed for '{issue_title[:60]}...': {e}", exc_info=True)
        return False


async def _async_create_linear_issue_for_report(
    task: BaseServiceTask,
    *,
    issue_id: Optional[str],
    issue_title: str,
    issue_description: Optional[str],
    chat_or_embed_url: Optional[str],
    is_from_admin: bool,
    contact_email: Optional[str],
) -> bool:
    """
    Async implementation: build the Linear issue description, create the issue,
    and store the identifier back in Directus.
    """
    try:
        # Build a Markdown description for the Linear issue
        parts = ["**User-reported issue**"]

        if is_from_admin:
            parts.append("*Reported by: admin*")
        elif contact_email:
            parts.append(f"*Reported by: {contact_email}*")
        else:
            parts.append("*Reported by: anonymous user*")

        if issue_description:
            parts.append(f"\n---\n\n{issue_description}")

        if chat_or_embed_url:
            parts.append(f"\n**Related URL:** {chat_or_embed_url}")

        if issue_id:
            parts.append(f"\n**Internal issue ID:** `{issue_id}`")
            parts.append(f"Inspect: `docker exec api python /app/backend/scripts/debug.py issue {issue_id}`")

        description = "\n".join(parts)

        # Create the Linear issue
        # Priority: 2 (high) for admin reports, 3 (medium) for user reports
        priority = 2 if is_from_admin else 3

        linear_result = await _create_linear_issue(
            title=f"Bug report: {issue_title}",
            description=description,
            priority=priority,
        )

        if not linear_result:
            return False

        # Store Linear identifier back in Directus if we have an issue_id
        if issue_id and linear_result.get("identifier"):
            try:
                await task.initialize_services()
                await task.directus_service.update_item(
                    "issues",
                    issue_id,
                    {"linear_issue_identifier": linear_result["identifier"]},
                )
                logger.info(
                    f"Stored Linear identifier {linear_result['identifier']} "
                    f"in Directus issue {issue_id}"
                )
            except Exception as e:
                # Non-fatal: the Linear issue was created, we just couldn't store the reference
                logger.error(
                    f"Failed to store Linear identifier in Directus for issue {issue_id}: {e}",
                    exc_info=True,
                )
            finally:
                try:
                    await task.cleanup_services()
                except Exception as cleanup_err:
                    logger.warning(f"Cleanup error: {cleanup_err}", exc_info=True)

        return True

    except Exception as e:
        logger.error(f"Error in _async_create_linear_issue_for_report: {e}", exc_info=True)
        return False
