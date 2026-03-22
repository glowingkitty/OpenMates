#!/usr/bin/env python3
"""
Issue Triage Script
===================
Fetches all reported issues from the production admin API, decrypts contact info,
and generates a CSV file for manual triage and categorization.

Output CSV includes empty columns for status, category, and notes so you can
fill them in during manual review.

Usage:
    # With CLI argument
    python scripts/triage_issues.py --api-key YOUR_ADMIN_API_KEY

    # With environment variable
    export ADMIN_API_KEY=YOUR_ADMIN_API_KEY
    python scripts/triage_issues.py

    # Custom API URL (e.g. dev server)
    python scripts/triage_issues.py --api-key KEY --api-url https://api.dev.openmates.org

    # Dry run (test connection, show stats only, no CSV)
    python scripts/triage_issues.py --api-key KEY --dry-run
"""

import argparse
import csv
import json
import os
import ssl
import sys
import urllib.error
import urllib.request
from datetime import datetime, timezone
from pathlib import Path


# ---------------------------------------------------------------------------
# Configuration
# ---------------------------------------------------------------------------

DEFAULT_API_URL = "https://api.openmates.org"
OUTPUT_DIR = Path(__file__).parent / "triage_output"
PAGE_SIZE = 200  # Max allowed by the admin API


# ---------------------------------------------------------------------------
# API helpers (stdlib only, no requests/httpx)
# ---------------------------------------------------------------------------

def make_request(url: str, api_key: str, timeout: int = 30) -> dict:
    """
    Make an authenticated GET request to the admin debug API.
    Returns parsed JSON response.
    """
    req = urllib.request.Request(url)
    req.add_header("Authorization", f"Bearer {api_key}")
    req.add_header("Accept", "application/json")

    # Create SSL context that works on most systems
    ctx = ssl.create_default_context()

    try:
        with urllib.request.urlopen(req, timeout=timeout, context=ctx) as resp:
            body = resp.read().decode("utf-8")
            return json.loads(body)
    except urllib.error.HTTPError as e:
        body = e.read().decode("utf-8", errors="replace")
        print(f"  HTTP {e.code}: {body[:500]}", file=sys.stderr)
        raise
    except urllib.error.URLError as e:
        print(f"  Connection error: {e.reason}", file=sys.stderr)
        raise


def fetch_all_issues(api_url: str, api_key: str) -> list[dict]:
    """
    Paginate through all issues (including processed) and return the full list.
    The admin API returns issues sorted by created_at descending (newest first).
    """
    all_issues: list[dict] = []
    offset = 0

    while True:
        url = (
            f"{api_url}/v1/admin/debug/issues"
            f"?include_processed=true&limit={PAGE_SIZE}&offset={offset}"
        )
        print(f"  Fetching issues (offset={offset}, limit={PAGE_SIZE})...")

        data = make_request(url, api_key)
        issues = data.get("issues", [])

        if not issues:
            break

        all_issues.extend(issues)
        print(f"  Got {len(issues)} issues (total so far: {len(all_issues)})")

        # If we got fewer than PAGE_SIZE, we've reached the end
        if len(issues) < PAGE_SIZE:
            break

        offset += PAGE_SIZE

    return all_issues


# ---------------------------------------------------------------------------
# Processing helpers
# ---------------------------------------------------------------------------

def compute_age_days(timestamp_str: str) -> int:
    """Compute the age in days from a timestamp string to now."""
    if not timestamp_str:
        return -1

    now = datetime.now(timezone.utc)

    # Try common Directus timestamp formats
    for fmt in [
        "%Y-%m-%dT%H:%M:%S.%f%z",
        "%Y-%m-%dT%H:%M:%S%z",
        "%Y-%m-%dT%H:%M:%S.%f",
        "%Y-%m-%dT%H:%M:%S",
        "%Y-%m-%d %H:%M:%S.%f%z",
        "%Y-%m-%d %H:%M:%S%z",
        "%Y-%m-%d %H:%M:%S",
    ]:
        try:
            dt = datetime.strptime(timestamp_str, fmt)
            # If no timezone info, assume UTC
            if dt.tzinfo is None:
                dt = dt.replace(tzinfo=timezone.utc)
            return max(0, (now - dt).days)
        except ValueError:
            continue

    return -1


def truncate(text: str | None, max_len: int = 100) -> str:
    """Truncate text to max_len chars, adding ellipsis if needed."""
    if not text:
        return ""
    # Collapse newlines for CSV readability
    clean = text.replace("\n", " ").replace("\r", "").strip()
    if len(clean) <= max_len:
        return clean
    return clean[: max_len - 3] + "..."


def format_timestamp(ts: str | None) -> str:
    """Format a timestamp for human readability in the CSV."""
    if not ts:
        return ""
    # Strip microseconds and timezone for cleaner display
    try:
        for fmt in [
            "%Y-%m-%dT%H:%M:%S.%f%z",
            "%Y-%m-%dT%H:%M:%S%z",
            "%Y-%m-%dT%H:%M:%S.%f",
            "%Y-%m-%dT%H:%M:%S",
        ]:
            try:
                dt = datetime.strptime(ts, fmt)
                return dt.strftime("%Y-%m-%d %H:%M")
            except ValueError:
                continue
    except Exception:
        pass
    return ts


# ---------------------------------------------------------------------------
# CSV generation
# ---------------------------------------------------------------------------

CSV_HEADERS = [
    "id",
    "title",
    "description_preview",
    "has_contact_email",
    "contact_email",
    "chat_or_embed_url",
    "reported_at",
    "created_at",
    "age_days",
    "processed",
    # Empty columns for manual triage:
    "status",
    "category",
    "notes",
]


