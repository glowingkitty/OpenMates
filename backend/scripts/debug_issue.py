#!/usr/bin/env python3
"""
Script to inspect issue report data including metadata, decrypted fields, and the full S3 YAML report.

This script:
1. Takes an issue ID as argument
2. Fetches issue metadata from Directus
3. Decrypts all encrypted fields (email, URL, location, device info)
4. Optionally fetches and decrypts the full YAML report from S3
5. Displays a formatted inspection report

Issue Architecture:
- title/description: stored in cleartext for searchability
- encrypted_contact_email: Vault-encrypted with issue_report_emails key
- encrypted_chat_or_embed_url: Vault-encrypted with issue_report_emails key
- encrypted_estimated_location: Vault-encrypted with issue_report_emails key
- encrypted_device_info: Vault-encrypted with issue_report_emails key
- encrypted_issue_report_yaml_s3_key: Vault-encrypted S3 key pointing to full YAML report

Usage:
    docker exec api python /app/backend/scripts/debug.py issue <issue_id>
    docker exec api python /app/backend/scripts/debug.py issue abc12345-6789-0123-4567-890123456789

    # Fetch issue from production server (required for production-only issues)
    docker exec api python /app/backend/scripts/debug.py issue <issue_id> --production
    docker exec api python /app/backend/scripts/debug.py issue --list --production

Options:
    --no-logs           Skip fetching the full YAML report from S3
    --full-logs         Show all data untruncated: all log lines AND full text fields (description,
                        device info, IndexedDB, etc.). Output can be very long — pipe to a file or
                        use grep to filter. By default only warnings/errors are shown in logs and
                        long fields are truncated to a readable summary.
    --json              Output as JSON instead of formatted text
    --list              List recent issues (most recent first)
    --list-limit N      Number of issues to list (default: 20)
    --search TEXT       Search issues by title/description (used with --list)
    --include-processed Include processed issues in --list results
    --delete            Delete the issue (Directus + S3). Use after confirming the issue is fixed.
    --yes               Skip confirmation when using --delete (required for non-interactive use)
    --production        Fetch data from the production Admin Debug API instead of local Directus
    --dev               Fetch data from the dev Admin Debug API (implies --production)
"""

import asyncio
import argparse
import json
import os
import sys
from datetime import datetime
from typing import Dict, Any, List, Optional

# Add the backend directory to the Python path — must happen before backend imports
sys.path.insert(0, '/app/backend')

from backend.core.api.app.services.directus.directus import DirectusService
from backend.core.api.app.services.cache import CacheService
from backend.core.api.app.utils.encryption import EncryptionService
from backend.core.api.app.utils.secrets_manager import SecretsManager
from backend.core.api.app.services.s3.service import S3UploadService
from backend.core.api.app.services.s3.config import get_bucket_name

# Shared inspection utilities — replaces duplicated helpers
from debug_utils import (
    configure_script_logging,
    format_timestamp,
    truncate_string,
    censor_email,
    get_api_key_from_vault,
    make_prod_api_request,
    PROD_API_URL,
    DEV_API_URL,
)

script_logger = configure_script_logging('debug_issue', extra_suppress=['botocore', 'boto3'])

async def fetch_issue_from_production_api(
    issue_id: str,
    include_logs: bool = True,
    use_dev: bool = False,
) -> Optional[Dict[str, Any]]:
    """Fetch issue data from the production (or dev) Admin Debug API.

    The production API decrypts all Vault-encrypted fields server-side and
    fetches the S3 YAML report, so the response contains plaintext fields
    directly (contact_email, chat_or_embed_url, etc.).

    Args:
        issue_id: The issue ID (UUID format).
        include_logs: Whether to include the full S3 YAML report.
        use_dev: If True, hit the dev API instead of production.

    Returns:
        Parsed JSON response from the API, or None if not found (404).
    """
    api_key = await get_api_key_from_vault()
    base_url = DEV_API_URL if use_dev else PROD_API_URL

    source_label = "dev" if use_dev else "production"
    script_logger.info(
        f"Fetching issue from {source_label} API: "
        f"{base_url}/issues/{issue_id}"
    )

    return await make_prod_api_request(
        f"issues/{issue_id}",
        api_key,
        base_url,
        params={"include_logs": include_logs},
        entity_label=f"Issue {issue_id}",
    )


async def fetch_issues_list_from_production_api(
    limit: int = 50,
    offset: int = 0,
    search: Optional[str] = None,
    include_processed: bool = False,
    use_dev: bool = False,
) -> Optional[Dict[str, Any]]:
    """Fetch issue list from the production (or dev) Admin Debug API.

    Args:
        limit: Maximum number of issues to return.
        offset: Pagination offset.
        search: Optional search text for title/description.
        include_processed: Include processed issues.
        use_dev: If True, hit the dev API instead of production.

    Returns:
        Parsed JSON response with issues list, or None on error.
    """
    api_key = await get_api_key_from_vault()
    base_url = DEV_API_URL if use_dev else PROD_API_URL

    source_label = "dev" if use_dev else "production"
    script_logger.info(f"Listing issues from {source_label} API: {base_url}/issues")

    params: Dict[str, Any] = {
        "limit": limit,
        "offset": offset,
        "include_processed": include_processed,
    }
    if search:
        params["search"] = search

    return await make_prod_api_request(
        "issues",
        api_key,
        base_url,
        params=params,
        entity_label="Issue list",
    )


async def delete_issue_via_production_api(
    issue_id: str,
    use_dev: bool = False,
) -> Optional[Dict[str, Any]]:
    """Delete an issue via the production (or dev) Admin Debug API.

    The production API handles S3 cleanup and Directus deletion server-side.

    Args:
        issue_id: The issue ID to delete.
        use_dev: If True, hit the dev API instead of production.

    Returns:
        Parsed JSON response, or None if not found.
    """
    api_key = await get_api_key_from_vault()
    base_url = DEV_API_URL if use_dev else PROD_API_URL

    source_label = "dev" if use_dev else "production"
    script_logger.info(f"Deleting issue via {source_label} API: {base_url}/issues/{issue_id}")

    return await make_prod_api_request(
        f"issues/{issue_id}",
        api_key,
        base_url,
        method="DELETE",
        entity_label=f"Issue {issue_id}",
    )


