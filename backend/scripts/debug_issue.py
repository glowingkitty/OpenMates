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
- encrypted_issue_report_yaml_s3_key: Vault-encrypted S3 key pointing to S3 YAML (no longer
  contains logs — those are queried live from OpenObserve via --timeline)

Usage:
    docker exec api python /app/backend/scripts/debug.py issue <issue_id>
    docker exec api python /app/backend/scripts/debug.py issue abc12345-6789-0123-4567-890123456789

    # Unified timeline: browser console + backend logs merged chronologically
    docker exec api python /app/backend/scripts/debug.py issue <issue_id> --timeline
    docker exec api python /app/backend/scripts/debug.py issue <issue_id> --timeline --before 15 --after 5

    # Fetch issue from production server (required for production-only issues)
    docker exec api python /app/backend/scripts/debug.py issue <issue_id> --production
    docker exec api python /app/backend/scripts/debug.py issue --list --production
    docker exec api python /app/backend/scripts/debug.py issue <issue_id> --timeline --production

Options:
    --no-logs           Skip fetching the full YAML report from S3
    --full-logs         Show all data untruncated: full text fields (description,
                        device info, IndexedDB, etc.). Output can be very long — pipe to a file or
                        use grep to filter. Use --timeline for log inspection.
    --timeline          Show a unified chronological timeline of browser console + backend logs
                        from OpenObserve, anchored to the issue's created_at timestamp.
                        Replaces --full-logs for log investigation.
    --before N          Minutes before issue timestamp to include in timeline (default: 10)
    --after N           Minutes after issue timestamp to include in timeline (default: 5)
    --json              Output as JSON instead of formatted text
    --list              List recent issues (most recent first)
    --list-limit N      Number of issues to list (default: 20)
    --search TEXT       Search issues by title/description (used with --list)
    --include-processed Include processed issues in --list results
    --delete            Delete the issue (Directus + S3). Use after confirming the issue is fixed.
    --yes               Skip confirmation when using --delete (required for non-interactive use)
    --related-commits   Search git history for commits related to this issue by keywords from title/description.
                        Shows matching commits and which files they touched.
    --production        Fetch data from the production Admin Debug API instead of local Directus
    --dev               Fetch data from the dev Admin Debug API (implies --production)
"""

import asyncio
import argparse
import json
import os
import sys
import time
from datetime import datetime, timezone
from typing import Dict, Any, List, Optional, Tuple

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


# ──────────────────────────────────────────────────────────────────────────────
# TIMELINE — unified browser + backend log view anchored to issue created_at
# ──────────────────────────────────────────────────────────────────────────────

# ANSI colours (mirrors debug_logs.py palette — kept minimal here)
_C_RESET  = "\033[0m"
_C_DIM    = "\033[2m"
_C_BOLD   = "\033[1m"
_C_RED    = "\033[31m"
_C_YELLOW = "\033[33m"
_C_CYAN   = "\033[36m"
_C_GREEN  = "\033[32m"
_C_MAGENTA= "\033[35m"


def _sql_esc(s: str) -> str:
    return s.replace("'", "''")


async def _query_openobserve_sql(
    sql: str,
    start_us: int,
    end_us: int,
    max_rows: int = 2000,
) -> List[Dict[str, Any]]:
    """Execute a raw SQL query against the local OpenObserve instance."""
    import aiohttp

    email    = os.getenv("OPENOBSERVE_ROOT_EMAIL", "")
    password = os.getenv("OPENOBSERVE_ROOT_PASSWORD", "")

    sql_text = sql.strip().rstrip(";")
    if " limit " not in sql_text.lower():
        sql_text = f"{sql_text} LIMIT {max_rows}"

    body = {"query": {"sql": sql_text, "start_time": start_us, "end_time": end_us}}
    urls = (
        "http://openobserve:5080/api/default/_search",
        "http://openobserve:5080/api/default/default/_search",
    )
    timeout = aiohttp.ClientTimeout(total=30)
    try:
        async with aiohttp.ClientSession(timeout=timeout) as session:
            for url in urls:
                async with session.post(
                    url, json=body, auth=aiohttp.BasicAuth(email, password)
                ) as resp:
                    if resp.status == 200:
                        data = await resp.json()
                        return data.get("hits", [])
                    if resp.status == 404:
                        continue
                    script_logger.warning(
                        f"OpenObserve query failed ({resp.status}): {(await resp.text())[:200]}"
                    )
                    return []
    except Exception as exc:
        script_logger.warning(f"Cannot connect to OpenObserve: {exc}")
        return []
    return []


def _parse_ts_us(hit: Dict[str, Any]) -> int:
    """Return the hit's _timestamp in microseconds (int)."""
    return int(hit.get("_timestamp", 0))


