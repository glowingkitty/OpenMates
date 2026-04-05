"""
OpenObserve Push Service

Pushes custom log streams to OpenObserve via its native JSON push API.
Each stream is a separate URL: /api/{org}/{stream_name}/_json.

The Loki-compatible endpoint (/api/{org}/loki/api/v1/push) was used previously
but silently drops data in OpenObserve v0.70+. The native JSON API is reliable
and simpler — each record is a flat JSON object with a _timestamp field (us).

Primary use cases:
- forwarding browser console logs from admin users so they appear alongside
  server-side logs in OpenObserve (called by admin_client_logs route)
- forwarding anonymized ephemeral logs from all authenticated users for
  error-triggered retention (48h ephemeral → 14d on error)
- forwarding normalized daily test-run summaries into the dedicated test-runs
  stream for flaky-test debugging and trend analysis

Architecture context: docs/architecture/admin-console-log-forwarding.md
Tests: None (non-critical debug infrastructure)
"""

import logging
import os
import re
import json
import time
import aiohttp
from typing import List, Dict, Any

logger = logging.getLogger(__name__)

OPENOBSERVE_ORG = "default"

# Stream names (underscores, not hyphens — O2 normalizes hyphens to underscores)
STREAM_CLIENT_CONSOLE = "client_console"
STREAM_CLIENT_EPHEMERAL = "client_console_ephemeral"
STREAM_CLIENT_ERROR_CONTEXT = "client_console_error_context"
STREAM_CLIENT_ISSUE_REPORT = "client_issue_report"
STREAM_TEST_RUNS = "test_runs"
STREAM_TEST_EVENTS = "test_events"

# Ordered rules: first match wins. Keep specific patterns before generic ones.
_DEVICE_PATTERNS: list[tuple[re.Pattern[str], str]] = [
    (re.compile(r"iPhone", re.I), "iphone"),
    (re.compile(r"iPad", re.I), "ipad"),
    (re.compile(r"Android", re.I), "android"),
    (re.compile(r"Windows Phone", re.I), "windows-phone"),
    (re.compile(r"Windows", re.I), "windows"),
    (re.compile(r"Macintosh|Mac OS X", re.I), "mac"),
    (re.compile(r"Linux", re.I), "linux"),
    (re.compile(r"CrOS", re.I), "chromeos"),
]


def derive_device_type(user_agent: str) -> str:
    """
    Derive a short, searchable device-type label from a User-Agent string.

    Returns one of: iphone, ipad, android, windows-phone, windows, mac, linux,
    chromeos, or 'unknown'.  Used as a stable OpenObserve stream label so every
    admin session's logs can be filtered by device without needing to parse UA
    strings in SQL queries.
    """
    for pattern, label in _DEVICE_PATTERNS:
        if pattern.search(user_agent):
            return label
    return "unknown"


