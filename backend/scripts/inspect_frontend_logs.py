#!/usr/bin/env python3
"""
Script to query and display browser console logs forwarded from admin users via Loki.

Admin users have their browser console logs automatically forwarded to Loki
by clientLogForwarder.ts. This script queries those logs for debugging.

Usage:
    docker exec api python /app/backend/scripts/inspect_frontend_logs.py
    docker exec api python /app/backend/scripts/inspect_frontend_logs.py --since 10
    docker exec api python /app/backend/scripts/inspect_frontend_logs.py --level error
    docker exec api python /app/backend/scripts/inspect_frontend_logs.py --user jan41139
    docker exec api python /app/backend/scripts/inspect_frontend_logs.py --search "WebSocket"
    docker exec api python /app/backend/scripts/inspect_frontend_logs.py --level error --since 60 --limit 100
    docker exec api python /app/backend/scripts/inspect_frontend_logs.py --json

Options:
    --since N       Minutes to look back (default: 30)
    --limit N       Max number of log entries to return (default: 200)
    --level LEVEL   Filter by log level: debug, info, warn, error (default: all)
    --user USER     Filter by admin username (default: all admins)
    --search TEXT   Search log message content (substring match)
    --json          Output raw JSON from Loki instead of formatted text
    --follow        Poll for new logs every 5 seconds (Ctrl+C to stop)
"""

import asyncio
import argparse
import json
import logging
import time
from datetime import datetime, timezone
from typing import Optional

import aiohttp

# Configure logging - suppress everything except our output
logging.basicConfig(level=logging.WARNING)
logger = logging.getLogger("inspect_frontend_logs")
logger.setLevel(logging.INFO)

LOKI_URL = "http://loki:3100"

# ANSI color codes for terminal output
COLORS = {
    "error": "\033[91m",   # Red
    "warn": "\033[93m",    # Yellow
    "info": "\033[92m",    # Green
    "debug": "\033[90m",   # Gray
    "reset": "\033[0m",
    "bold": "\033[1m",
    "dim": "\033[2m",
}


def colorize(text: str, color: str) -> str:
    """Wrap text in ANSI color codes."""
    return f"{COLORS.get(color, '')}{text}{COLORS['reset']}"


def format_ns_timestamp(ns_str: str) -> str:
    """Convert Loki nanosecond timestamp to human-readable format."""
    try:
        ts_seconds = int(ns_str) / 1_000_000_000
        dt = datetime.fromtimestamp(ts_seconds, tz=timezone.utc)
        return dt.strftime("%Y-%m-%d %H:%M:%S")
    except (ValueError, OSError):
        return ns_str


def build_query(level: Optional[str], user: Optional[str], search: Optional[str]) -> str:
    """Build a LogQL query string from filter options."""
    # Build label matchers
    labels = ['job="client-console"']
    if level:
        labels.append(f'level="{level}"')
    if user:
        labels.append(f'user_email="{user}"')

    query = "{" + ", ".join(labels) + "}"

    # Add content filter
    if search:
        query += f' |= "{search}"'

    return query


def print_log_entry(timestamp_ns: str, message: str, level: str, user: str) -> None:
    """Print a single formatted log entry."""
    ts = format_ns_timestamp(timestamp_ns)
    level_str = colorize(f"{level.upper():5s}", level)
    user_str = colorize(f"[{user}]", "dim")
    print(f"{colorize(ts, 'dim')} {level_str} {user_str} {message}")


