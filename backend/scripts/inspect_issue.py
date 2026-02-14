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
    docker exec api python /app/backend/scripts/inspect_issue.py <issue_id>
    docker exec api python /app/backend/scripts/inspect_issue.py abc12345-6789-0123-4567-890123456789

Options:
    --no-logs           Skip fetching the full YAML report from S3
    --full-logs         Show all log lines (by default only warnings/errors with context are shown)
    --json              Output as JSON instead of formatted text
    --list              List recent issues (most recent first)
    --list-limit N      Number of issues to list (default: 20)
    --search TEXT       Search issues by title/description (used with --list)
    --include-processed Include processed issues in --list results
"""

import asyncio
import argparse
import logging
import os
import sys
import json
from datetime import datetime
from typing import Dict, Any, List, Optional

# Add the backend directory to the Python path
sys.path.insert(0, '/app/backend')

from backend.core.api.app.services.directus.directus import DirectusService
from backend.core.api.app.services.cache import CacheService
from backend.core.api.app.utils.encryption import EncryptionService
from backend.core.api.app.utils.secrets_manager import SecretsManager
from backend.core.api.app.services.s3.service import S3UploadService
from backend.core.api.app.services.s3.config import get_bucket_name

# Configure logging
logging.basicConfig(
    level=logging.WARNING,  # Only show warnings and errors from libraries
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)

# Set our script logger to INFO level
script_logger = logging.getLogger('inspect_issue')
script_logger.setLevel(logging.INFO)

# Suppress verbose logging from httpx and other libraries
logging.getLogger('httpx').setLevel(logging.WARNING)
logging.getLogger('httpcore').setLevel(logging.WARNING)
logging.getLogger('backend').setLevel(logging.WARNING)
logging.getLogger('botocore').setLevel(logging.WARNING)
logging.getLogger('boto3').setLevel(logging.WARNING)


def format_timestamp(ts: Optional[str]) -> str:
    """
    Format a timestamp string to human-readable format.

    Args:
        ts: Timestamp string (ISO format) or None

    Returns:
        Formatted datetime string or "N/A" if timestamp is None/invalid
    """
    if not ts:
        return "N/A"
    try:
        if isinstance(ts, int):
            dt = datetime.fromtimestamp(ts)
        else:
            # Try parsing as ISO format string
            dt = datetime.fromisoformat(str(ts).replace('Z', '+00:00'))
        return dt.strftime("%Y-%m-%d %H:%M:%S")
    except Exception:
        return str(ts)


def censor_email(email: Optional[str]) -> Optional[str]:
    """
    Censor an email address to protect user privacy.

    Shows only the first 2 characters of the local part and the full domain.
    Example: "john.doe@example.com" -> "jo***@example.com"

    Args:
        email: Full email address string, or None

    Returns:
        Censored email string, or None if input is None
    """
    if not email or '@' not in email:
        return email
    local, domain = email.rsplit('@', 1)
    if len(local) <= 2:
        censored_local = local[0] + '***' if local else '***'
    else:
        censored_local = local[:2] + '***'
    return f"{censored_local}@{domain}"


def truncate_string(s: str, max_len: int = 80) -> str:
    """
    Truncate a string to max_len characters, adding ellipsis if truncated.

    Args:
        s: String to truncate
        max_len: Maximum length (default: 80)

    Returns:
        Truncated string with ellipsis if needed
    """
    if not s:
        return "N/A"
    if len(s) <= max_len:
        return s
    return s[:max_len - 3] + "..."


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
        'sort': '-created_at',
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

            lines.append("")
            lines.append(f"  {i:3}. {status_emoji} [{issue_id[:8]}...]  {created_at}")
            lines.append(f"       Title:     {truncate_string(title, 70)}")
            lines.append(f"       Email:     {truncate_string(email, 50)}")
            lines.append(f"       Reported:  {timestamp}")
            lines.append(f"       Processed: {processed}")

            # Show if S3 report exists
            has_s3 = "✓" if issue.get('encrypted_issue_report_yaml_s3_key') else "✗"
            lines.append(f"       S3 Report: {has_s3}")

    lines.append("")
    lines.append("=" * 100)
    lines.append("")

    return "\n".join(lines)


def format_detail_output(
    issue_id: str,
    issue: Optional[Dict[str, Any]],
    decrypted: Dict[str, Optional[str]],
    s3_report: Optional[Dict[str, Any]],
    full_logs: bool = False
) -> str:
    """
    Format the issue inspection results as human-readable text.

    By default, log sections (console logs and docker compose logs) are filtered to show
    only WARNING/ERROR/CRITICAL lines with 3 lines of surrounding context. Use full_logs=True
    to show all log lines unfiltered.

    Args:
        issue_id: The issue ID
        issue: Raw issue metadata from Directus
        decrypted: Dictionary of decrypted field values
        s3_report: Parsed YAML report from S3 (or None)
        full_logs: If True, show all log lines; if False, filter to errors/warnings only

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
        lines.append(f"  Description:       {truncate_string(issue.get('description', 'N/A'), 200)}")
        lines.append("")
        lines.append(f"  Timestamp:         {format_timestamp(issue.get('timestamp'))}")
        lines.append(f"  Created At:        {format_timestamp(issue.get('created_at'))}")
        lines.append(f"  Updated At:        {format_timestamp(issue.get('updated_at'))}")
        lines.append(f"  Processed:         {issue.get('processed', False) or False}")
        lines.append("")

        # Encrypted fields presence check
        encrypted_fields = [
            ('encrypted_contact_email', 'Contact Email'),
            ('encrypted_chat_or_embed_url', 'Chat/Embed URL'),
            ('encrypted_estimated_location', 'Estimated Location'),
            ('encrypted_device_info', 'Device Info'),
            ('encrypted_issue_report_yaml_s3_key', 'S3 Report Key'),
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
            lines.append(f"  💻 Device Info:        {truncate_string(device_info, 200)}")
        else:
            lines.append("  💻 Device Info:        N/A (not provided)")

    # ===================== FULL DESCRIPTION =====================
    # Show full description if it's longer than the truncated version above
    if issue and issue.get('description') and len(issue.get('description', '')) > 200:
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
                lines.append(f"    Device Info:      {truncate_string(str(tech_details.get('device_info')), 200)}")

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
                    lines.append(f"    {key}: {truncate_string(str(value), 150)}")
            else:
                lines.append(f"    {truncate_string(str(indexeddb), 300)}")

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
    s3_report: Optional[Dict[str, Any]]
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
        's3_report': censored_s3_report
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
        help='Show all log lines unfiltered (by default only warnings/errors with context are shown)'
    )

    args = parser.parse_args()

    # Validate arguments
    if not args.list and not args.issue_id:
        parser.error("Either provide an issue_id or use --list to list recent issues")

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
            # ===================== DETAIL MODE =====================
            script_logger.info(f"Inspecting issue: {args.issue_id}")

            # 1. Fetch issue metadata
            issue = await get_issue(directus_service, args.issue_id)

            # 2. Decrypt fields
            decrypted: Dict[str, Optional[str]] = {}
            if issue:
                decrypted = await decrypt_issue_fields(encryption_service, issue)

            # 3. Fetch S3 report (if not skipped and issue has an S3 key)
            s3_report = None
            if not args.no_logs and issue and issue.get('encrypted_issue_report_yaml_s3_key'):
                script_logger.info("Fetching S3 YAML report...")
                try:
                    await secrets_manager.initialize()
                    s3_service = S3UploadService(secrets_manager=secrets_manager)
                    await s3_service.initialize()
                    s3_report = await fetch_s3_report(encryption_service, s3_service, issue)
                except Exception as e:
                    script_logger.warning(f"Failed to initialize S3 service: {e}")

            # 4. Format and output results
            if args.json:
                print(format_detail_json(args.issue_id, issue, decrypted, s3_report))
            else:
                print(format_detail_output(args.issue_id, issue, decrypted, s3_report, full_logs=args.full_logs))

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
