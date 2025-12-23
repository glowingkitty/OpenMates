"""
Loki Log Collector Service

This service queries Loki to collect logs from all Docker Compose containers.
This is equivalent to running 'docker compose logs' and provides logs from all services.
"""

import logging
import aiohttp
import asyncio
import json
import tempfile
import base64
from typing import Optional, List, Dict, Any
from datetime import datetime, timedelta, timezone
import urllib.parse

logger = logging.getLogger(__name__)


class LokiLogCollectorService:
    """Service for collecting Docker Compose logs via Loki queries."""

    def __init__(self):
        self.loki_url = "http://loki:3100"  # Internal Docker network URL
        self.compose_project = "openmates-core"  # From docker-compose.yml name field

    async def _query_loki(self, query: str, limit: int = 1000, start_time: Optional[datetime] = None) -> Optional[Dict]:
        """
        Query Loki API for logs.

        Args:
            query: LogQL query string
            limit: Maximum number of log lines to return
            start_time: Start time for the query (defaults to 1 hour ago)

        Returns:
            Dict containing Loki query results or None if failed
        """
        try:
            if start_time is None:
                start_time = datetime.now(timezone.utc) - timedelta(hours=1)

            # Format times for Loki API (nanoseconds since epoch)
            start_ns = int(start_time.timestamp() * 1_000_000_000)
            end_ns = int(datetime.now(timezone.utc).timestamp() * 1_000_000_000)

            # Prepare query parameters
            params = {
                'query': query,
                'limit': str(limit),
                'start': str(start_ns),
                'end': str(end_ns),
                'direction': 'backward'  # Get most recent logs first
            }

            url = f"{self.loki_url}/loki/api/v1/query_range"

            logger.info(f"Querying Loki: {query} (limit: {limit})")

            timeout = aiohttp.ClientTimeout(total=30)
            async with aiohttp.ClientSession(timeout=timeout) as session:
                async with session.get(url, params=params) as response:
                    if response.status == 200:
                        result = await response.json()
                        return result
                    else:
                        error_text = await response.text()
                        logger.error(f"Loki query failed with status {response.status}: {error_text}")
                        return None

        except Exception as e:
            logger.error(f"Error querying Loki: {e}", exc_info=True)
            return None

    def _format_loki_logs(self, loki_result: Dict) -> str:
        """
        Format Loki query results into docker-compose-logs-like output.

        Args:
            loki_result: Result from Loki query

        Returns:
            Formatted log string
        """
        if not loki_result or 'data' not in loki_result:
            return "No log data returned from Loki"

        try:
            formatted_logs = []

            # Add header
            header = f"=== Container Logs from Loki - {datetime.utcnow().isoformat()}Z ===\n"
            formatted_logs.append(header)

            # Process each stream (container/service)
            streams = loki_result['data']['result']

            for stream in streams:
                stream_labels = stream.get('stream', {})
                container_name = stream_labels.get('container', 'unknown')
                service_name = stream_labels.get('service', 'unknown')

                # Add stream header
                formatted_logs.append(f"\n--- Logs from {service_name} ({container_name}) ---\n")

                # Process log entries (they come as [timestamp, line])
                entries = stream.get('values', [])

                # Sort entries by timestamp (ascending order for readability)
                entries.sort(key=lambda x: x[0])

                for timestamp_ns, log_line in entries:
                    # Convert timestamp from nanoseconds to readable format
                    timestamp_s = int(timestamp_ns) / 1_000_000_000
                    dt = datetime.fromtimestamp(timestamp_s, tz=timezone.utc)
                    formatted_time = dt.strftime('%Y-%m-%d %H:%M:%S')

                    # Format like docker-compose logs: service_name | timestamp | log_line
                    formatted_entry = f"{service_name} | {formatted_time} | {log_line}"
                    formatted_logs.append(formatted_entry)

            return '\n'.join(formatted_logs)

        except Exception as e:
            logger.error(f"Error formatting Loki logs: {e}", exc_info=True)
            return f"Error formatting logs: {str(e)}"

    async def get_compose_logs(self, lines: int = 100, services: Optional[List[str]] = None) -> Optional[str]:
        """
        Get logs from Docker Compose services via Loki.

        Args:
            lines: Number of lines to retrieve from each service
            services: List of specific services to get logs from (None for all)

        Returns:
            String containing the logs or None if failed
        """
        try:
            logger.info(f"Collecting Docker Compose logs from Loki (lines: {lines})")

            # Build LogQL query to get logs from all containers in our compose project
            base_query = f'{{compose_project="{self.compose_project}"}}'

            # If specific services requested, filter by them
            if services:
                service_filter = '|'.join(services)
                base_query = f'{{compose_project="{self.compose_project}", service=~"{service_filter}"}}'

            # Query Loki
            result = await self._query_loki(base_query, limit=lines * 5)  # Get more lines, then format

            if result:
                formatted_logs = self._format_loki_logs(result)

                # Limit to requested number of lines
                log_lines = formatted_logs.split('\n')
                if len(log_lines) > lines + 10:  # +10 for headers
                    log_lines = log_lines[:lines + 10] + ['... (truncated)']

                return '\n'.join(log_lines)
            else:
                # Fallback: provide basic info about Loki setup
                fallback = f"=== Loki Log Collection Failed - {datetime.utcnow().isoformat()}Z ===\n"
                fallback += f"Could not retrieve logs from Loki at {self.loki_url}\n"
                fallback += f"Compose project: {self.compose_project}\n"
                fallback += f"Attempted query: {base_query}\n\n"
                fallback += "This indicates either:\n"
                fallback += "1. Loki service is not running\n"
                fallback += "2. Promtail hasn't collected logs yet\n"
                fallback += "3. Network connectivity issue\n"
                return fallback

        except Exception as e:
            logger.error(f"Error collecting compose logs from Loki: {e}", exc_info=True)
            return f"Error collecting logs from Loki: {str(e)}"

    async def get_service_status(self) -> Optional[str]:
        """
        Get the status of services by querying recent logs.

        Returns:
            String containing service status summary
        """
        try:
            # Query for recent logs from all services to check status
            query = f'{{compose_project="{self.compose_project}"}} |~ "(?i)(started|ready|listening|error|failed)"'

            result = await self._query_loki(query, limit=50)

            if result:
                status_info = []
                status_info.append(f"=== Service Status from Loki - {datetime.utcnow().isoformat()}Z ===\n")

                # Extract service status information
                services_seen = set()
                streams = result.get('data', {}).get('result', [])

                for stream in streams:
                    service_name = stream.get('stream', {}).get('service', 'unknown')
                    services_seen.add(service_name)

                    # Get latest entry to check status
                    entries = stream.get('values', [])
                    if entries:
                        latest_entry = entries[0]  # Most recent
                        timestamp_ns, log_line = latest_entry
                        timestamp_s = int(timestamp_ns) / 1_000_000_000
                        dt = datetime.fromtimestamp(timestamp_s, tz=timezone.utc)
                        formatted_time = dt.strftime('%Y-%m-%d %H:%M:%S')

                        status_info.append(f"{service_name}: Last activity at {formatted_time}")
                        if any(word in log_line.lower() for word in ['error', 'failed', 'exception']):
                            status_info.append(f"  ⚠️  Recent error: {log_line[:100]}...")
                        elif any(word in log_line.lower() for word in ['started', 'ready', 'listening']):
                            status_info.append(f"  ✅ Status: {log_line[:100]}...")

                status_info.append(f"\nActive services detected: {', '.join(sorted(services_seen))}")
                return '\n'.join(status_info)
            else:
                return f"=== Service Status ===\nUnable to retrieve status from Loki at {self.loki_url}"

        except Exception as e:
            logger.error(f"Error getting service status from Loki: {e}")
            return f"Error getting service status: {str(e)}"

    async def create_log_file(self, lines: int = 100, services: Optional[List[str]] = None) -> Optional[str]:
        """
        Create a temporary file with Docker Compose logs from Loki.

        Args:
            lines: Number of lines to retrieve
            services: Specific services to collect logs from

        Returns:
            Path to the temporary file or None if failed
        """
        try:
            logs = await self.get_compose_logs(lines, services)
            if not logs:
                return None

            # Create temporary file
            with tempfile.NamedTemporaryFile(mode='w', suffix='.log', prefix='compose_logs_', delete=False) as f:
                f.write(logs)
                f.write("\n\n")

                # Add service status
                status = await self.get_service_status()
                if status:
                    f.write(status)

                return f.name

        except Exception as e:
            logger.error(f"Error creating log file: {e}")
            return None

    def is_docker_available(self) -> bool:
        """
        Check if Loki is available for log collection.
        This replaces the Docker availability check.
        """
        # We'll assume Loki is available since it's part of the compose setup
        # The actual availability will be checked when we make requests
        return True

    async def test_loki_connection(self) -> bool:
        """
        Test if Loki is accessible and responding.

        Returns:
            True if Loki is accessible, False otherwise
        """
        try:
            url = f"{self.loki_url}/ready"
            timeout = aiohttp.ClientTimeout(total=10)

            async with aiohttp.ClientSession(timeout=timeout) as session:
                async with session.get(url) as response:
                    return response.status == 200

        except Exception as e:
            logger.debug(f"Loki connection test failed: {e}")
            return False


# Global instance
loki_log_collector = LokiLogCollectorService()