def map_production_issue_to_local_format(api_response: Dict[str, Any]) -> Dict[str, Any]:
    """Map the production API IssueDetailResponse to the format expected by format functions.

    The production API returns decrypted fields directly (contact_email,
    chat_or_embed_url, etc.), so we map them to the 'decrypted' dict format
    used by the local code path. The 'issue' dict mirrors Directus fields.

    Args:
        api_response: Parsed JSON from GET /issues/{issue_id}.

    Returns:
        Dict with 'issue' and 'decrypted' keys matching local format.
    """
    # Build a pseudo-Directus issue record from the API response
    issue = {
        "id": api_response.get("id"),
        "title": api_response.get("title", ""),
        "description": api_response.get("description"),
        "timestamp": api_response.get("timestamp", ""),
        "created_at": api_response.get("created_at", ""),
        "updated_at": api_response.get("updated_at", ""),
        "processed": api_response.get("processed", False),
        "is_from_admin": api_response.get("is_from_admin", False),
        "reported_by_user_id": api_response.get("reported_by_user_id"),
        # Mark encrypted fields as present if decrypted values exist
        "encrypted_contact_email": "present" if api_response.get("contact_email") else None,
        "encrypted_chat_or_embed_url": "present" if api_response.get("chat_or_embed_url") else None,
        "encrypted_estimated_location": "present" if api_response.get("estimated_location") else None,
        "encrypted_device_info": "present" if api_response.get("device_info") else None,
        "encrypted_issue_report_yaml_s3_key": "present" if api_response.get("full_report") else None,
        "encrypted_screenshot_s3_key": None,  # Not available via API
    }

    # Decrypted fields are already plaintext in the API response
    decrypted = {
        "contact_email": api_response.get("contact_email"),
        "chat_or_embed_url": api_response.get("chat_or_embed_url"),
        "estimated_location": api_response.get("estimated_location"),
        "device_info": api_response.get("device_info"),
    }

    # Full report is already decrypted and parsed by the API
    full_report = api_response.get("full_report")

    return {
        "issue": issue,
        "decrypted": decrypted,
        "full_report": full_report,
    }


def map_production_issues_list(api_response: Dict[str, Any]) -> tuple:
    """Map the production API IssuesListResponse to the format expected by format_list_output.

    Args:
        api_response: Parsed JSON from GET /issues.

    Returns:
        Tuple of (issues_list, decrypted_list) matching the local format.
    """
    issues = []
    decrypted_list = []

    for item in api_response.get("issues", []):
        issue = {
            "id": item.get("id"),
            "title": item.get("title", ""),
            "description": item.get("description"),
            "timestamp": item.get("timestamp", ""),
            "created_at": item.get("created_at", ""),
            "processed": item.get("processed", False),
            "is_from_admin": item.get("is_from_admin", False),
            "reported_by_user_id": item.get("reported_by_user_id"),
            "encrypted_issue_report_yaml_s3_key": None,  # Not in list response
            "encrypted_screenshot_s3_key": None,
        }
        issues.append(issue)

        decrypted = {
            "contact_email": item.get("contact_email"),
            "chat_or_embed_url": item.get("chat_or_embed_url"),
            "estimated_location": None,
            "device_info": None,
        }
        decrypted_list.append(decrypted)

    return issues, decrypted_list


async def get_issue(directus_service: DirectusService, issue_id: str) -> Optional[Dict[str, Any]]:
    """
    Fetch issue metadata from Directus.

    Args:
        directus_service: DirectusService instance
        issue_id: The issue ID (UUID format)

    Returns:
        Issue metadata dictionary or None if not found
    """
    script_logger.debug(f"Fetching issue metadata for issue_id: {issue_id}")

    params = {
        'filter[id][_eq]': issue_id,
        'fields': '*',
        'limit': 1
    }

    try:
        response = await directus_service.get_items('issues', params=params, no_cache=True)
        if response and isinstance(response, list) and len(response) > 0:
            return response[0]
        else:
            script_logger.warning(f"Issue not found in Directus: {issue_id}")
            return None
    except Exception as e:
        script_logger.error(f"Error fetching issue metadata: {e}")
        return None


async def list_issues(
    directus_service: DirectusService,
    limit: int = 20,
    search: Optional[str] = None,
    include_processed: bool = False
) -> List[Dict[str, Any]]:
    """
    List recent issues from Directus.

    Args:
        directus_service: DirectusService instance
        limit: Maximum number of issues to fetch
        search: Optional search text for title/description
        include_processed: Include processed issues (default: False)

    Returns:
        List of issue dictionaries, sorted by created_at descending
    """
    script_logger.debug(f"Listing issues (limit={limit}, search={search})")

    params: Dict[str, Any] = {
        'fields': '*',
        'sort': '-timestamp',
        'limit': limit
    }

    # Build filters
    filters: List[Dict[str, Any]] = []

    if not include_processed:
        filters.append({
            '_or': [
                {'processed': {'_eq': False}},
                {'processed': {'_null': True}},
            ]
        })

    if search:
        filters.append({
            '_or': [
                {'title': {'_icontains': search}},
                {'description': {'_icontains': search}},
            ]
        })

    if filters:
        if len(filters) == 1:
            params['filter'] = filters[0]
        else:
            params['filter'] = {'_and': filters}

    try:
        response = await directus_service.get_items('issues', params=params, no_cache=True)
        if response and isinstance(response, list):
            return response
        return []
    except Exception as e:
        script_logger.error(f"Error listing issues: {e}")
        return []


async def decrypt_issue_fields(
    encryption_service: EncryptionService,
    issue: Dict[str, Any]
) -> Dict[str, Optional[str]]:
    """
    Decrypt all encrypted fields of an issue.

    Args:
        encryption_service: EncryptionService instance
        issue: Raw issue dictionary from Directus

    Returns:
        Dictionary with decrypted field values (keys without 'encrypted_' prefix)
    """
    decrypted: Dict[str, Optional[str]] = {}

    # Decrypt contact email (uses dedicated email method)
    if issue.get('encrypted_contact_email'):
        try:
            decrypted['contact_email'] = await encryption_service.decrypt_issue_report_email(
                issue['encrypted_contact_email']
            )
        except Exception as e:
            script_logger.warning(f"Failed to decrypt contact_email: {e}")
            decrypted['contact_email'] = f"[DECRYPTION FAILED: {e}]"
    else:
        decrypted['contact_email'] = None

    # Decrypt URL
    if issue.get('encrypted_chat_or_embed_url'):
        try:
            decrypted['chat_or_embed_url'] = await encryption_service.decrypt_issue_report_data(
                issue['encrypted_chat_or_embed_url']
            )
        except Exception as e:
            script_logger.warning(f"Failed to decrypt chat_or_embed_url: {e}")
            decrypted['chat_or_embed_url'] = f"[DECRYPTION FAILED: {e}]"
    else:
        decrypted['chat_or_embed_url'] = None

    # Decrypt estimated location
    if issue.get('encrypted_estimated_location'):
        try:
            decrypted['estimated_location'] = await encryption_service.decrypt_issue_report_data(
                issue['encrypted_estimated_location']
            )
        except Exception as e:
            script_logger.warning(f"Failed to decrypt estimated_location: {e}")
            decrypted['estimated_location'] = f"[DECRYPTION FAILED: {e}]"
    else:
        decrypted['estimated_location'] = None

    # Decrypt device info
    if issue.get('encrypted_device_info'):
        try:
            decrypted['device_info'] = await encryption_service.decrypt_issue_report_data(
                issue['encrypted_device_info']
            )
        except Exception as e:
            script_logger.warning(f"Failed to decrypt device_info: {e}")
            decrypted['device_info'] = f"[DECRYPTION FAILED: {e}]"
    else:
        decrypted['device_info'] = None

    return decrypted


