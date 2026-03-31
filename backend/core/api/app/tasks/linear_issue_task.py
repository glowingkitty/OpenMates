# backend/core/api/app/tasks/linear_issue_task.py
"""
Celery task for auto-creating Linear issues when users report bugs.

When a user submits an issue report through the frontend, this task creates a
corresponding Linear issue in the OpenMates team. Before issue creation, the
task runs two security layers:

1. Content-based auto-labeling (keyword analysis for Bug, Performance, Security, etc.)
2. LLM-based prompt injection detection via the content sanitization pipeline

If prompt injection is detected:
- Score >= 7.0: Issue is still created but flagged with 'suspicious-report' label
- Score 5.0-6.9: Detected injection strings are stripped, 'needs-review' label added
- Score < 5.0: Normal processing

The Linear issue identifier (e.g., "OPE-78") is stored back in the Directus record
so admins can cross-reference between the internal issue database and the Linear board.

Architecture:
- Dispatched fire-and-forget from the issue report API route (alongside the email task)
- Uses Linear's GraphQL API directly (no dependency on scripts/_linear_client.py)
- Stores the Linear issue identifier back in Directus for cross-reference
- Never blocks the user-facing response — failures are logged but not retried
"""

import logging
import asyncio
import os
import re
from typing import Optional, List, Dict, Any

import httpx

from backend.core.api.app.tasks.celery_config import app
from backend.core.api.app.tasks.base_task import BaseServiceTask

logger = logging.getLogger(__name__)

# ── Linear API Constants ──────────────────────────────────────────────────────

LINEAR_API_URL = "https://api.linear.app/graphql"
LINEAR_TEAM_ID = "8fcbd114-657d-4a68-8c27-f18c9bf7ce7b"
LINEAR_REQUEST_TIMEOUT = 15  # seconds

# Linear state name for newly created issue reports.
# "Todo" keeps them visible in the backlog (not "Triage" which can be overlooked).
LINEAR_ISSUE_STATE_NAME = "Todo"

# ── Auto-Labeling Configuration ──────────────────────────────────────────────
# Maps Linear label names to keyword patterns that trigger them.
# Patterns are matched case-insensitively against the combined title + description.
# Order matters: first match wins for mutually exclusive labels (Bug vs Feature).
AUTO_LABEL_RULES: List[Dict[str, Any]] = [
    {
        "label": "Security",
        "patterns": [
            r"\bsecurit(?:y|ies)\b", r"\bvulnerabilit(?:y|ies)\b", r"\bexploit\b",
            r"\binjection\b", r"\bxss\b", r"\bcsrf\b", r"\bauth(?:entication|orization)\b.*(?:bypass|fail|broke)",
            r"\bdata\s*leak\b", r"\bprivacy\b",
        ],
    },
    {
        "label": "Encryption",
        "patterns": [
            r"\bencrypt(?:ion|ed)?\b", r"\bdecrypt(?:ion|ed)?\b", r"\bkey\s*(?:management|mismatch|missing)\b",
            r"\be2e(?:e)?\b", r"\bend.to.end\b",
        ],
    },
    {
        "label": "Performance",
        "patterns": [
            r"\bslow\b", r"\blag(?:s|gy|ging)?\b", r"\blaten(?:cy|t)\b", r"\bloading\b",
            r"\btimeout\b", r"\bfreez(?:e|es|ing)\b", r"\bhang(?:s|ing)?\b",
            r"\bmemory\s*(?:leak|usage)\b", r"\bcpu\s*(?:usage|spike)\b",
        ],
    },
    {
        "label": "Bug",
        "patterns": [
            r"\berror\b", r"\bcrash(?:es|ed|ing)?\b", r"\bbroken\b",
            r"\bdoesn'?t\s*work\b", r"\bnot\s*working\b", r"\bfail(?:s|ed|ing|ure)?\b",
            r"\bbug\b", r"\bglitch\b", r"\bwrong\b", r"\bmissing\b",
            r"\bunexpected\b", r"\bregression\b",
        ],
    },
    {
        "label": "Feature",
        "patterns": [
            r"\bfeature\s*request\b", r"\bsuggestion\b", r"\bwould\s*be\s*nice\b",
            r"\bwish\b", r"\bplease\s*add\b", r"\bcan\s*you\s*add\b",
        ],
    },
    {
        "label": "Improvement",
        "patterns": [
            r"\bimprove(?:ment)?\b", r"\benhance(?:ment)?\b", r"\bux\b",
            r"\bui\b", r"\bconfusing\b", r"\bunintuitive\b", r"\bhard\s*to\s*use\b",
            r"\blayout\b", r"\bdesign\b",
        ],
    },
]

