"""
OpenObserve Push Service

Pushes custom log streams to OpenObserve via its Loki-compatible HTTP push API.
Replaces the former loki_push_service.py. OpenObserve speaks the same Loki push
protocol at /api/{org}/loki/api/v1/push, so the payload format is unchanged.

Primary use cases:
- forwarding browser console logs from admin users so they appear alongside
  server-side logs in OpenObserve (called by admin_client_logs route)
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
TEST_RUNS_STREAM = "test-runs"

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
    Service for pushing custom log entries to OpenObserve via its Loki-compatible push API.

    OpenObserve accepts the same JSON format as Loki's /loki/api/v1/push endpoint.
    Labels become searchable fields; values are [nanosecond-timestamp, log-line] pairs.
    """

    def __init__(self) -> None:
        self.base_url = "http://openobserve:5080"
        self.org = OPENOBSERVE_ORG
        self.server_env = os.getenv("SERVER_ENVIRONMENT", "development").lower()
        self._email = os.getenv("OPENOBSERVE_ROOT_EMAIL", "")
        self._password = os.getenv("OPENOBSERVE_ROOT_PASSWORD", "")

    def _auth(self) -> aiohttp.BasicAuth:
        return aiohttp.BasicAuth(self._email, self._password)

    async def push_client_logs(
        self,
        entries: List[Dict[str, Any]],
        user_email: str,
        metadata: Dict[str, str],
    ) -> bool:
        """
        Push a batch of client console log entries to OpenObserve.

        Entries are grouped by level into separate streams so level-based
        filtering works efficiently. OpenObserve's Loki-compat endpoint returns
        204 No Content on success, identical to Loki.

        Args:
            entries: List of log entries with 'timestamp' (ms epoch), 'level', 'message'
            user_email: Admin user identifier (username used as label)
            metadata: Client environment dict with 'userAgent', 'pageUrl', 'tabId'
        """
        if not entries:
            return True

        try:
            streams_by_level: Dict[str, List[List[str]]] = {}

            for entry in entries:
                level = entry.get("level", "log")
                if level == "log":
                    level = "info"

                timestamp_ms = entry.get("timestamp", 0)
                message = entry.get("message", "")
                timestamp_ns = str(int(timestamp_ms * 1_000_000))

                page_url = metadata.get("pageUrl", "")
                tab_id = metadata.get("tabId", "")
                formatted_message = f"[tab={tab_id}] [{page_url}] {message}"

                streams_by_level.setdefault(level, []).append([timestamp_ns, formatted_message])

            # Truncate user_agent to avoid exceeding OpenObserve label size limits
            user_agent = metadata.get("userAgent", "")[:200]
            device_type = derive_device_type(user_agent)

            streams = []
            for level, values in streams_by_level.items():
                streams.append({
                    "stream": {
                        "job": "client-console",
                        "level": level,
                        "user_email": user_email,
                        "server_env": self.server_env,
                        "source": "browser",
                        "user_agent": user_agent,
                        # Stable device-type label derived from UA — enables
                        # simple equality filters like device_type='iphone'
                        # without UA string parsing in SQL queries.
                        "device_type": device_type,
                    },
                    "values": values,
                })

            payload = {"streams": streams}

            # OpenObserve Loki-compatible push endpoint
            url = f"{self.base_url}/api/{self.org}/loki/api/v1/push"
            timeout = aiohttp.ClientTimeout(total=10)

            async with aiohttp.ClientSession(timeout=timeout, auth=self._auth()) as session:
                async with session.post(
                    url,
                    json=payload,
                    headers={"Content-Type": "application/json"},
                ) as response:
                    if response.status == 204:
                        return True
                    else:
                        error_text = await response.text()
                        logger.error(
                            f"OpenObserve push failed (status={response.status}): {error_text[:300]}"
                        )
                        return False

        except Exception as e:
            logger.error(f"Error pushing client logs to OpenObserve: {e}", exc_info=True)
            return False


    async def push_issue_logs(
        self,
        logs_text: str,
        issue_id: str,
        user_id: str,
        metadata: Dict[str, str],
    ) -> bool:
        """
        Push the console log snapshot captured at issue-report time to OpenObserve.

        This is a one-shot push triggered when any authenticated user submits an
        issue report. The logs are tagged with the issue_id so they can be
        correlated with the Directus issue record.

        Args:
            logs_text: Pre-formatted log text from logCollector.getLogsAsText()
            issue_id: The Directus issue record ID returned by /v1/settings/issues
            user_id: The authenticated user's ID (user_id from profile)
            metadata: Client environment dict with 'userAgent', 'pageUrl'
        """
        if not logs_text or not logs_text.strip():
            return True

        try:
            timestamp_ns = str(int(__import__('time').time() * 1_000_000_000))
            page_url = metadata.get("pageUrl", "")
            user_agent = metadata.get("userAgent", "")

            formatted_message = (
                f"[issue_id={issue_id}] [user={user_id}] "
                f"[page={page_url}] [ua={user_agent[:80]}]\n{logs_text}"
            )

            payload = {
                "streams": [
                    {
                        "stream": {
                            "job": "client-issue-report",
                            "issue_id": issue_id,
                            "user_id": user_id,
                            "server_env": self.server_env,
                            "source": "browser",
                        },
                        "values": [[timestamp_ns, formatted_message]],
                    }
                ]
            }

            url = f"{self.base_url}/api/{self.org}/loki/api/v1/push"
            timeout = aiohttp.ClientTimeout(total=10)

            async with aiohttp.ClientSession(timeout=timeout, auth=self._auth()) as session:
                async with session.post(
                    url,
                    json=payload,
                    headers={"Content-Type": "application/json"},
                ) as response:
                    if response.status == 204:
                        return True
                    else:
                        error_text = await response.text()
                        logger.error(
                            f"OpenObserve issue-log push failed (status={response.status}): {error_text[:300]}"
                        )
                        return False

        except Exception as e:
            logger.error(f"Error pushing issue logs to OpenObserve: {e}", exc_info=True)
            return False

    async def push_test_run_summary(self, summary_payload: Dict[str, Any]) -> bool:
        """
        Push one daily test-run summary event into the dedicated test-runs stream.

        The stream labels are intentionally low-cardinality for query performance.
        High-cardinality details (failed test names/errors) remain in the log body.
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

            timestamp_ns = str(int(time.time() * 1_000_000_000))
            body = {
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
                "failed_tests": failed_tests,
                "top_failures": top_failures,
            }

            payload = {
                "streams": [
                    {
                        "stream": {
                            "job": "test-runs",
                            "suite": suite,
                            "status": status,
                            "environment": environment,
                            "git_branch": git_branch,
                            "server_env": self.server_env,
                            "source": "daily-test-runner",
                        },
                        "values": [[timestamp_ns, json.dumps(body)]],
                    }
                ]
            }

            # Dedicated OpenObserve stream path for daily test-run records.
            url = f"{self.base_url}/api/{self.org}/{TEST_RUNS_STREAM}/loki/api/v1/push"
            timeout = aiohttp.ClientTimeout(total=10)

            async with aiohttp.ClientSession(timeout=timeout, auth=self._auth()) as session:
                async with session.post(
                    url,
                    json=payload,
                    headers={"Content-Type": "application/json"},
                ) as response:
                    if response.status == 204:
                        return True

                    error_text = await response.text()
                    logger.error(
                        f"OpenObserve test-run push failed (status={response.status}): {error_text[:300]}"
                    )
                    return False

        except Exception as e:
            logger.error(f"Error pushing test run summary to OpenObserve: {e}", exc_info=True)
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