async def query_loki(
    since_minutes: int,
    limit: int,
    level: Optional[str],
    user: Optional[str],
    search: Optional[str],
    as_json: bool,
    start_ns: Optional[int] = None,
) -> Optional[int]:
    """
    Query Loki for client console logs.

    Returns the latest timestamp (in nanoseconds) seen, or None if no results.
    """
    query = build_query(level, user, search)

    # Calculate time range
    if start_ns:
        start_param = str(start_ns)
    else:
        start_seconds = time.time() - (since_minutes * 60)
        start_param = str(int(start_seconds * 1_000_000_000))

    end_param = str(int(time.time() * 1_000_000_000))

    params = {
        "query": query,
        "limit": str(limit),
        "start": start_param,
        "end": end_param,
        "direction": "forward",  # Oldest first for readable output
    }

    try:
        timeout = aiohttp.ClientTimeout(total=15)
        async with aiohttp.ClientSession(timeout=timeout) as session:
            async with session.get(f"{LOKI_URL}/loki/api/v1/query_range", params=params) as resp:
                if resp.status != 200:
                    error_text = await resp.text()
                    logger.error(f"Loki query failed (HTTP {resp.status}): {error_text}")
                    return None

                data = await resp.json()
    except aiohttp.ClientError as e:
        logger.error(f"Cannot connect to Loki at {LOKI_URL}: {e}")
        logger.error("Make sure this script is running inside the API container (docker exec api ...)")
        return None

    if as_json:
        print(json.dumps(data, indent=2))
        # Still track latest timestamp for --follow mode
        latest_ns = _get_latest_ns(data)
        return latest_ns

    # Parse and display results
    results = data.get("data", {}).get("result", [])

    if not results:
        return None

    # Collect all entries with metadata, then sort by timestamp
    all_entries = []
    for stream in results:
        stream_labels = stream.get("stream", {})
        stream_level = stream_labels.get("level", "info")
        stream_user = stream_labels.get("user_email", "unknown")

        for value in stream.get("values", []):
            timestamp_ns, message = value[0], value[1]
            all_entries.append((timestamp_ns, message, stream_level, stream_user))

    # Sort by timestamp (oldest first)
    all_entries.sort(key=lambda e: int(e[0]))

    for timestamp_ns, message, entry_level, entry_user in all_entries:
        print_log_entry(timestamp_ns, message, entry_level, entry_user)

    latest_ns = int(all_entries[-1][0]) if all_entries else None
    return latest_ns


def _get_latest_ns(data: dict) -> Optional[int]:
    """Extract the latest nanosecond timestamp from a Loki response."""
    latest = None
    for stream in data.get("data", {}).get("result", []):
        for value in stream.get("values", []):
            ns = int(value[0])
            if latest is None or ns > latest:
                latest = ns
    return latest


async def follow_mode(
    since_minutes: int,
    limit: int,
    level: Optional[str],
    user: Optional[str],
    search: Optional[str],
    as_json: bool,
) -> None:
    """Continuously poll Loki for new log entries."""
    query = build_query(level, user, search)
    print(colorize(f"Following client logs: {query}", "bold"))
    print(colorize("Press Ctrl+C to stop\n", "dim"))

    # First query uses since_minutes
    latest_ns = await query_loki(since_minutes, limit, level, user, search, as_json)

    while True:
        await asyncio.sleep(5)
        # Subsequent queries start from 1ns after the last seen timestamp
        start_from = (latest_ns + 1) if latest_ns else None
        if start_from is None:
            # No results yet, keep using since_minutes window
            new_latest = await query_loki(since_minutes, limit, level, user, search, as_json)
        else:
            new_latest = await query_loki(
                since_minutes, limit, level, user, search, as_json, start_ns=start_from
            )
        if new_latest:
            latest_ns = new_latest


async def main() -> None:
    parser = argparse.ArgumentParser(
        description="Query browser console logs forwarded from admin users to Loki"
    )
    parser.add_argument("--since", type=int, default=30, help="Minutes to look back (default: 30)")
    parser.add_argument("--limit", type=int, default=200, help="Max log entries (default: 200)")
    parser.add_argument(
        "--level",
        choices=["debug", "info", "warn", "error"],
        default=None,
        help="Filter by log level",
    )
    parser.add_argument("--user", default=None, help="Filter by admin username")
    parser.add_argument("--search", default=None, help="Search log message content")
    parser.add_argument("--json", action="store_true", dest="as_json", help="Output raw JSON")
    parser.add_argument("--follow", action="store_true", help="Poll for new logs every 5s")
    args = parser.parse_args()

    query = build_query(args.level, args.user, args.search)

    if args.follow:
        try:
            await follow_mode(
                args.since, args.limit, args.level, args.user, args.search, args.as_json
            )
        except KeyboardInterrupt:
            print(colorize("\nStopped.", "dim"))
            return

    # One-shot query
    print(colorize(f"Query: {query}  (last {args.since} min, limit {args.limit})", "dim"))
    print()

    latest_ns = await query_loki(
        args.since, args.limit, args.level, args.user, args.search, args.as_json
    )

    if latest_ns is None and not args.as_json:
        print(colorize("No client console logs found for the given filters.", "dim"))
        print(colorize("Ensure an admin user has the app open in their browser.", "dim"))


if __name__ == "__main__":
    asyncio.run(main())