# Prompt injection detection thresholds (mirrors prompt_injection_detection.yml)
INJECTION_BLOCK_THRESHOLD = 7.0
INJECTION_REVIEW_THRESHOLD = 5.0


def _get_linear_api_key() -> Optional[str]:
    """Read LINEAR_API_KEY from environment (injected via .env → docker-compose)."""
    return os.environ.get("LINEAR_API_KEY")


def _auto_detect_labels(title: str, description: Optional[str]) -> List[str]:
    """
    Analyse issue title and description to automatically suggest Linear labels.

    Scans the combined text against keyword patterns and returns matching label
    names. Falls back to ["Bug"] if no pattern matches (most reports are bugs).

    Args:
        title: Issue title
        description: Optional issue description

    Returns:
        List of label name strings to apply.
    """
    combined = f"{title} {description or ''}".lower()
    matched_labels: List[str] = []

    for rule in AUTO_LABEL_RULES:
        for pattern in rule["patterns"]:
            if re.search(pattern, combined, re.IGNORECASE):
                matched_labels.append(rule["label"])
                break  # One match per rule is enough

    # Default to "Bug" if no category matched — most user reports are bugs
    if not matched_labels:
        matched_labels.append("Bug")

    return matched_labels


async def _run_prompt_injection_detection(
    title: str,
    description: Optional[str],
    secrets_manager: Any,
    cache_service: Any,
) -> Dict[str, Any]:
    """
    Run LLM-based prompt injection detection on issue title + description.

    Uses the same sanitize_external_content() pipeline used for app skill outputs,
    ensuring consistent security coverage.

    Args:
        title: Issue title text
        description: Optional description text
        secrets_manager: SecretsManager instance for LLM API calls
        cache_service: CacheService instance for config/model caching

    Returns:
        Dict with keys:
        - score: float (0.0-10.0), highest injection score detected
        - flagged: bool, True if score >= review threshold
        - blocked: bool, True if score >= block threshold
        - sanitized_title: str, title after injection string removal
        - sanitized_description: Optional[str], description after injection string removal
        - error: Optional[str], error message if detection failed
    """
    result = {
        "score": 0.0,
        "flagged": False,
        "blocked": False,
        "sanitized_title": title,
        "sanitized_description": description,
        "error": None,
    }

    try:
        from backend.apps.ai.processing.content_sanitization import sanitize_external_content
    except ImportError as e:
        logger.warning(f"Cannot import content_sanitization for issue report scan: {e}")
        result["error"] = str(e)
        return result

    # Combine title + description for a single detection pass
    combined_text = title
    if description:
        combined_text = f"{title}\n\n{description}"

    try:
        sanitized = await sanitize_external_content(
            content=combined_text,
            content_type="text",
            task_id="issue_report_injection_scan",
            secrets_manager=secrets_manager,
            cache_service=cache_service,
        )

        # Determine score based on sanitization outcome
        if not sanitized:
            # Content was fully blocked — score >= block threshold
            result["score"] = INJECTION_BLOCK_THRESHOLD
            result["blocked"] = True
            result["flagged"] = True
            logger.warning(
                "[issue_report_injection_scan] Issue report content BLOCKED by injection detection"
            )
        elif sanitized != combined_text:
            # Content was modified — injection strings were stripped
            result["score"] = INJECTION_REVIEW_THRESHOLD
            result["flagged"] = True

            # Split sanitized text back into title and description
            if description:
                parts = sanitized.split("\n\n", 1)
                result["sanitized_title"] = parts[0] if parts else sanitized
                result["sanitized_description"] = parts[1] if len(parts) > 1 else None
            else:
                result["sanitized_title"] = sanitized

            logger.info(
                "[issue_report_injection_scan] Issue report content sanitized — "
                f"injection strings removed (score >= {INJECTION_REVIEW_THRESHOLD})"
            )
        else:
            # Content passed unchanged — safe
            logger.info("[issue_report_injection_scan] Issue report content passed injection scan (clean)")

    except Exception as e:
        # Detection failure should NOT block issue creation — log and continue
        logger.error(
            f"[issue_report_injection_scan] Prompt injection detection failed: {e}",
            exc_info=True,
        )
        result["error"] = str(e)

    return result