async def get_screenshot_presigned_url(
    encryption_service: EncryptionService,
    s3_service: S3UploadService,
    issue: Dict[str, Any],
    expiration: int = 7 * 24 * 3600,
) -> Optional[str]:
    """
    Decrypt the screenshot S3 key and generate a fresh pre-signed URL.

    The screenshot PNG is stored unencrypted in the issue_logs bucket so it can be
    viewed directly — only the S3 key itself is encrypted in Directus.

    Args:
        encryption_service: EncryptionService instance
        s3_service: S3UploadService instance (initialized)
        issue: Raw issue dictionary from Directus
        expiration: Pre-signed URL expiry in seconds (default: 7 days)

    Returns:
        Pre-signed URL string, or None if no screenshot or on error
    """
    if not issue.get('encrypted_screenshot_s3_key'):
        return None

    try:
        # Decrypt the S3 object key
        screenshot_s3_key = await encryption_service.decrypt_issue_report_data(
            issue['encrypted_screenshot_s3_key']
        )
        if not screenshot_s3_key:
            script_logger.warning("Failed to decrypt screenshot S3 key (returned None)")
            return None

        # Get environment-specific bucket name
        environment = os.getenv('SERVER_ENVIRONMENT', 'development')
        bucket_name = get_bucket_name('issue_logs', environment)

        # Generate a fresh pre-signed URL (7 days by default)
        presigned_url = s3_service.generate_presigned_url(
            bucket_name=bucket_name,
            file_key=screenshot_s3_key,
            expiration=expiration
        )
        script_logger.debug(f"Generated pre-signed URL for screenshot: {screenshot_s3_key}")
        return presigned_url

    except Exception as e:
        script_logger.error(f"Error generating screenshot pre-signed URL: {e}", exc_info=True)
        return None


async def delete_issue(
    directus_service: DirectusService,
    encryption_service: EncryptionService,
    s3_service: Optional[S3UploadService],
    issue_id: str,
    issue: Optional[Dict[str, Any]],
) -> tuple[bool, str]:
    """
    Delete an issue from Directus and S3.

    Deletes both the YAML report (encrypted) and the screenshot PNG (unencrypted)
    from the issue_logs S3 bucket, then removes the Directus record.

    Args:
        directus_service: DirectusService instance (must support admin for delete_item)
        encryption_service: EncryptionService instance
        s3_service: S3UploadService instance (can be None; S3 delete is skipped if unavailable)
        issue_id: The issue ID to delete
        issue: Raw issue dict from Directus (must be loaded already)

    Returns:
        Tuple of (success: bool, message: str)
    """
    if not issue:
        return False, f"Issue not found: {issue_id}"

    deleted_from_s3 = False

    # Delete YAML report from S3 if key exists
    if issue.get("encrypted_issue_report_yaml_s3_key") and s3_service:
        try:
            s3_object_key = await encryption_service.decrypt_issue_report_data(
                issue["encrypted_issue_report_yaml_s3_key"]
            )
            if s3_object_key:
                await s3_service.delete_file(bucket_key="issue_logs", file_key=s3_object_key)
                deleted_from_s3 = True
                script_logger.info(f"Deleted S3 YAML file for issue {issue_id}: {s3_object_key}")
        except Exception as e:
            script_logger.warning(f"Failed to delete S3 YAML file for issue {issue_id}: {e}")

    # Delete screenshot PNG from S3 if key exists
    if issue.get("encrypted_screenshot_s3_key") and s3_service:
        try:
            screenshot_s3_key = await encryption_service.decrypt_issue_report_data(
                issue["encrypted_screenshot_s3_key"]
            )
            if screenshot_s3_key:
                await s3_service.delete_file(bucket_key="issue_logs", file_key=screenshot_s3_key)
                script_logger.info(f"Deleted S3 screenshot for issue {issue_id}: {screenshot_s3_key}")
        except Exception as e:
            script_logger.warning(f"Failed to delete S3 screenshot for issue {issue_id}: {e}")

    # Delete from Directus (admin required)
    try:
        success = await directus_service.delete_item("issues", issue_id, admin_required=True)
        if not success:
            return False, "Failed to delete issue from database"
    except Exception as e:
        script_logger.error(f"Error deleting issue from Directus: {e}", exc_info=True)
        return False, str(e)

    msg = f"Issue {issue_id} deleted successfully"
    if deleted_from_s3:
        msg += " (Directus + S3)"
    else:
        msg += " (Directus only)"
    return True, msg


async def fetch_s3_report(
    encryption_service: EncryptionService,
    s3_service: S3UploadService,
    issue: Dict[str, Any]
) -> Optional[Dict[str, Any]]:
    """
    Fetch and decrypt the full YAML report from S3.

    The flow is:
    1. Decrypt the S3 object key from the issue record
    2. Download the encrypted YAML from S3
    3. Decrypt the YAML content
    4. Parse the YAML into a dictionary

    Args:
        encryption_service: EncryptionService instance
        s3_service: S3UploadService instance (initialized)
        issue: Raw issue dictionary from Directus

    Returns:
        Parsed YAML report dictionary, or None if unavailable/failed
    """
    if not issue.get('encrypted_issue_report_yaml_s3_key'):
        script_logger.debug("No S3 key found for this issue")
        return None

    try:
        import yaml

        # Step 1: Decrypt the S3 object key
        s3_object_key = await encryption_service.decrypt_issue_report_data(
            issue['encrypted_issue_report_yaml_s3_key']
        )

        if not s3_object_key:
            script_logger.warning("Failed to decrypt S3 object key (returned None)")
            return None

        script_logger.debug(f"Decrypted S3 key: {s3_object_key}")

        # Step 2: Get the bucket name for current environment
        environment = os.getenv('SERVER_ENVIRONMENT', 'development')
        bucket_name = get_bucket_name('issue_logs', environment)

        # Step 3: Download encrypted YAML from S3
        encrypted_yaml_bytes = await s3_service.get_file(
            bucket_name=bucket_name,
            object_key=s3_object_key
        )

        if not encrypted_yaml_bytes:
            script_logger.warning(f"S3 file not found or empty: bucket={bucket_name}, key={s3_object_key}")
            return None

        script_logger.debug(f"Downloaded {len(encrypted_yaml_bytes)} bytes from S3")

        # Step 4: Decrypt the YAML content
        encrypted_yaml_str = encrypted_yaml_bytes.decode('utf-8')
        decrypted_yaml = await encryption_service.decrypt_issue_report_data(encrypted_yaml_str)

        if not decrypted_yaml:
            script_logger.warning("Failed to decrypt YAML content from S3")
            return None

        # Step 5: Parse YAML
        report = yaml.safe_load(decrypted_yaml)
        script_logger.debug("Successfully parsed YAML report from S3")
        return report

    except Exception as e:
        script_logger.error(f"Error fetching S3 report: {e}", exc_info=True)
        return None