def _hit_to_event(hit: Dict[str, Any], source_override: Optional[str] = None) -> Dict[str, Any]:
    """Convert a raw OpenObserve hit to a normalised event dict."""
    ts_us  = _parse_ts_us(hit)
    level  = (hit.get("level") or "info").lower()
    source = source_override or hit.get("container") or hit.get("service") or "unknown"
    job    = hit.get("job", "")
    if job == "client-console":
        source = "browser"
    msg = (hit.get("message") or "").strip()
    return {"ts_us": ts_us, "level": level, "source": source, "message": msg}


async def fetch_issue_timeline_local(
    issue: Dict[str, Any],
    before_minutes: int = 10,
    after_minutes: int = 5,
    max_rows: int = 2000,
) -> Tuple[List[Dict[str, Any]], int, int]:
    """
    Query OpenObserve for the unified issue timeline (local mode).

    Runs three parallel queries anchored to the issue's created_at timestamp:
      1. Browser console logs: job=client-console, matching user_id in message
      2. Raw container stdout logs: job empty/NULL, matching user_id/issue_id
      3. Structured API logs: job=api-logs, matching user_id/issue_id

    Returns (events, start_us, end_us) where events are sorted by timestamp.
    """
    issue_id = issue.get("id", "")
    user_id  = issue.get("reported_by_user_id") or ""

    # Determine the incident anchor timestamp
    created_at_str = issue.get("created_at") or issue.get("timestamp") or ""
    try:
        anchor_dt = datetime.fromisoformat(created_at_str.replace("Z", "+00:00"))
        anchor_us = int(anchor_dt.timestamp() * 1_000_000)
    except Exception:
        # Fall back to now
        anchor_us = int(time.time() * 1_000_000)

    start_us = anchor_us - before_minutes * 60 * 1_000_000
    end_us   = anchor_us + after_minutes  * 60 * 1_000_000

    # Clamp end_us to now so we don't query the future
    now_us = int(time.time() * 1_000_000)
    if end_us > now_us:
        end_us = now_us

    issue_id_esc = _sql_esc(issue_id)

    # Build queries
    queries: List[Tuple[str, Optional[str]]] = []

    # ── OpenObserve "default" stream field reference ──
    # Available fields: _timestamp, compose_project, container, debugging_id,
    #   device_type, environment, event_type, filename, git_branch, job, level,
    #   logstream, message, name, server_env, service, source, status, stream,
    #   suite, tab_id, transaction_type, user_agent, user_email, user_id,
    #   worker_slot.
    # NOT valid: 'log', 'issue_id'.
    # Job values: 'client-console' (browser), 'api-logs' (structured API),
    #   'audit-compliance-logs', or empty/NULL (raw container stdout).

    # 1. Browser console logs (job=client-console).
    # The user_id / issue_id are NOT structured fields on client-console entries,
    # so we match on the user_id in the message body when available.
    if user_id:
        user_id_esc = _sql_esc(user_id)
        browser_where = (
            f"job = 'client-console' AND "
            f"(message LIKE '%{user_id_esc}%' OR message LIKE '%{issue_id_esc}%')"
        )
    else:
        browser_where = (
            f"job = 'client-console' AND message LIKE '%{issue_id_esc}%'"
        )
    queries.append((
        f"SELECT _timestamp, message, level "
        f'FROM "default" '
        f"WHERE {browser_where} "
        f"ORDER BY _timestamp ASC",
        "browser",
    ))

    # 2+3. Backend logs mentioning issue_id or user_id in message body.
    search_terms: List[str] = [_sql_esc(issue_id)]
    if user_id:
        search_terms.append(_sql_esc(user_id))

    like_clauses = " OR ".join(
        f"message LIKE '%{t}%'" for t in search_terms
    )

    # 2. Raw container stdout logs (no job label, but container/service populated).
    queries.append((
        f"SELECT _timestamp, container, service, message, level "
        f'FROM "default" '
        f"WHERE (job = '' OR job IS NULL) AND ({like_clauses}) "
        f"ORDER BY _timestamp ASC",
        None,
    ))

    # 3. Structured API logs (job=api-logs; container/service often empty).
    queries.append((
        f"SELECT _timestamp, message, level "
        f'FROM "default" '
        f"WHERE job = 'api-logs' AND ({like_clauses}) "
        f"ORDER BY _timestamp ASC",
        "api",
    ))

    # Execute all queries in parallel
    results = await asyncio.gather(
        *[_query_openobserve_sql(sql, start_us, end_us, max_rows) for sql, _ in queries],
        return_exceptions=True,
    )

    all_events: List[Dict[str, Any]] = []
    for (_, source_override), result in zip(queries, results):
        if isinstance(result, BaseException):
            script_logger.warning(f"Timeline query failed: {result}")
            continue
        for hit in result:
            all_events.append(_hit_to_event(hit, source_override))

    # ── Merge OTel trace spans if trace_ids are present in the issue ──
    # Issues created after the OTel integration include trace_ids from the
    # frontend's WS span ring buffer. We query OpenObserve for these traces
    # and merge the spans into the timeline for end-to-end visibility.
    trace_ids = issue.get("trace_ids") or []
    if trace_ids and isinstance(trace_ids, list):
        try:
            # Import from the sibling debug_trace module (lives in the same directory)
            import importlib.util
            trace_script = os.path.join(os.path.dirname(__file__), "debug_trace.py")
            spec = importlib.util.spec_from_file_location("debug_trace", trace_script)
            if spec and spec.loader:
                debug_trace_mod = importlib.util.module_from_spec(spec)
                spec.loader.exec_module(debug_trace_mod)
                base_url = debug_trace_mod._get_base_url(production=False)
                auth = debug_trace_mod._get_auth(production=False)

                for tid in trace_ids[:20]:  # Cap to 20 trace IDs max
                    tid_clean = tid.strip()
                    if not tid_clean:
                        continue
                    sql = debug_trace_mod._query_by_trace_id(tid_clean)
                    spans = debug_trace_mod._search_traces(
                        sql, start_us, end_us, base_url, auth
                    )
                    for span in spans:
                        # Convert trace span to timeline event format
                        span_ts = span.get("start_time", 0)
                        span_name = span.get("operation_name", span.get("span_name", "unknown"))
                        service = span.get("service_name", "")
                        duration_ns = span.get("duration", 0)
                        duration_ms = duration_ns / 1_000_000 if duration_ns else 0
                        status = span.get("span_status", "")

                        msg = f"[TRACE] {span_name}"
                        if duration_ms > 0:
                            msg += f" ({duration_ms:.1f}ms)"
                        if status and status != "Unset":
                            msg += f" [{status}]"

                        all_events.append({
                            "ts_us": span_ts // 1000 if span_ts > 1e15 else span_ts,
                            "source": f"trace:{service}" if service else "trace",
                            "level": "TRACE",
                            "message": msg,
                        })
        except Exception as trace_err:
            script_logger.warning(f"Failed to merge OTel trace spans: {trace_err}")

    # Deduplicate (same µs + first 100 chars of message)
    seen: set = set()
    unique: List[Dict[str, Any]] = []
    for evt in sorted(all_events, key=lambda e: e["ts_us"]):
        key = (evt["ts_us"], evt["message"][:100])
        if key not in seen:
            seen.add(key)
            unique.append(evt)

    return unique, start_us, end_us