class OpenObservePushService:
    """
    Service for pushing custom log entries to OpenObserve via its native JSON API.

    Each push targets a specific stream: /api/{org}/{stream_name}/_json.
    Records are flat JSON objects with a _timestamp field (microseconds since epoch).
    All fields become searchable columns in OpenObserve.
    """

    def __init__(self) -> None:
        self.base_url = "http://openobserve:5080"
        self.org = OPENOBSERVE_ORG
        self.server_env = os.getenv("SERVER_ENVIRONMENT", "development").lower()
        self._email = os.getenv("OPENOBSERVE_ROOT_EMAIL", "")
        self._password = os.getenv("OPENOBSERVE_ROOT_PASSWORD", "")

    def _auth(self) -> aiohttp.BasicAuth:
        return aiohttp.BasicAuth(self._email, self._password)

    async def _push_to_stream(
        self,
        stream_name: str,
        records: List[Dict[str, Any]],
        timeout_seconds: int = 10,
    ) -> bool:
        """
        Push records to an OpenObserve stream via the native JSON API.

        Args:
            stream_name: Target stream (e.g. 'client_console_ephemeral')
            records: List of flat JSON objects, each with '_timestamp' (microseconds)
            timeout_seconds: Request timeout
        """
        if not records:
            return True

        url = f"{self.base_url}/api/{self.org}/{stream_name}/_json"
        timeout = aiohttp.ClientTimeout(total=timeout_seconds)

        try:
            async with aiohttp.ClientSession(timeout=timeout, auth=self._auth()) as session:
                async with session.post(
                    url,
                    json=records,
                    headers={"Content-Type": "application/json"},
                ) as response:
                    if response.status == 200:
                        return True
                    else:
                        error_text = await response.text()
                        logger.error(
                            f"OpenObserve push to {stream_name} failed "
                            f"(status={response.status}): {error_text[:300]}"
                        )
                        return False
        except Exception as e:
            logger.error(
                f"Error pushing to OpenObserve stream {stream_name}: {e}",
                exc_info=True,
            )
            return False

    async def push_client_logs(
        self,
        entries: List[Dict[str, Any]],
        user_email: str,
        metadata: Dict[str, str],
    ) -> bool:
        """
        Push a batch of client console log entries to OpenObserve.

        Args:
            entries: List of log entries with 'timestamp' (ms epoch), 'level', 'message'
            user_email: Admin user identifier (username used as label)
            metadata: Client environment dict with 'userAgent', 'pageUrl', 'tabId'
        """
        if not entries:
            return True

        user_agent = metadata.get("userAgent", "")[:200]
        device_type = derive_device_type(user_agent)
        page_url = metadata.get("pageUrl", "")
        tab_id = metadata.get("tabId", "")

        records = []
        for entry in entries:
            level = entry.get("level", "log")
            if level == "log":
                level = "info"

            timestamp_ms = entry.get("timestamp", 0)
            message = entry.get("message", "")
            formatted_message = f"[tab={tab_id}] [{page_url}] {message}"

            records.append({
                "_timestamp": int(timestamp_ms * 1_000),  # ms → microseconds
                "level": level,
                "message": formatted_message,
                "user_email": user_email,
                "server_env": self.server_env,
                "source": "browser",
                "user_agent": user_agent,
                "device_type": device_type,
                "job": "client-console",
            })

        return await self._push_to_stream(STREAM_CLIENT_CONSOLE, records)

    async def push_ephemeral_client_logs(
        self,
        entries: List[Dict[str, Any]],
        session_pseudonym: str,
        metadata: Dict[str, str],
    ) -> bool:
        """
        Push anonymized client console logs to the ephemeral stream (48h retention).

        Unlike push_client_logs(), this method does NOT include user_email or
        user_id. The only identifier is the random per-session session_pseudonym
        which cannot be linked to a user unless they include it in an issue report.

        Args:
            entries: Log entries with 'timestamp' (ms), 'level', 'message'
            session_pseudonym: Random UUIDv4 per browser page load
            metadata: Client metadata (userAgent, pageUrl, tabId)
        """
        if not entries:
            return True

        user_agent = metadata.get("userAgent", "")[:200]
        device_type = derive_device_type(user_agent)
        page_url = metadata.get("pageUrl", "")
        tab_id = metadata.get("tabId", "")

        records = []
        for entry in entries:
            level = entry.get("level", "log")
            if level == "log":
                level = "info"

            timestamp_ms = entry.get("timestamp", 0)
            message = entry.get("message", "")
            formatted_message = f"[tab={tab_id}] [{page_url}] {message}"

            records.append({
                "_timestamp": int(timestamp_ms * 1_000),  # ms → microseconds
                "level": level,
                "message": formatted_message,
                "session_pseudonym": session_pseudonym,
                "device_type": device_type,
                "server_env": self.server_env,
                "source": "browser",
                "job": "client-console-ephemeral",
            })

        return await self._push_to_stream(STREAM_CLIENT_EPHEMERAL, records)

    async def push_error_context_logs(
        self,
        entries: List[Dict[str, Any]],
        session_pseudonym: str,
    ) -> bool:
        """
        Push promoted error-context logs to the long-retention stream (14d).

        Called by the ephemeral log promotion Celery task when a session has
        error-level logs. Copies the full session context (all log levels)
        from the ephemeral stream to the error-context stream for debugging.

        Args:
            entries: Log entries with '_timestamp' (us) and 'message' (from O2 query)
            session_pseudonym: The session whose logs are being promoted
        """
        if not entries:
            return True

        records = []
        for entry in entries:
            # Entries from O2 queries already have _timestamp in microseconds
            timestamp_us = entry.get("_timestamp", int(time.time() * 1_000_000))
            message = str(entry.get("message", ""))
            records.append({
                "_timestamp": int(timestamp_us),
                "message": message,
                "session_pseudonym": session_pseudonym,
                "server_env": self.server_env,
                "source": "promoted",
                "job": "client-console-error-context",
            })

        return await self._push_to_stream(
            STREAM_CLIENT_ERROR_CONTEXT, records, timeout_seconds=30,
        )

    async def push_issue_logs(
        self,
        logs_text: str,
        issue_id: str,
        user_id: str,
        metadata: Dict[str, str],
    ) -> bool:
        """
        Push the console log snapshot captured at issue-report time to OpenObserve.

        One-shot push triggered when any authenticated user submits an issue report.
        Tagged with the issue_id for correlation with the Directus issue record.

        Args:
            logs_text: Pre-formatted log text from logCollector.getLogsAsText()
            issue_id: The Directus issue record ID
            user_id: The authenticated user's ID
            metadata: Client environment dict with 'userAgent', 'pageUrl'
        """
        if not logs_text or not logs_text.strip():
            return True

        page_url = metadata.get("pageUrl", "")
        user_agent = metadata.get("userAgent", "")

        formatted_message = (
            f"[issue_id={issue_id}] [user={user_id}] "
            f"[page={page_url}] [ua={user_agent[:80]}]\n{logs_text}"
        )

        records = [{
            "_timestamp": int(time.time() * 1_000_000),
            "message": formatted_message,
            "issue_id": issue_id,
            "user_id": user_id,
            "server_env": self.server_env,
            "source": "browser",
            "job": "client-issue-report",
        }]

        return await self._push_to_stream(STREAM_CLIENT_ISSUE_REPORT, records)

    async def push_debug_session_logs(
        self,
        entries: List[Dict[str, Any]],
        debugging_id: str,
        user_id: str,
        metadata: Dict[str, str],
    ) -> bool:
        """
        Push console log entries from a user debug log sharing session.

        Uses the same stream as admin log forwarding, but with a debugging_id
        field instead of user_email. Allows querying via `debug.py logs --debug-id <ID>`.

        Args:
            entries: Log entries with 'timestamp' (ms), 'level', 'message'
            debugging_id: Short debug session ID (e.g. 'dbg-a3f2c8')
            user_id: Authenticated user's UUID
            metadata: Client metadata (userAgent, pageUrl, tabId)
        """
        if not entries:
            return True

        user_agent = metadata.get("userAgent", "")[:200]
        device_type = derive_device_type(user_agent)
        page_url = metadata.get("pageUrl", "")
        tab_id = metadata.get("tabId", "")

        records = []
        for entry in entries:
            level = entry.get("level", "log")
            if level == "log":
                level = "info"

            timestamp_ms = entry.get("timestamp", 0)
            message = entry.get("message", "")
            formatted_message = f"[tab={tab_id}] [{page_url}] {message}"

            records.append({
                "_timestamp": int(timestamp_ms * 1_000),  # ms → microseconds
                "level": level,
                "message": formatted_message,
                "debugging_id": debugging_id,
                "user_id": user_id,
                "server_env": self.server_env,
                "source": "browser",
                "user_agent": user_agent,
                "device_type": device_type,
                "job": "client-console",
            })

        return await self._push_to_stream(STREAM_CLIENT_CONSOLE, records)

    async def push_test_run_summary(self, summary_payload: Dict[str, Any]) -> bool:
        """
        Push one daily test-run summary event into the dedicated test-runs stream.

        Low-cardinality fields are top-level for efficient filtering.
        High-cardinality details (failed test names/errors) are in the message body.
        """
        try:
            run_id = str(summary_payload.get("run_id", ""))
            suite = str(summary_payload.get("suite", "daily"))
            status = str(summary_payload.get("status", "unknown"))
            environment = str(summary_payload.get("environment", self.server_env))
            git_sha = str(summary_payload.get("git_sha", ""))
            git_branch = str(summary_payload.get("git_branch", ""))
            duration_seconds = int(summary_payload.get("duration_seconds", 0))
            total = int(summary_payload.get("total", 0))
            passed = int(summary_payload.get("passed", 0))
            failed = int(summary_payload.get("failed", 0))
            skipped = int(summary_payload.get("skipped", 0))
            not_started = int(summary_payload.get("not_started", 0))
            failed_tests = summary_payload.get("failed_tests", [])

            top_failures: list[dict[str, Any]] = []
            for failure in failed_tests[:10]:
                top_failures.append(
                    {
                        "suite": str(failure.get("suite", "")),
                        "name": str(failure.get("name", "")),
                        "error": str(failure.get("error", ""))[:400],
                    }
                )

            records = [{
                "_timestamp": int(time.time() * 1_000_000),
                "run_id": run_id,
                "suite": suite,
                "status": status,
                "environment": environment,
                "git_sha": git_sha,
                "git_branch": git_branch,
                "duration_seconds": duration_seconds,
                "total": total,
                "passed": passed,
                "failed": failed,
                "skipped": skipped,
                "not_started": not_started,
                "failed_tests": json.dumps(failed_tests),
                "top_failures": json.dumps(top_failures),
                "server_env": self.server_env,
                "source": "daily-test-runner",
                "job": "test-runs",
            }]

            return await self._push_to_stream(STREAM_TEST_RUNS, records)

        except Exception as e:
            logger.error(f"Error pushing test run summary to OpenObserve: {e}", exc_info=True)
            return False

    async def push_test_event(self, event_payload: Dict[str, Any]) -> bool:
        """
        Push a single test lifecycle event (spec started, passed, failed, suite summary)
        into the dedicated test-events stream.

        Called by the Playwright api-reporter via /internal/openobserve/push-test-event.
        """
        try:
            event_type = str(event_payload.get("event_type", "test_end"))
            status = str(event_payload.get("status", "unknown"))
            environment = str(event_payload.get("environment", self.server_env))
            worker_slot = str(event_payload.get("worker_slot", "0"))
            git_branch = str(event_payload.get("git_branch", ""))
            test_file = str(event_payload.get("test_file", ""))
            test_name = str(event_payload.get("test_name", ""))
            duration_ms = int(event_payload.get("duration_ms", 0))
            error_message = str(event_payload.get("error_message", ""))[:800]
            run_id = str(event_payload.get("run_id", ""))
            total = event_payload.get("total")
            passed = event_payload.get("passed")
            failed = event_payload.get("failed")
            skipped = event_payload.get("skipped")

            # Console log aggregation fields (from console-monitor.ts via api-reporter)
            total_console_messages = event_payload.get("total_console_messages")
            console_errors = event_payload.get("console_errors")
            console_warnings = event_payload.get("console_warnings")
            console_logs_top = event_payload.get("console_logs_top")

            record: Dict[str, Any] = {
                "_timestamp": int(time.time() * 1_000_000),
                "event_type": event_type,
                "test_file": test_file,
                "test_name": test_name,
                "status": status,
                "duration_ms": duration_ms,
                "worker_slot": worker_slot,
                "environment": environment,
                "git_branch": git_branch,
                "run_id": run_id,
                "server_env": self.server_env,
                "source": "playwright-reporter",
                "job": "test-events",
            }
            if error_message:
                record["error_message"] = error_message
            if total is not None:
                record["total"] = total
                record["passed"] = passed
                record["failed"] = failed
                record["skipped"] = skipped
            if total_console_messages is not None:
                record["total_console_messages"] = total_console_messages
            if console_errors:
                record["console_errors"] = json.dumps(console_errors)
            if console_warnings:
                record["console_warnings"] = json.dumps(console_warnings)
            if console_logs_top:
                record["console_logs_top"] = json.dumps(console_logs_top)

            return await self._push_to_stream(STREAM_TEST_EVENTS, [record])

        except Exception as e:
            logger.error(f"Error pushing test event to OpenObserve: {e}", exc_info=True)
            return False

    async def test_push_connection(self) -> bool:
        """Test if OpenObserve is reachable."""
        try:
            url = f"{self.base_url}/healthz"
            timeout = aiohttp.ClientTimeout(total=5)
            async with aiohttp.ClientSession(timeout=timeout) as session:
                async with session.get(url) as response:
                    return response.status == 200
        except Exception as e:
            logger.debug(f"OpenObserve push connection test failed: {e}")
            return False


# Global singleton
openobserve_push_service = OpenObservePushService()