def issue_to_row(issue: dict) -> dict:
    """Convert an API issue object to a CSV row dict."""
    email = issue.get("contact_email") or ""
    reported = issue.get("timestamp", "")
    created = issue.get("created_at", "")

    return {
        "id": issue.get("id", ""),
        "title": truncate(issue.get("title", ""), 150),
        "description_preview": truncate(issue.get("description"), 100),
        "has_contact_email": "Yes" if email else "No",
        "contact_email": email,
        "chat_or_embed_url": issue.get("chat_or_embed_url") or "",
        "reported_at": format_timestamp(reported),
        "created_at": format_timestamp(created),
        "age_days": compute_age_days(reported or created),
        "processed": "Yes" if issue.get("processed") else "No",
        "status": "",
        "category": "",
        "notes": "",
    }


def write_csv(issues: list[dict], output_path: Path) -> None:
    """Write issues to a CSV file."""
    output_path.parent.mkdir(parents=True, exist_ok=True)

    with open(output_path, "w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=CSV_HEADERS)
        writer.writeheader()
        for issue in issues:
            writer.writerow(issue_to_row(issue))


# ---------------------------------------------------------------------------
# Summary stats
# ---------------------------------------------------------------------------

def print_summary(issues: list[dict]) -> None:
    """Print triage summary statistics to stdout."""
    total = len(issues)
    with_email = sum(1 for i in issues if i.get("contact_email"))
    without_email = total - with_email
    processed = sum(1 for i in issues if i.get("processed"))
    unprocessed = total - processed

    # Age distribution
    ages = []
    for i in issues:
        ts = i.get("timestamp") or i.get("created_at", "")
        age = compute_age_days(ts)
        if age >= 0:
            ages.append(age)

    age_buckets = {
        "< 7 days": 0,
        "7-14 days": 0,
        "14-30 days": 0,
        "30-60 days": 0,
        "60-90 days": 0,
        "> 90 days": 0,
    }
    for age in ages:
        if age < 7:
            age_buckets["< 7 days"] += 1
        elif age < 14:
            age_buckets["7-14 days"] += 1
        elif age < 30:
            age_buckets["14-30 days"] += 1
        elif age < 60:
            age_buckets["30-60 days"] += 1
        elif age < 90:
            age_buckets["60-90 days"] += 1
        else:
            age_buckets["> 90 days"] += 1

    # With/without chat URL
    with_url = sum(1 for i in issues if i.get("chat_or_embed_url"))

    print("\n" + "=" * 60)
    print("  ISSUE TRIAGE SUMMARY")
    print("=" * 60)
    print(f"  Total issues:        {total}")
    print(f"  With contact email:  {with_email}")
    print(f"  Without email:       {without_email}")
    print(f"  With chat/embed URL: {with_url}")
    print(f"  Already processed:   {processed}")
    print(f"  Unprocessed:         {unprocessed}")
    print()
    print("  Age distribution:")
    for bucket, count in age_buckets.items():
        bar = "#" * count
        print(f"    {bucket:>12s}: {count:3d}  {bar}")
    print("=" * 60)


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def main() -> None:
    parser = argparse.ArgumentParser(
        description="Fetch and triage issue reports from the OpenMates admin API.",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=__doc__,
    )
    parser.add_argument(
        "--api-key",
        default=os.environ.get("ADMIN_API_KEY", ""),
        help="Admin API key (or set ADMIN_API_KEY env var)",
    )
    parser.add_argument(
        "--api-url",
        default=DEFAULT_API_URL,
        help=f"Base API URL (default: {DEFAULT_API_URL})",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Fetch and show stats only, don't write CSV",
    )
    parser.add_argument(
        "--output",
        type=str,
        default="",
        help="Custom output CSV path (default: auto-generated in scripts/triage_output/)",
    )

    args = parser.parse_args()

    if not args.api_key:
        print(
            "Error: No API key provided.\n"
            "  Use --api-key KEY or set ADMIN_API_KEY environment variable.",
            file=sys.stderr,
        )
        sys.exit(1)

    api_url = args.api_url.rstrip("/")

    print(f"Fetching issues from {api_url}...")
    print()

    try:
        issues = fetch_all_issues(api_url, args.api_key)
    except Exception as e:
        print(f"\nFailed to fetch issues: {e}", file=sys.stderr)
        sys.exit(1)

    if not issues:
        print("No issues found.")
        sys.exit(0)

    # Print summary
    print_summary(issues)

    # Write CSV (unless dry run)
    if args.dry_run:
        print("\n  [Dry run] Skipping CSV generation.")
    else:
        if args.output:
            output_path = Path(args.output)
        else:
            today = datetime.now().strftime("%Y-%m-%d")
            output_path = OUTPUT_DIR / f"issues_triage_{today}.csv"

        write_csv(issues, output_path)
        print(f"\n  CSV written to: {output_path}")
        print(f"  Total rows: {len(issues)}")
        print()
        print("  Next steps:")
        print("  1. Open the CSV in a spreadsheet app")
        print("  2. Fill in 'status' column: likely_fixed | needs_investigation | feature_request | duplicate | stale | closed")
        print("  3. Fill in 'category' column: bug | ai_quality | performance | auth | payment | ui | other")
        print("  4. Add any notes in the 'notes' column")
        print("  5. Issues with contact emails can be responded to in Phase 2")


if __name__ == "__main__":
    main()