async def fetch_issue_timeline_remote(
    issue_id: str,
    before_minutes: int,
    after_minutes: int,
    use_dev: bool = False,
) -> Optional[Dict[str, Any]]:
    """
    Fetch the issue timeline via the production Admin Debug API.

    Calls GET /v1/admin/debug/issues/{issue_id}/timeline with before/after params.
    Returns the raw API response dict, or None on failure.
    """
    api_key  = await get_api_key_from_vault()
    base_url = DEV_API_URL if use_dev else PROD_API_URL

    return await make_prod_api_request(
        f"issues/{issue_id}/timeline",
        api_key,
        base_url,
        params={"before_minutes": before_minutes, "after_minutes": after_minutes},
        entity_label=f"Issue timeline {issue_id}",
    )


def format_issue_timeline(
    events: List[Dict[str, Any]],
    issue: Dict[str, Any],
    start_us: int,
    end_us: int,
    before_minutes: int,
    after_minutes: int,
) -> str:
    """
    Render the merged browser+backend event timeline for an issue.

    Each line: HH:MM:SS.mmm  LEVEL  [source]  message
    A visual marker is inserted at the issue's created_at timestamp.
    """
    lines: List[str] = []

    issue_id    = issue.get("id", "?")[:8]
    title       = issue.get("title", "?")
    created_str = issue.get("created_at") or issue.get("timestamp") or ""
    try:
        anchor_dt = datetime.fromisoformat(created_str.replace("Z", "+00:00"))
        anchor_us = int(anchor_dt.timestamp() * 1_000_000)
        anchor_label = anchor_dt.strftime("%H:%M:%S UTC")
    except Exception:
        anchor_us    = 0
        anchor_label = "unknown"

    start_dt = datetime.fromtimestamp(start_us / 1_000_000, tz=timezone.utc)
    end_dt   = datetime.fromtimestamp(end_us   / 1_000_000, tz=timezone.utc)

    # Header
    lines.append("")
    lines.append("=" * 100)
    lines.append(f"ISSUE TIMELINE  #{issue_id}  —  {title}")
    lines.append("=" * 100)
    lines.append(
        f"  Window: {start_dt.strftime('%Y-%m-%d %H:%M:%S')} → "
        f"{end_dt.strftime('%Y-%m-%d %H:%M:%S')} UTC  "
        f"(−{before_minutes}min / +{after_minutes}min around report)"
    )
    lines.append(f"  Report: {created_str}   |   Events: {len(events)}")
    lines.append("=" * 100)

    if not events:
        lines.append("")
        lines.append("  No events found in OpenObserve for this time window.")
        lines.append(
            "  The issue may pre-date the current OpenObserve retention window, "
            "or no logs were tagged with the issue_id / user_id."
        )
        lines.append("")
        lines.append("=" * 100)
        lines.append("")
        return "\n".join(lines)

    marker_inserted = False
    prev_ts_us: Optional[int] = None

    for evt in events:
        ts_us   = evt["ts_us"]
        level   = evt["level"]
        source  = evt["source"]
        message = evt["message"]

        # Insert the "ISSUE REPORTED" marker at the right chronological position
        if not marker_inserted and anchor_us > 0 and ts_us >= anchor_us:
            marker_inserted = True
            lines.append("")
            lines.append(
                f"{'─' * 20}  ISSUE REPORTED  {anchor_label}  {'─' * 20}"
            )
            lines.append("")

        # Time gap separator (> 60 s between consecutive events)
        if prev_ts_us is not None and (ts_us - prev_ts_us) > 60 * 1_000_000:
            gap_s = (ts_us - prev_ts_us) / 1_000_000
            lines.append(f"  {_C_DIM}... {gap_s:.0f}s gap ...{_C_RESET}")

        prev_ts_us = ts_us

        # Format timestamp
        dt     = datetime.fromtimestamp(ts_us / 1_000_000, tz=timezone.utc)
        ts_str = dt.strftime("%H:%M:%S.") + f"{dt.microsecond // 1000:03d}"

        # Level badge + colour
        lvl_upper = level.upper()[:5]
        if level in ("error", "critical"):
            lvl_col = _C_RED
            suffix  = " !!"
        elif level in ("warn", "warning"):
            lvl_col = _C_YELLOW
            suffix  = " ! "
        else:
            lvl_col = _C_DIM
            suffix  = "   "

        # Source colour
        if source == "browser":
            src_col = _C_MAGENTA
        elif source in ("api", "api-logs"):
            src_col = _C_CYAN
        else:
            src_col = _C_GREEN

        # Truncate message to 160 chars for readable output
        msg_display = message[:160] + ("…" if len(message) > 160 else "")

        lines.append(
            f"  {_C_DIM}{ts_str}{_C_RESET}  "
            f"{lvl_col}{lvl_upper:<5}{_C_RESET}{suffix}  "
            f"{src_col}[{source[:20]}]{_C_RESET}  "
            f"{msg_display}"
        )

    # If anchor is after all events, insert marker at the end
    if not marker_inserted and anchor_us > 0:
        lines.append("")
        lines.append(
            f"{'─' * 20}  ISSUE REPORTED  {anchor_label}  {'─' * 20}"
        )

    # Footer summary
    error_count   = sum(1 for e in events if e["level"] in ("error", "critical"))
    warning_count = sum(1 for e in events if e["level"] in ("warn", "warning"))
    sources       = sorted({e["source"] for e in events})
    lines.append("")
    lines.append("-" * 100)
    lines.append(
        f"  Summary: {len(events)} events | {error_count} errors | {warning_count} warnings | "
        f"sources: {', '.join(sources)}"
    )
    lines.append("=" * 100)
    lines.append("")

    return "\n".join(lines)


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