async def _find_label_ids_by_names(
    client: httpx.AsyncClient,
    api_key: str,
    label_names: List[str],
) -> List[str]:
    """
    Look up Linear label UUIDs by their display names within the team.

    Args:
        client: Active httpx client
        api_key: Linear API key
        label_names: Label names to search for (case-insensitive match)

    Returns:
        List of label UUIDs for names that were found.
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

        # Build a case-insensitive lookup map
        label_map = {node["name"].lower(): node["id"] for node in nodes if "name" in node and "id" in node}

        found_ids = []
        for name in label_names:
            label_id = label_map.get(name.lower())
            if label_id:
                found_ids.append(label_id)
            else:
                logger.warning(f"Linear label '{name}' not found in team — skipping")

        return found_ids

    except Exception as e:
        logger.warning(f"Failed to look up Linear labels {label_names}: {e}")
        return []


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
    label_names: Optional[List[str]] = None,
) -> Optional[dict]:
    """
    Create a Linear issue via GraphQL API.

    Args:
        title: Issue title (max 200 chars, truncated if longer)
        description: Markdown description for the Linear issue
        priority: Linear priority (0=none, 1=urgent, 2=high, 3=medium, 4=low)
        label_names: List of label names to apply (looked up by name at runtime)

    Returns:
        Dict with id, identifier, url on success, None on failure.
    """
    api_key = _get_linear_api_key()
    if not api_key:
        logger.warning("LINEAR_API_KEY not set — skipping Linear issue creation")
        return None

    title = title[:200]
    if label_names is None:
        label_names = ["Bug"]

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
            # Look up label IDs by name (resilient to workspace changes)
            label_ids = await _find_label_ids_by_names(client, api_key, label_names)
            if label_ids:
                input_data["labelIds"] = label_ids
            else:
                logger.warning(f"Could not resolve any labels from {label_names} — creating issue without labels")

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
                f"Created Linear issue {issue['identifier']} with labels {label_names} "
                f"for user-reported issue: {title[:60]}"
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
    ascii_smuggling_detected: bool = False,
) -> bool:
    """
    Celery task to create a Linear issue when a user reports a bug.

    Runs prompt injection detection and auto-labeling before creating the issue.
    Creates a Linear issue with the report details and stores the Linear identifier
    (e.g., "OPE-78") back in the Directus issues record for cross-reference.

    Args:
        issue_id: Directus issue record UUID (for updating with Linear identifier)
        issue_title: The user-provided issue title (already ASCII-smuggling cleaned)
        issue_description: Optional issue description (already ASCII-smuggling cleaned)
        chat_or_embed_url: Optional related chat/embed URL (included in Linear description)
        is_from_admin: Whether the reporter is an admin user
        contact_email: Optional reporter email (included in Linear description for context)
        ascii_smuggling_detected: Whether ASCII smuggling was detected in the API route

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
                ascii_smuggling_detected=ascii_smuggling_detected,
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
    ascii_smuggling_detected: bool,
) -> bool:
    """
    Async implementation: run prompt injection detection, build the Linear issue
    description with auto-labels, create the issue, and store the identifier
    back in Directus.
    """
    try:
        # ── Step 1: Auto-detect labels from content keywords ─────────────
        label_names = _auto_detect_labels(issue_title, issue_description)
        logger.info(f"Auto-detected labels for issue report: {label_names}")

        # ── Step 2: LLM-based prompt injection detection ─────────────────
        # Initialize services for the LLM call (secrets_manager + cache_service)
        injection_result = {"score": 0.0, "flagged": False, "blocked": False, "error": None}
        effective_title = issue_title
        effective_description = issue_description

        try:
            await task.initialize_services()
            injection_result = await _run_prompt_injection_detection(
                title=issue_title,
                description=issue_description,
                secrets_manager=task.secrets_manager,
                cache_service=task.cache_service,
            )

            if injection_result["blocked"]:
                # Score >= 7.0: High risk — still create issue but flag it
                if "suspicious-report" not in label_names:
                    label_names.append("suspicious-report")
                logger.warning(
                    f"Issue report flagged as suspicious (score >= {INJECTION_BLOCK_THRESHOLD}): "
                    f"'{issue_title[:60]}...'"
                )
            elif injection_result["flagged"]:
                # Score 5.0-6.9: Moderate risk — use sanitized content, add review label
                effective_title = injection_result.get("sanitized_title", issue_title)
                effective_description = injection_result.get("sanitized_description", issue_description)
                if "needs-review" not in label_names:
                    label_names.append("needs-review")
                logger.info(
                    f"Issue report needs review (score >= {INJECTION_REVIEW_THRESHOLD}): "
                    f"'{issue_title[:60]}...'"
                )
        except Exception as e:
            # Detection failure must NOT block issue creation
            logger.error(f"Prompt injection detection failed for issue report: {e}", exc_info=True)
            injection_result["error"] = str(e)

        # If ASCII smuggling was detected in the API route, ensure Security label is present
        if ascii_smuggling_detected and "Security" not in label_names:
            label_names.append("Security")
            logger.info("Added 'Security' label due to ASCII smuggling detection in API route")

        # ── Step 3: Build Linear issue description ───────────────────────
        parts = ["**User-reported issue**"]

        if is_from_admin:
            parts.append("*Reported by: admin*")
        elif contact_email:
            parts.append(f"*Reported by: {contact_email}*")
        else:
            parts.append("*Reported by: anonymous user*")

        if effective_description:
            parts.append(f"\n---\n\n{effective_description}")

        if chat_or_embed_url:
            parts.append(f"\n**Related URL:** {chat_or_embed_url}")

        if issue_id:
            parts.append(f"\n**Internal issue ID:** `{issue_id}`")
            parts.append(f"Inspect: `docker exec api python /app/backend/scripts/debug.py issue {issue_id}`")

        # Add security annotations if injection was detected
        if injection_result["blocked"]:
            parts.append(
                "\n---\n"
                "**⚠ SECURITY: Prompt injection detected (high confidence)**\n"
                "This report was flagged by the automated prompt injection detection system. "
                "The original content may contain malicious instructions. Review carefully before acting on it."
            )
        elif injection_result["flagged"]:
            parts.append(
                "\n---\n"
                "**⚠ SECURITY: Possible prompt injection (moderate confidence)**\n"
                "Detected injection strings were stripped from the description. "
                "Original content had suspicious patterns — review the internal issue record for full details."
            )
        elif injection_result.get("error"):
            parts.append(
                f"\n---\n"
                f"**ℹ Note:** Prompt injection scan could not complete: {injection_result['error'][:200]}\n"
                f"Content was NOT scanned — treat with normal caution."
            )

        if ascii_smuggling_detected:
            parts.append(
                "\n**ℹ ASCII smuggling:** Hidden Unicode characters were detected and removed from the original submission."
            )

        # Add auto-label summary for transparency
        parts.append(f"\n**Auto-labels:** {', '.join(label_names)}")

        description = "\n".join(parts)

        # ── Step 4: Create the Linear issue ──────────────────────────────
        # Priority: 2 (high) for admin reports, 3 (medium) for user reports
        priority = 2 if is_from_admin else 3

        linear_result = await _create_linear_issue(
            title=f"Bug report: {effective_title}",
            description=description,
            priority=priority,
            label_names=label_names,
        )

        if not linear_result:
            return False

        # ── Step 5: Store Linear identifier in Directus ──────────────────
        if issue_id and linear_result.get("identifier"):
            try:
                # Services may already be initialized from the injection detection step
                if not task._directus_service:
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
