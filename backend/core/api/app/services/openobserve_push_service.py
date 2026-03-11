"""
OpenObserve Push Service

Pushes custom log streams to OpenObserve via its Loki-compatible HTTP push API.
Replaces the former loki_push_service.py. OpenObserve speaks the same Loki push
protocol at /api/{org}/loki/api/v1/push, so the payload format is unchanged.

Primary use case: forwarding browser console logs from admin users so they appear
alongside server-side logs in OpenObserve. This endpoint is called by the
admin_client_logs route.

Architecture context: docs/architecture/admin-console-log-forwarding.md
Tests: None (non-critical debug infrastructure)
"""

import logging
import os
import re
import aiohttp
from typing import List, Dict, Any

logger = logging.getLogger(__name__)

OPENOBSERVE_ORG = "default"

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