def _relative_time(timestamp_str: Optional[str]) -> str:
    """Convert an ISO timestamp to a relative time string like '2h ago' or '3d ago'."""
    if not timestamp_str:
        return "?"
    try:
        dt = datetime.fromisoformat(timestamp_str.replace("Z", "+00:00"))
        now = datetime.now(dt.tzinfo) if dt.tzinfo else datetime.now()
        delta = now - dt
        minutes = int(delta.total_seconds() / 60)
        if minutes < 1:
            return "just now"
        if minutes < 60:
            return f"{minutes}m ago"
        hours = minutes // 60
        if hours < 24:
            return f"{hours}h ago"
        days = hours // 24
        return f"{days}d ago"
    except Exception:
        return "?"


def format_compact_output(
    issues: List[Dict[str, Any]],
) -> str:
    """Format issues as a compact one-line-per-issue summary for session context.

    Shows truncated issue_id, relative time, title, truncated user_id (no email),
    and affected URL. Designed to be concise enough to embed in sessions.py start
    output without overwhelming Claude with irrelevant detail.

    Args:
        issues: Raw issue dictionaries from Directus (or mapped from API).

    Returns:
        Compact multi-line string, or empty message if no issues.
    """
    if not issues:
        return "  No recent issues."

    lines = []
    for issue in issues:
        issue_id = issue.get("id", "N/A")
        title = truncate_string(issue.get("title", "N/A"), 60)
        user_id = issue.get("reported_by_user_id")
        user_str = f"user:{user_id[:8]}" if user_id else "user:anon"
        timestamp = issue.get("created_at") or issue.get("timestamp")
        rel_time = _relative_time(timestamp)

        # Try to extract URL from encrypted fields (only available locally, not via compact)
        url = issue.get("chat_or_embed_url", "")
        url_str = f", {truncate_string(url, 40)}" if url else ""

        lines.append(f"  #{issue_id} ({rel_time}) \"{title}\" — {user_str}{url_str}")

    lines.append("  → Inspect: docker exec api python /app/backend/scripts/debug.py issue <ID>")
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
            "  ℹ  Summary mode: some fields are truncated."
        )
        lines.append(
            "     Use --full-logs for complete untruncated field output."
        )
    lines.append(
        "  ℹ  For logs, use: debug.py issue <id> --timeline  "
        "(unified browser + backend timeline from OpenObserve)"
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

        # Logs section — no longer stored in S3 YAML; queried live from OpenObserve via --timeline.
        # Old YAMLs may still contain console_logs / docker_compose_logs; show a migration note.
        logs = report.get('logs', {})
        if logs and (logs.get('console_logs') or logs.get('docker_compose_logs')):
            lines.append("")
            lines.append("  LOGS (legacy snapshot — pre-dates OpenObserve timeline):")
            lines.append("  " + "-" * 60)
            lines.append(
                "    This YAML was created before log data was moved to OpenObserve."
            )
            lines.append(
                "    Run with --timeline for a live, unified browser+backend timeline instead."
            )
            # Still show a quick error-only filter so old YAMLs aren't totally opaque
            console_logs = logs.get('console_logs')
            docker_logs  = logs.get('docker_compose_logs')
            combined = ""
            if console_logs:
                combined += str(console_logs) + "\n"
            if docker_logs:
                if isinstance(docker_logs, dict):
                    for svc_logs in docker_logs.values():
                        if svc_logs:
                            combined += str(svc_logs) + "\n"
                else:
                    combined += str(docker_logs) + "\n"
            if combined.strip():
                filtered, total, matches = filter_logs_to_errors(combined)
                lines.append(
                    f"    Quick error scan: {matches} warning(s)/error(s) of {total} lines"
                )
                if filtered:
                    for fl in filtered[:40]:  # cap at 40 lines to keep output short
                        lines.append(f"  {fl}")
                    if len(filtered) > 40:
                        lines.append(f"    ... ({len(filtered) - 40} more — use --timeline)")

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



def format_summary_output(
    issue_id: str,
    issue: Optional[Dict[str, Any]],
    decrypted: Dict[str, Optional[str]],
    s3_report: Optional[Dict[str, Any]],
) -> str:
    """Format a condensed issue summary for sessions.py inline context.

    Shows metadata, key findings, runtime state, and last 5 user actions.
    Skips raw HTML (messages, sidebar) to keep output under ~40 lines.
    """
    lines = []

    # ── Compact header
    title = (issue or {}).get('title', 'Unknown')
    created = (issue or {}).get('date_created', '') or (issue or {}).get('timestamp', '')
    from_admin = (issue or {}).get('is_from_admin', False) or False
    user_id = (issue or {}).get('user_created', '') or '?'

    lines.append(f"Issue: {title}")
    lines.append(f"  ID: {issue_id}")
    lines.append(f"  Time: {created}  |  Admin: {'yes' if from_admin else 'no'}  |  User: {user_id[:12]}...")

    # ── Decrypted key info (1-2 lines)
    url = decrypted.get('chat_or_embed_url', '')
    device = decrypted.get('device_info', '')
    location = decrypted.get('estimated_location', '')
    if url:
        lines.append(f"  URL: {url[:120]}{'...' if len(url) > 120 else ''}")
    if location:
        lines.append(f"  Location: {location}  |  Device: {device[:80] if device else 'N/A'}")

    # ── Description (truncated)
    desc = (issue or {}).get('description', '')
    if desc:
        # Strip HTML entities, take first 200 chars
        import html as _html
        clean_desc = _html.unescape(desc).replace('\n', ' ').strip()
        if len(clean_desc) > 200:
            clean_desc = clean_desc[:197] + '...'
        lines.append(f"  Description: {clean_desc}")

    # ── S3 YAML key findings
    report = s3_report or {}
    indexeddb = report.get('indexeddb_inspection')
    if indexeddb and isinstance(indexeddb, dict):
        # Extract the chat inspection text
        indexeddb_str = str(indexeddb) if not isinstance(indexeddb, str) else indexeddb
        lines.append(f"  IndexedDB: {indexeddb_str[:200]}{'...' if len(indexeddb_str) > 200 else ''}")
    elif indexeddb:
        indexeddb_str = str(indexeddb)
        # Look for ISSUES DETECTED
        if 'ISSUES DETECTED' in indexeddb_str:
            start = indexeddb_str.find('ISSUES DETECTED')
            end = indexeddb_str.find('\n\n', start)
            if end == -1:
                end = min(start + 200, len(indexeddb_str))
            lines.append(f"  IndexedDB: {indexeddb_str[start:end].strip()}")
        else:
            lines.append(f"  IndexedDB: {indexeddb_str[:150]}{'...' if len(indexeddb_str) > 150 else ''}")

    # ── Log quick scan (from S3 YAML legacy or pre-computed)
    log_section = report.get('logs_quick_scan') or report.get('console_logs_summary')
    if log_section:
        lines.append(f"  Log scan: {str(log_section)[:200]}")

    # ── Runtime debug state (compact)
    runtime = report.get('runtime_debug_state')
    if runtime:
        if isinstance(runtime, dict):
            ws_status = runtime.get('websocket_status', {})
            sync_state = runtime.get('phased_sync_state', {})
            ws_line = f"WS: {ws_status.get('status', '?')}"
            if ws_status.get('lastMessage'):
                ws_line += f" ({ws_status['lastMessage'][:60]})"
            sync_line = f"Sync: initial={sync_state.get('initialSyncCompleted', '?')}, chat={str(sync_state.get('currentActiveChatId', '?'))[:12]}"
            lines.append(f"  Runtime: {ws_line} | {sync_line}")
        else:
            lines.append(f"  Runtime: {str(runtime)[:150]}")

    # ── User action history (last 5 only)
    actions = report.get('action_history')
    if actions:
        action_lines = str(actions).strip().split('\n')
        if action_lines:
            lines.append(f"  Actions ({len(action_lines)} total, last 5):")
            for al in action_lines[-5:]:
                lines.append(f"    {al.strip()}")

    # ── Footer hint
    lines.append(f"  Full: debug.py issue {issue_id} | Timeline: debug.py issue {issue_id} --timeline")

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


def _find_related_commits_for_issue(title: str, description: str = "", n_commits: int = 50) -> list:
    """Search git history for commits related to an issue by title/description keywords.

    Extracts significant words from title and description, then runs git log --grep
    for each keyword. Returns a deduplicated list of (sha, message, files) tuples.

    Design intent: helps avoid re-investigating known patterns and identifies prior fixes.
    """
    import re as _re
    import subprocess

    # Extract keywords: words >= 5 chars, no common stop words
    _stop_words = {
        "should", "could", "would", "when", "there", "where", "which",
        "broken", "bugfix", "issue", "error", "wrong", "fixed", "added",
        "updated", "button", "click", "modal", "shows", "display", "render",
    }
    text = f"{title} {description}".lower()
    words = _re.findall(r'[a-z][a-z0-9]{4,}', text)
    keywords = [w for w in set(words) if w not in _stop_words][:6]  # limit to 6

    # Also add issue ID substrings (first 8 chars of UUIDs found in text)
    uuid_parts = _re.findall(r'[0-9a-f]{8}', text)
    keywords += uuid_parts[:2]

    if not keywords:
        return []

    # Determine project root relative to this script
    script_dir = os.path.dirname(os.path.abspath(__file__))
    project_root = os.path.join(script_dir, "..", "..")

    found: dict[str, dict] = {}
    for keyword in keywords:
        try:
            result = subprocess.run(
                ["git", "log", f"--max-count={n_commits}", "--oneline",
                 "--grep", keyword, "--ignore-case"],
                capture_output=True, text=True, timeout=10,
                cwd=project_root,
            )
            for line in result.stdout.strip().splitlines():
                sha = line.split(" ", 1)[0]
                if sha not in found:
                    msg = line
                    # Get files touched
                    files_result = subprocess.run(
                        ["git", "diff-tree", "--no-commit-id", "-r", "--name-only", sha],
                        capture_output=True, text=True, timeout=5, cwd=project_root,
                    )
                    files = files_result.stdout.strip().splitlines()[:5]
                    found[sha] = {"msg": msg, "files": files, "matched_kw": keyword}
        except Exception:
            continue

    return list(found.values())[:8]  # cap at 8 results


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
        '--compact',
        action='store_true',
        help='Output a one-line-per-issue summary for embedding in session context. '
        'Shows truncated issue_id, relative time, title, truncated user_id, and URL. '
        'Used with --list. No email addresses are shown.'
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
            'Show all text fields untruncated (description, device info, IndexedDB, etc.). '
            'For log inspection use --timeline instead.'
        )
    )
    parser.add_argument(
        '--timeline',
        action='store_true',
        help=(
            'Show a unified chronological timeline of browser console + backend logs from '
            'OpenObserve, anchored to the issue created_at timestamp. '
            'Use --before / --after to control the time window around the report.'
        )
    )
    parser.add_argument(
        '--before',
        type=int,
        default=10,
        metavar='N',
        help='Minutes before the issue timestamp to include in --timeline (default: 10)'
    )
    parser.add_argument(
        '--after',
        type=int,
        default=5,
        metavar='N',
        help='Minutes after the issue timestamp to include in --timeline (default: 5)'
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
    parser.add_argument(
        '--summary',
        action='store_true',
        help='Output a condensed summary: metadata, key findings, runtime state, '
        'last 5 user actions. Skips raw HTML (messages, sidebar). '
        'Used by sessions.py for inline issue context.'
    )
    parser.add_argument(
        '--related-commits',
        action='store_true',
        help='Search git history for commits related to this issue by extracting '
        'keywords from the issue title and description. Shows matching commits '
        'and files they touched. Useful for finding prior fixes to similar issues.'
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

                if args.compact:
                    print(format_compact_output(issues))
                elif args.json:
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
                # ---- Remote detail mode (or --timeline via API) ----
                script_logger.info(f"Inspecting issue: {args.issue_id}")

                if args.timeline:
                    # --timeline in remote mode: call the dedicated timeline endpoint
                    print(
                        f"{_C_DIM}Fetching issue timeline from {source_label} API...{_C_RESET}",
                        flush=True,
                    )
                    tl_response = await fetch_issue_timeline_remote(
                        args.issue_id,
                        before_minutes=args.before,
                        after_minutes=args.after,
                        use_dev=args.dev,
                    )
                    if tl_response is None:
                        script_logger.error(
                            f"Issue not found or timeline unavailable on {source_label}: "
                            f"{args.issue_id}"
                        )
                        sys.exit(1)

                    # The API returns {issue, events, start_us, end_us}
                    tl_issue   = tl_response.get("issue", {})
                    tl_events  = tl_response.get("events", [])
                    tl_start   = tl_response.get("start_us", 0)
                    tl_end     = tl_response.get("end_us", 0)
                    print(format_issue_timeline(
                        tl_events, tl_issue,
                        tl_start, tl_end,
                        args.before, args.after,
                    ))

                else:
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
                    elif args.summary:
                        print(format_summary_output(
                            args.issue_id, issue, decrypted, s3_report,
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

                if args.compact:
                    # Compact mode: skip expensive email decryption — only show user_id
                    print(format_compact_output(issues))
                    return

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

                if args.timeline:
                    # --timeline: query OpenObserve directly, no S3 needed
                    if not issue:
                        script_logger.error(f"Issue not found: {args.issue_id}")
                        sys.exit(1)
                    print(
                        f"{_C_DIM}Querying OpenObserve timeline "
                        f"(−{args.before}min / +{args.after}min)...{_C_RESET}",
                        flush=True,
                    )
                    tl_events, tl_start, tl_end = await fetch_issue_timeline_local(
                        issue,
                        before_minutes=args.before,
                        after_minutes=args.after,
                    )
                    print(format_issue_timeline(
                        tl_events, issue,
                        tl_start, tl_end,
                        args.before, args.after,
                    ))

                else:
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
                    elif args.summary:
                        print(format_summary_output(
                            args.issue_id, issue, decrypted, s3_report,
                        ))
                    else:
                        print(format_detail_output(
                            args.issue_id, issue, decrypted, s3_report,
                            full_logs=args.full_logs,
                            screenshot_presigned_url=screenshot_presigned_url
                        ))

                    # --related-commits: search git history for prior related fixes
                    if getattr(args, 'related_commits', False) and issue:
                        title = decrypted.get('title', '') or issue.get('title', '') or ''
                        description = decrypted.get('description', '') or ''
                        related = _find_related_commits_for_issue(title, description)
                        print()
                        print("═" * 60)
                        if related:
                            print(f"Related commits ({len(related)} found):")
                            for r in related:
                                print(f"  {r['msg']}")
                                for f in r['files']:
                                    print(f"    {f}")
                                print(f"    (matched keyword: {r['matched_kw']})")
                        else:
                            print("Related commits: none found in last 50 commits.")
                        print("═" * 60)

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
