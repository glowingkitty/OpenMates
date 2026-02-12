"""
Loki Push Service

Thin wrapper around Loki's HTTP push API (POST /loki/api/v1/push) for ingesting
custom log streams that don't originate from Docker containers or log files.

Primary use case: forwarding browser console logs from admin users into Loki
so they appear alongside server-side logs in Grafana. This enables unified
debugging without requiring manual issue reports.

See docs/admin-console-log-forwarding.md for full architecture documentation.
"""

import logging
import os
import aiohttp
from typing import List, Dict, Any

logger = logging.getLogger(__name__)


class LokiPushService:
    """
    Service for pushing custom log entries to Loki via its HTTP API.

    Loki's push endpoint expects a specific JSON format with streams, labels, and values.
    This service handles formatting and delivery so callers only need to provide
    simple log entries with timestamps and messages.
    """

    def __init__(self) -> None:
        self.loki_url = "http://loki:3100"  # Internal Docker network URL
        self.server_env = os.getenv("SERVER_ENVIRONMENT", "development").lower()

    async def push_client_logs(
        self,
        entries: List[Dict[str, Any]],
        user_email: str,
        metadata: Dict[str, str],
    ) -> bool:
        """
        Push a batch of client console log entries to Loki.

        Each entry is grouped by log level into separate Loki streams so that
        level-based filtering works efficiently in LogQL queries.

        Args:
            entries: List of log entries, each with 'timestamp' (ms epoch), 'level', and 'message'
            user_email: Email of the admin user (used as a Loki label for filtering)
            metadata: Client metadata dict with 'userAgent', 'pageUrl', 'tabId'

        Returns:
            True if push succeeded, False otherwise
        """
        if not entries:
            return True

        try:
            # Group entries by level so each level gets its own Loki stream.
            # This allows efficient LogQL queries like {job="client-console", level="error"}
            streams_by_level: Dict[str, List[List[str]]] = {}

            for entry in entries:
                level = entry.get("level", "log")
                # Normalize 'log' level to 'info' for consistency with server-side log levels
                if level == "log":
                    level = "info"

                timestamp_ms = entry.get("timestamp", 0)
                message = entry.get("message", "")

                # Loki expects timestamps as nanosecond strings
                timestamp_ns = str(int(timestamp_ms * 1_000_000))

                # Prepend page URL and tab ID to the message for context in Grafana
                page_url = metadata.get("pageUrl", "")
                tab_id = metadata.get("tabId", "")
                formatted_message = f"[tab={tab_id}] [{page_url}] {message}"

                if level not in streams_by_level:
                    streams_by_level[level] = []
                streams_by_level[level].append([timestamp_ns, formatted_message])

            # Build Loki push payload
            # See: https://grafana.com/docs/loki/latest/reference/loki-http-api/#push-log-entries-to-loki
            streams = []
            for level, values in streams_by_level.items():
                streams.append({
                    "stream": {
                        "job": "client-console",
                        "level": level,
                        "user_email": user_email,
                        "server_env": self.server_env,
                        "source": "browser",
                    },
                    "values": values,
                })

            payload = {"streams": streams}

            url = f"{self.loki_url}/loki/api/v1/push"
            timeout = aiohttp.ClientTimeout(total=10)

            async with aiohttp.ClientSession(timeout=timeout) as session:
                async with session.post(
                    url,
                    json=payload,
                    headers={"Content-Type": "application/json"},
                ) as response:
                    if response.status == 204:
                        # 204 No Content = successful push (Loki's standard success response)
                        return True
                    else:
                        error_text = await response.text()
                        logger.error(
                            f"Loki push failed with status {response.status}: {error_text}"
                        )
                        return False

        except Exception as e:
            # Log but don't raise - client log forwarding is non-critical infrastructure
            logger.error(f"Error pushing client logs to Loki: {e}", exc_info=True)
            return False

    async def test_push_connection(self) -> bool:
        """
        Test if Loki's push endpoint is reachable.

        Returns:
            True if Loki is accessible, False otherwise
        """
        try:
            url = f"{self.loki_url}/ready"
            timeout = aiohttp.ClientTimeout(total=5)

            async with aiohttp.ClientSession(timeout=timeout) as session:
                async with session.get(url) as response:
                    return response.status == 200

        except Exception as e:
            logger.debug(f"Loki push connection test failed: {e}")
            return False


# Global singleton instance
loki_push_service = LokiPushService()