def filter_logs_to_errors(
    log_text: str,
    context_lines: int = 3
) -> tuple[list[str], int, int]:
    """
    Filter log lines to only show WARNING/ERROR/CRITICAL entries with surrounding context.

    Scans all lines for log-level keywords and includes `context_lines` lines before and
    after each match. Overlapping context windows are merged.

    Args:
        log_text: Raw log text (newline-separated)
        context_lines: Number of lines to show before and after each match (default: 3)

    Returns:
        Tuple of (filtered_lines, total_line_count, match_count)
    """
    import re

    all_lines = log_text.split('\n')
    total = len(all_lines)

    # Regex patterns that match actual log-level indicators, not incidental mentions.
    # Matches structured JSON logs like: "level": "ERROR"
    # Matches plain-text logs like: [ERROR], ERROR:, ] ERROR , WARN  [, WARNING
    # Matches postgres logs like: ERROR:  duplicate key
    # Avoids false positives like "0 errors", "error_message": null, etc.
    error_regexes = [
        re.compile(r'"level"\s*:\s*"(ERROR|WARNING|CRITICAL)"'),  # JSON structured logs
        re.compile(r'\]\s+(ERROR|WARN|WARNING|CRITICAL)\s+\['),   # Console: ] WARN  [component]
        re.compile(r'\b(ERROR|WARNING|CRITICAL):\s'),             # Postgres/plain: ERROR:  msg
        re.compile(r'\[(ERROR|WARNING|CRITICAL)\]'),              # Bracketed: [ERROR]
    ]

    # Find indices of lines that contain error-level keywords
    match_indices: set[int] = set()
    for idx, line in enumerate(all_lines):
        for regex in error_regexes:
            if regex.search(line):
                match_indices.add(idx)
                break

    if not match_indices:
        return [], total, 0

    # Build set of all indices to include (matches + context)
    include_indices: set[int] = set()
    for idx in match_indices:
        start = max(0, idx - context_lines)
        end = min(total, idx + context_lines + 1)
        for i in range(start, end):
            include_indices.add(i)

    # Build output with "..." gap markers between non-contiguous ranges
    sorted_indices = sorted(include_indices)
    filtered: list[str] = []
    prev_idx = -2  # Initialize to ensure first gap is not printed

    for idx in sorted_indices:
        if idx > prev_idx + 1:
            # There's a gap - add separator showing how many lines were skipped
            skipped = idx - prev_idx - 1
            if prev_idx >= 0:
                filtered.append(f"    ... ({skipped} line(s) skipped) ...")
        line = all_lines[idx]
        # Highlight the actual error lines with a marker
        if idx in match_indices:
            filtered.append(f"  >>> {line}")
        else:
            filtered.append(f"      {line}")
        prev_idx = idx

    return filtered, total, len(match_indices)


def format_list_output(
    issues: List[Dict[str, Any]],
    decrypted_issues: List[Dict[str, Optional[str]]]
) -> str:
    """
    Format the issue list as human-readable text.

    Args:
        issues: Raw issue dictionaries from Directus
        decrypted_issues: List of decrypted field dictionaries (parallel to issues)

    Returns:
        Formatted string for display
    """
    lines = []

    lines.append("")
    lines.append("=" * 100)
    lines.append("ISSUE REPORTS LIST")
    lines.append("=" * 100)
    lines.append(f"Total: {len(issues)} issue(s)")
    lines.append(f"Generated at: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
    lines.append("=" * 100)

    if not issues:
        lines.append("")
        lines.append("  No issues found.")
    else:
        for i, (issue, decrypted) in enumerate(zip(issues, decrypted_issues), 1):
            issue_id = issue.get('id', 'N/A')
            title = issue.get('title', 'N/A')
            processed = issue.get('processed', False) or False
            created_at = format_timestamp(issue.get('created_at'))
            timestamp = format_timestamp(issue.get('timestamp'))
            email = censor_email(decrypted.get('contact_email')) or 'N/A'

            # Status indicator
            status_emoji = "✅" if processed else "🔴"
            
            # Admin indicator
            is_from_admin = issue.get('is_from_admin', False) or False
            admin_indicator = " 👑" if is_from_admin else ""

            lines.append("")
            lines.append(f"  {i:3}. {status_emoji} [{issue_id[:8]}...]{admin_indicator}  {created_at}")
            lines.append(f"       Title:     {truncate_string(title, 70)}")
            lines.append(f"       Email:     {truncate_string(email, 50)}")
            lines.append(f"       Reported:  {timestamp}")
            lines.append(f"       Processed: {processed}")
            if is_from_admin:
                lines.append("       From:      Admin User")

            # Show if S3 report exists
            has_s3 = "✓" if issue.get('encrypted_issue_report_yaml_s3_key') else "✗"
            lines.append(f"       S3 Report: {has_s3}")

            # Show if screenshot exists
            has_screenshot = "✓" if issue.get('encrypted_screenshot_s3_key') else "✗"
            lines.append(f"       Screenshot: {has_screenshot}")

    lines.append("")
    lines.append("=" * 100)
    lines.append("")

    return "\n".join(lines)


def format_detail_output(
    issue_id: str,
    issue: Optional[Dict[str, Any]],
    decrypted: Dict[str, Optional[str]],
    s3_report: Optional[Dict[str, Any]],
    full_logs: bool = False,
    screenshot_presigned_url: Optional[str] = None
) -> str:
    """
    Format the issue inspection results as human-readable text.

    By default, log sections (console logs and docker compose logs) are filtered to show
    only WARNING/ERROR/CRITICAL lines with 3 lines of surrounding context, and long text
    fields (description, device info, IndexedDB) are truncated for readability.

    Use full_logs=True (--full-logs flag) to:
    - Show all log lines unfiltered
    - Show all text fields untruncated
    Output can be very long — pipe to a file or use grep to filter.

    Args:
        issue_id: The issue ID
        issue: Raw issue metadata from Directus
        decrypted: Dictionary of decrypted field values
        s3_report: Parsed YAML report from S3 (or None)
        full_logs: If True, show all data untruncated; if False, show summary with truncation

    Returns:
        Formatted string for display
    """
    lines = []

    # Header
    lines.append("")
    lines.append("=" * 100)
    lines.append("ISSUE INSPECTION REPORT")
    lines.append("=" * 100)
    lines.append(f"Issue ID: {issue_id}")
    lines.append(f"Generated at: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
    lines.append("=" * 100)

    # Mode banner
    if full_logs:
        lines.append("")
        lines.append(
            "  ⚠  --full-logs enabled: full untruncated output follows "
            "(may be very long — pipe to a file or use grep to filter)"
        )
    else:
        lines.append("")
        lines.append(
            "  ℹ  Summary mode: some fields are truncated and logs are filtered to errors/warnings only."
        )
        lines.append(
            "     Use --full-logs for complete untruncated output "
            "(warning: can be very long — consider piping to a file or using grep)."
        )

    # ===================== ISSUE METADATA =====================
    lines.append("")
    lines.append("-" * 100)
    lines.append("ISSUE METADATA (from Directus)")
    lines.append("-" * 100)

    if not issue:
        lines.append("  ❌ Issue NOT FOUND in Directus")
    else:
        # Core metadata (cleartext fields)
        lines.append(f"  Title:             {issue.get('title', 'N/A')}")
        desc_raw = issue.get('description', 'N/A') or 'N/A'
        if full_logs:
            lines.append(f"  Description:       {desc_raw}")
        else:
            lines.append(f"  Description:       {truncate_string(desc_raw, 200)}")
        lines.append("")
        lines.append(f"  Timestamp:         {format_timestamp(issue.get('timestamp'))}")
        lines.append(f"  Created At:        {format_timestamp(issue.get('created_at'))}")
        lines.append(f"  Updated At:        {format_timestamp(issue.get('updated_at'))}")
        lines.append(f"  Processed:         {issue.get('processed', False) or False}")
        lines.append(f"  From Admin:        {issue.get('is_from_admin', False) or False}")
        if issue.get('reported_by_user_id'):
            lines.append(f"  Reporter User ID:  {issue.get('reported_by_user_id')}")
        else:
            lines.append("  Reporter User ID:  (unauthenticated)")
        lines.append("")

        # Encrypted fields presence check
        encrypted_fields = [
            ('encrypted_contact_email', 'Contact Email'),
            ('encrypted_chat_or_embed_url', 'Chat/Embed URL'),
            ('encrypted_estimated_location', 'Estimated Location'),
            ('encrypted_device_info', 'Device Info'),
            ('encrypted_issue_report_yaml_s3_key', 'S3 Report Key'),
            ('encrypted_screenshot_s3_key', 'Screenshot S3 Key'),
        ]

        lines.append("  Encrypted Fields Present:")
        for field_key, field_name in encrypted_fields:
            value = issue.get(field_key)
            has_value = "✓" if value else "✗"
            size_info = f" ({len(value)} chars)" if value else ""
            lines.append(f"    {has_value} {field_name}{size_info}")

    # ===================== DECRYPTED FIELDS =====================
    lines.append("")
    lines.append("-" * 100)
    lines.append("DECRYPTED FIELDS")
    lines.append("-" * 100)

    if not issue:
        lines.append("  (skipped - issue not found)")
    else:
        # Contact email (censored for privacy)
        email = censor_email(decrypted.get('contact_email'))
        if email:
            lines.append(f"  📧 Contact Email:      {email}")
        else:
            lines.append("  📧 Contact Email:      N/A (not provided)")

        # Chat or embed URL
        url = decrypted.get('chat_or_embed_url')
        if url:
            lines.append(f"  🔗 Chat/Embed URL:     {url}")
        else:
            lines.append("  🔗 Chat/Embed URL:     N/A (not provided)")

        # Estimated location
        location = decrypted.get('estimated_location')
        if location:
            lines.append(f"  📍 Estimated Location: {location}")
        else:
            lines.append("  📍 Estimated Location: N/A (not available)")

        # Device info
        device_info = decrypted.get('device_info')
        if device_info:
            if full_logs:
                lines.append(f"  💻 Device Info:        {device_info}")
            else:
                lines.append(f"  💻 Device Info:        {truncate_string(device_info, 200)}")
        else:
            lines.append("  💻 Device Info:        N/A (not provided)")

        # Screenshot — display a fresh pre-signed URL so Claude/admin can view the image directly.
        # The URL is generated by the caller (main()) and passed in as screenshot_presigned_url.
        # It expires in 7 days.
        if screenshot_presigned_url:
            lines.append("")
            lines.append("  🖼  SCREENSHOT (pre-signed URL, valid 7 days from now):")
            lines.append(f"      {screenshot_presigned_url}")
        elif issue.get('encrypted_screenshot_s3_key'):
            lines.append("  🖼  SCREENSHOT:         S3 key exists but pre-signed URL generation failed")
        else:
            lines.append("  🖼  SCREENSHOT:         N/A (not attached)")

    # ===================== FULL DESCRIPTION =====================
    # In summary mode: show full description in its own section if it was truncated above.
    # In full-logs mode: already shown in full inline above, skip this section.
    if not full_logs and issue and issue.get('description') and len(issue.get('description', '')) > 200:
        lines.append("")
        lines.append("-" * 100)
        lines.append("FULL DESCRIPTION")
        lines.append("-" * 100)
        # Indent each line of the description
        for desc_line in issue['description'].split('\n'):
            lines.append(f"  {desc_line}")

    # ===================== S3 YAML REPORT =====================
    lines.append("")
    lines.append("-" * 100)
    lines.append("S3 YAML REPORT")
    lines.append("-" * 100)

    if s3_report is None:
        if issue and issue.get('encrypted_issue_report_yaml_s3_key'):
            lines.append("  ❌ Failed to fetch or decrypt S3 report (key exists but retrieval failed)")
        elif issue:
            lines.append("  ℹ️  No S3 report available (issue may not have been fully processed)")
        else:
            lines.append("  (skipped - issue not found)")
    else:
        # Parse the YAML report structure
        report = s3_report.get('issue_report', s3_report)

        # Metadata section
        metadata = report.get('metadata', {})
        if metadata:
            lines.append("")
            lines.append("  REPORT METADATA:")
            lines.append(f"    Issue ID:         {metadata.get('issue_id', 'N/A')}")
            lines.append(f"    Generated At:     {metadata.get('generated_at', 'N/A')}")
            lines.append(f"    Report Timestamp: {metadata.get('report_timestamp', 'N/A')}")
            lines.append(f"    Title:            {metadata.get('title', 'N/A')}")
            if metadata.get('contact_email'):
                lines.append(f"    Contact Email:    {censor_email(metadata.get('contact_email'))}")
            if metadata.get('estimated_location'):
                lines.append(f"    Est. Location:    {metadata.get('estimated_location')}")

        # Technical details section
        tech_details = report.get('technical_details', {})
        if tech_details:
            lines.append("")
            lines.append("  TECHNICAL DETAILS:")
            if tech_details.get('chat_or_embed_url'):
                lines.append(f"    URL:              {tech_details.get('chat_or_embed_url')}")
            if tech_details.get('device_info'):
                device_info_str = str(tech_details.get('device_info'))
                if full_logs:
                    lines.append(f"    Device Info:      {device_info_str}")
                else:
                    lines.append(f"    Device Info:      {truncate_string(device_info_str, 200)}")

        # Console logs section
        logs = report.get('logs', {})
        if logs:
            console_logs = logs.get('console_logs')
            docker_logs = logs.get('docker_compose_logs')

            if console_logs:
                lines.append("")
                console_text = str(console_logs)

                if full_logs:
                    lines.append("  CONSOLE LOGS (client-side) [FULL]:")
                    lines.append("  " + "-" * 60)
                    for log_line in console_text.split('\n'):
                        lines.append(f"    {log_line}")
                else:
                    filtered, total, matches = filter_logs_to_errors(console_text)
                    lines.append(
                        f"  CONSOLE LOGS (client-side) "
                        f"[{matches} warning(s)/error(s) of {total} lines, use --full-logs to show all]:"
                    )
                    lines.append("  " + "-" * 60)
                    if filtered:
                        lines.extend(filtered)
                    else:
                        lines.append("    ✅ No warnings or errors found in console logs.")

            if docker_logs:
                lines.append("")

                if full_logs:
                    lines.append("  DOCKER COMPOSE LOGS (server-side) [FULL]:")
                    lines.append("  " + "-" * 60)
                    if isinstance(docker_logs, dict):
                        for service_name, service_logs in docker_logs.items():
                            lines.append(f"    [{service_name}]:")
                            if service_logs:
                                for log_line in str(service_logs).split('\n'):
                                    lines.append(f"      {log_line}")
                            else:
                                lines.append("      (no logs)")
                    else:
                        for log_line in str(docker_logs).split('\n'):
                            lines.append(f"    {log_line}")
                else:
                    # Filter docker logs to errors/warnings with context
                    # Combine all docker logs into a single text block for filtering
                    combined_docker_text = ""
                    if isinstance(docker_logs, dict):
                        for service_name, service_logs in docker_logs.items():
                            if service_logs:
                                combined_docker_text += str(service_logs) + "\n"
                    else:
                        combined_docker_text = str(docker_logs)

                    filtered, total, matches = filter_logs_to_errors(combined_docker_text)
                    lines.append(
                        f"  DOCKER COMPOSE LOGS (server-side) "
                        f"[{matches} warning(s)/error(s) of {total} lines, use --full-logs to show all]:"
                    )
                    lines.append("  " + "-" * 60)
                    if filtered:
                        lines.extend(filtered)
                    else:
                        lines.append("    ✅ No warnings or errors found in docker logs.")

        # IndexedDB inspection section
        indexeddb = report.get('indexeddb_inspection')
        if indexeddb:
            lines.append("")
            lines.append("  INDEXEDDB INSPECTION:")
            lines.append("  " + "-" * 60)
            if isinstance(indexeddb, dict):
                for key, value in indexeddb.items():
                    value_str = str(value)
                    if full_logs:
                        lines.append(f"    {key}: {value_str}")
                    else:
                        lines.append(f"    {key}: {truncate_string(value_str, 150)}")
            else:
                indexeddb_str = str(indexeddb)
                if full_logs:
                    lines.append(f"    {indexeddb_str}")
                else:
                    lines.append(f"    {truncate_string(indexeddb_str, 300)}")

        # User action history section (last 20 interactions: button names / navigation only)
        # NO user-typed text content is ever included — only developer-authored labels.
        # This shows the sequence of interactions that led up to the reported issue,
        # making it easy to reproduce the user flow without reading chat messages.
        action_history = report.get('action_history')
        if action_history:
            lines.append("")
            lines.append("  USER ACTION HISTORY (button names / navigation — no typed text):")
            lines.append("  " + "-" * 60)
            for action_line in str(action_history).split('\n'):
                lines.append(f"    {action_line}")

        # Screenshot pre-signed URL from YAML report
        # (also shown in DECRYPTED FIELDS above from a freshly generated URL)
        screenshot_url_in_yaml = report.get('screenshot_presigned_url')
        if screenshot_url_in_yaml:
            lines.append("")
            lines.append("  SCREENSHOT URL (from YAML report — may have expired):")
            lines.append("  " + "-" * 60)
            lines.append(f"    {screenshot_url_in_yaml}")
            lines.append("    Note: Use the pre-signed URL in DECRYPTED FIELDS for a fresh 7-day link.")

        # Last messages HTML section (rendered HTML of last user message + assistant response)
        last_messages_html = report.get('last_messages_html')
        if last_messages_html:
            lines.append("")
            lines.append("  LAST MESSAGES HTML (rendered user message + assistant response):")
            lines.append("  " + "-" * 60)
            html_text = str(last_messages_html)
            # Show full HTML content since it's useful for debugging rendering
            for html_line in html_text.split('\n'):
                lines.append(f"    {html_line}")

        # Picked element HTML — outerHTML of the DOM element the user tapped via the element
        # picker overlay. Captures the exact broken UI element for layout/rendering debugging.
        picked_element_html = report.get('picked_element_html')
        if picked_element_html:
            lines.append("")
            lines.append("  PICKED ELEMENT HTML (element selected via element picker overlay):")
            lines.append("  " + "-" * 60)
            for html_line in str(picked_element_html).split('\n'):
                lines.append(f"    {html_line}")

        # Active chat sidebar HTML — outerHTML of the active Chat.svelte entry at submit time.
        # Captures title, status label, typing indicator, and category icon state.
        active_chat_sidebar_html = report.get('active_chat_sidebar_html')
        if active_chat_sidebar_html:
            lines.append("")
            lines.append("  ACTIVE CHAT SIDEBAR HTML (sidebar entry state at submit time):")
            lines.append("  " + "-" * 60)
            for html_line in str(active_chat_sidebar_html).split('\n'):
                lines.append(f"    {html_line}")

        # Runtime debug state — WS connection, online status, AI typing, pending uploads, sync.
        # Stored as a JSON string or dict in the YAML report depending on serialization round-trip.
        runtime_debug_state = report.get('runtime_debug_state')
        if runtime_debug_state:
            lines.append("")
            lines.append("  RUNTIME DEBUG STATE (WS, online, AI typing, pending uploads, sync):")
            lines.append("  " + "-" * 60)
            if isinstance(runtime_debug_state, dict):
                import json as _json_local
                state_text = _json_local.dumps(runtime_debug_state, indent=2, default=str)
            else:
                state_text = str(runtime_debug_state)
            for state_line in state_text.split('\n'):
                lines.append(f"    {state_line}")

    # Footer
    lines.append("")
    lines.append("=" * 100)
    lines.append("END OF REPORT")
    lines.append("=" * 100)
    lines.append("")

    return "\n".join(lines)


def format_detail_json(
    issue_id: str,
    issue: Optional[Dict[str, Any]],
    decrypted: Dict[str, Optional[str]],
    s3_report: Optional[Dict[str, Any]],
    screenshot_presigned_url: Optional[str] = None
) -> str:
    """
    Format the issue inspection results as JSON.

    Args:
        issue_id: The issue ID
        issue: Raw issue metadata from Directus
        decrypted: Dictionary of decrypted field values
        s3_report: Parsed YAML report from S3 (or None)

    Returns:
        JSON string
    """
    # Censor email in decrypted fields for JSON output
    censored_decrypted = dict(decrypted)
    if censored_decrypted.get('contact_email'):
        censored_decrypted['contact_email'] = censor_email(censored_decrypted['contact_email'])

    # Censor email in S3 report metadata if present
    censored_s3_report = s3_report
    if s3_report:
        import copy
        censored_s3_report = copy.deepcopy(s3_report)
        report = censored_s3_report.get('issue_report', censored_s3_report)
        metadata = report.get('metadata', {})
        if metadata.get('contact_email'):
            metadata['contact_email'] = censor_email(metadata['contact_email'])

    output = {
        'issue_id': issue_id,
        'generated_at': datetime.now().isoformat(),
        'issue_metadata': issue,
        'decrypted_fields': censored_decrypted,
        's3_report': censored_s3_report,
        # Fresh 7-day pre-signed URL for the screenshot PNG (if attached).
        # Load this URL directly to view the screenshot image.
        'screenshot_presigned_url': screenshot_presigned_url
    }

    return json.dumps(output, indent=2, default=str)


async def main():
    """Main function that inspects an issue or lists issues."""
    parser = argparse.ArgumentParser(
        description='Inspect issue report data including metadata, decrypted fields, and S3 YAML report'
    )
    parser.add_argument(
        'issue_id',
        type=str,
        nargs='?',
        default=None,
        help='Issue ID (UUID format) to inspect'
    )
    parser.add_argument(
        '--no-logs',
        action='store_true',
        help='Skip fetching the full YAML report from S3 (faster)'
    )
    parser.add_argument(
        '--json',
        action='store_true',
        help='Output as JSON instead of formatted text'
    )
    parser.add_argument(
        '--list',
        action='store_true',
        help='List recent issues instead of inspecting a specific one'
    )
    parser.add_argument(
        '--list-limit',
        type=int,
        default=20,
        help='Number of issues to list (default: 20, used with --list)'
    )
    parser.add_argument(
        '--search',
        type=str,
        default=None,
        help='Search issues by title/description (used with --list)'
    )
    parser.add_argument(
        '--include-processed',
        action='store_true',
        help='Include processed issues in --list results'
    )
    parser.add_argument(
        '--full-logs',
        action='store_true',
        help=(
            'Show all data untruncated: full log lines (not just errors/warnings) AND full text '
            'fields (description, device info, IndexedDB, etc.). '
            'Output can be very long — consider piping to a file or using grep to filter.'
        )
    )
    parser.add_argument(
        '--delete',
        action='store_true',
        help='Delete the issue (Directus + S3). Use after confirming the issue is fixed.'
    )
    parser.add_argument(
        '--yes',
        action='store_true',
        help='Skip confirmation when using --delete (required for non-interactive use)'
    )
    parser.add_argument(
        '--production',
        action='store_true',
        help='Fetch data from the production Admin Debug API instead of local Directus'
    )
    parser.add_argument(
        '--dev',
        action='store_true',
        help='When used with --production, hit the dev API instead of prod'
    )

    args = parser.parse_args()

    # Validate arguments
    if not args.list and not args.issue_id:
        parser.error("Either provide an issue_id or use --list to list recent issues")
    if args.delete and args.list:
        parser.error("Cannot use --delete with --list")
    if args.delete and not args.issue_id:
        parser.error("--delete requires an issue_id")

    # --- Determine remote vs local mode ---
    is_remote = args.production or args.dev
    if args.dev and not args.production:
        # --dev implies --production (it selects which remote API to hit)
        is_remote = True

    if is_remote:
        # ===================== PRODUCTION / DEV API MODE =====================
        source_label = "dev" if args.dev else "production"
        script_logger.info(f"Using {source_label} Admin Debug API")

        try:
            if args.list:
                # ---- Remote list mode ----
                script_logger.info(
                    f"Listing issues from {source_label} (limit={args.list_limit}, "
                    f"search={args.search}, include_processed={args.include_processed})"
                )

                api_response = await fetch_issues_list_from_production_api(
                    limit=args.list_limit,
                    search=args.search,
                    include_processed=args.include_processed,
                    use_dev=args.dev,
                )

                if api_response is None:
                    script_logger.error(f"Failed to fetch issues from {source_label} API")
                    sys.exit(1)

                issues, decrypted_list = map_production_issues_list(api_response)

                if args.json:
                    censored_decrypted_list = []
                    for d in decrypted_list:
                        censored = dict(d)
                        if censored.get('contact_email'):
                            censored['contact_email'] = censor_email(censored['contact_email'])
                        censored_decrypted_list.append(censored)

                    output_data = {
                        'generated_at': datetime.now().isoformat(),
                        'total': len(issues),
                        'source': source_label,
                        'issues': [
                            {**issue, 'decrypted': censored}
                            for issue, censored in zip(issues, censored_decrypted_list)
                        ]
                    }
                    print(json.dumps(output_data, indent=2, default=str))
                else:
                    print(format_list_output(issues, decrypted_list))

            elif args.delete:
                # ---- Remote delete mode ----
                if not args.yes:
                    if sys.stdin.isatty():
                        try:
                            reply = input(
                                f"Delete issue {args.issue_id} from {source_label}? [y/N]: "
                            ).strip().lower()
                            if reply not in ("y", "yes"):
                                script_logger.info("Delete cancelled.")
                                sys.exit(0)
                        except (EOFError, KeyboardInterrupt):
                            script_logger.info("Delete cancelled.")
                            sys.exit(0)
                    else:
                        script_logger.error(
                            "Use --yes to confirm deletion (required when not running interactively)."
                        )
                        sys.exit(1)

                result = await delete_issue_via_production_api(
                    args.issue_id, use_dev=args.dev
                )
                if result is None:
                    script_logger.error(f"Issue not found on {source_label}: {args.issue_id}")
                    sys.exit(1)
                if result.get("success"):
                    script_logger.info(result.get("message", f"Issue {args.issue_id} deleted"))
                else:
                    script_logger.error(result.get("message", "Delete failed"))
                    sys.exit(1)

            else:
                # ---- Remote detail mode ----
                script_logger.info(f"Inspecting issue: {args.issue_id}")

                api_response = await fetch_issue_from_production_api(
                    args.issue_id,
                    include_logs=not args.no_logs,
                    use_dev=args.dev,
                )

                if api_response is None:
                    script_logger.error(
                        f"Issue not found on {source_label}: {args.issue_id}"
                    )
                    sys.exit(1)

                mapped = map_production_issue_to_local_format(api_response)
                issue = mapped["issue"]
                decrypted = mapped["decrypted"]
                s3_report = mapped["full_report"]

                # Screenshot pre-signed URLs are not available via the API
                screenshot_presigned_url = None

                if args.json:
                    print(format_detail_json(
                        args.issue_id, issue, decrypted, s3_report,
                        screenshot_presigned_url=screenshot_presigned_url,
                    ))
                else:
                    print(format_detail_output(
                        args.issue_id, issue, decrypted, s3_report,
                        full_logs=args.full_logs,
                        screenshot_presigned_url=screenshot_presigned_url,
                    ))

        except Exception as e:
            script_logger.error(f"Error during inspection: {e}", exc_info=True)
            raise

    else:
        # ===================== LOCAL MODE (original code path) =====================
        # Initialize services
        cache_service = CacheService()
        encryption_service = EncryptionService()
        directus_service = DirectusService(
            cache_service=cache_service,
            encryption_service=encryption_service
        )

        # Initialize S3 service (needed for fetching YAML reports)
        secrets_manager = SecretsManager()
        s3_service = None

        try:
            if args.list:
                # ===================== LIST MODE =====================
                script_logger.info(
                    f"Listing issues (limit={args.list_limit}, search={args.search}, "
                    f"include_processed={args.include_processed})"
                )

                issues = await list_issues(
                    directus_service,
                    limit=args.list_limit,
                    search=args.search,
                    include_processed=args.include_processed
                )

                # Decrypt email for each issue (for display in list)
                decrypted_list = []
                for issue in issues:
                    decrypted = await decrypt_issue_fields(encryption_service, issue)
                    decrypted_list.append(decrypted)

                if args.json:
                    # Censor emails in JSON list output
                    censored_decrypted_list = []
                    for d in decrypted_list:
                        censored = dict(d)
                        if censored.get('contact_email'):
                            censored['contact_email'] = censor_email(censored['contact_email'])
                        censored_decrypted_list.append(censored)

                    output_data = {
                        'generated_at': datetime.now().isoformat(),
                        'total': len(issues),
                        'issues': [
                            {
                                **issue,
                                'decrypted': censored
                            }
                            for issue, censored in zip(issues, censored_decrypted_list)
                        ]
                    }
                    print(json.dumps(output_data, indent=2, default=str))
                else:
                    print(format_list_output(issues, decrypted_list))

            else:
                # ===================== DETAIL MODE (or DELETE) =====================
                # 1. Fetch issue metadata
                issue = await get_issue(directus_service, args.issue_id)

                if args.delete:
                    # Delete flow: confirm then delete from S3 and Directus
                    if not issue:
                        script_logger.error(f"Issue not found: {args.issue_id}")
                        sys.exit(1)
                    if not args.yes:
                        if sys.stdin.isatty():
                            try:
                                reply = input(f"Delete issue {args.issue_id}? [y/N]: ").strip().lower()
                                if reply != "y" and reply != "yes":
                                    script_logger.info("Delete cancelled.")
                                    sys.exit(0)
                            except (EOFError, KeyboardInterrupt):
                                script_logger.info("Delete cancelled.")
                                sys.exit(0)
                        else:
                            script_logger.error(
                                "Use --yes to confirm deletion "
                                "(required when not running interactively)."
                            )
                            sys.exit(1)
                    # Init S3 if issue has any S3 key (YAML report or screenshot)
                    if (
                        issue.get("encrypted_issue_report_yaml_s3_key")
                        or issue.get("encrypted_screenshot_s3_key")
                    ):
                        try:
                            await secrets_manager.initialize()
                            s3_service = S3UploadService(secrets_manager=secrets_manager)
                            await s3_service.initialize()
                        except Exception as e:
                            script_logger.warning(
                                f"S3 init failed; will delete from Directus only: {e}"
                            )
                    success, message = await delete_issue(
                        directus_service, encryption_service, s3_service, args.issue_id, issue
                    )
                    if success:
                        script_logger.info(message)
                    else:
                        script_logger.error(message)
                        sys.exit(1)
                    return

                # Inspect flow
                script_logger.info(f"Inspecting issue: {args.issue_id}")

                # 2. Decrypt fields
                decrypted: Dict[str, Optional[str]] = {}
                if issue:
                    decrypted = await decrypt_issue_fields(encryption_service, issue)

                # 3. Fetch S3 report and generate screenshot pre-signed URL (if applicable)
                s3_report = None
                screenshot_presigned_url: Optional[str] = None
                needs_s3 = (
                    (not args.no_logs and issue and issue.get('encrypted_issue_report_yaml_s3_key'))
                    or (issue and issue.get('encrypted_screenshot_s3_key'))
                )
                if needs_s3:
                    script_logger.info("Initializing S3 service for report/screenshot...")
                    try:
                        await secrets_manager.initialize()
                        s3_service = S3UploadService(secrets_manager=secrets_manager)
                        await s3_service.initialize()

                        # Fetch YAML report (unless --no-logs)
                        if not args.no_logs and issue and issue.get('encrypted_issue_report_yaml_s3_key'):
                            script_logger.info("Fetching S3 YAML report...")
                            s3_report = await fetch_s3_report(encryption_service, s3_service, issue)

                        # Generate fresh 7-day pre-signed URL for the screenshot PNG
                        if issue and issue.get('encrypted_screenshot_s3_key'):
                            script_logger.info("Generating screenshot pre-signed URL...")
                            screenshot_presigned_url = await get_screenshot_presigned_url(
                                encryption_service, s3_service, issue
                            )
                    except Exception as e:
                        script_logger.warning(f"Failed to initialize S3 service: {e}")

                # 4. Format and output results
                if args.json:
                    print(format_detail_json(
                        args.issue_id, issue, decrypted, s3_report,
                        screenshot_presigned_url=screenshot_presigned_url
                    ))
                else:
                    print(format_detail_output(
                        args.issue_id, issue, decrypted, s3_report,
                        full_logs=args.full_logs,
                        screenshot_presigned_url=screenshot_presigned_url
                    ))

        except Exception as e:
            script_logger.error(f"Error during inspection: {e}", exc_info=True)
            raise
        finally:
            # Clean up
            await directus_service.close()
            if secrets_manager:
                try:
                    await secrets_manager.aclose()
                except Exception:
                    pass


if __name__ == "__main__":
    asyncio.run(main())
