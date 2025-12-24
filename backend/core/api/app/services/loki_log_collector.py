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
import os
import re
from typing import Optional, List, Dict, Any
from datetime import datetime, timedelta, timezone
import urllib.parse

logger = logging.getLogger(__name__)


class LokiLogCollectorService:
    """Service for collecting Docker Compose logs via Loki queries."""

    def __init__(self):
        self.loki_url = "http://loki:3100"  # Internal Docker network URL
        self.compose_project = "openmates-core"  # From docker-compose.yml name field
        self.compose_file_path = os.getenv("OPENMATES_COMPOSE_FILE", "/app/backend/core/docker-compose.yml")

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

    async def _get_loki_series(self, start_time: Optional[datetime] = None) -> Optional[List[Dict[str, str]]]:
        """
        Query Loki for stream label sets ("series") within our compose project.
        """
        try:
            if start_time is None:
                start_time = datetime.now(timezone.utc) - timedelta(hours=1)

            start_ns = int(start_time.timestamp() * 1_000_000_000)
            end_ns = int(datetime.now(timezone.utc).timestamp() * 1_000_000_000)

            url = f"{self.loki_url}/loki/api/v1/series"
            params = [
                ("match[]", f'{{compose_project="{self.compose_project}"}}'),
                ("start", str(start_ns)),
                ("end", str(end_ns)),
            ]

            timeout = aiohttp.ClientTimeout(total=30)
            async with aiohttp.ClientSession(timeout=timeout) as session:
                async with session.get(url, params=params) as response:
                    if response.status != 200:
                        error_text = await response.text()
                        logger.warning(f"Loki series query failed with status {response.status}: {error_text}")
                        return None
                    result = await response.json()
                    if result.get("status") != "success":
                        logger.warning(f"Loki series query returned non-success status: {result.get('status')}")
                        return None
                    data = result.get("data")
                    return data if isinstance(data, list) else None
        except Exception as e:
            logger.warning(f"Error querying Loki series: {e}", exc_info=True)
            return None

    def _parse_compose_services(self) -> Dict[str, str]:
        """
        Parse docker-compose.yml to build a mapping of service_name -> container_name.
        Falls back to service_name if container_name is not specified.
        """
        try:
            if not os.path.exists(self.compose_file_path):
                return {}

            with open(self.compose_file_path, "r", encoding="utf-8") as f:
                lines = f.readlines()

            in_services = False
            current_service: Optional[str] = None
            service_to_container: Dict[str, str] = {}

            for line in lines:
                stripped = line.strip()
                if not in_services:
                    if stripped == "services:":
                        in_services = True
                    continue

                # End of "services" mapping once indentation drops to 0 (next top-level key)
                if line and not line.startswith(" ") and stripped:
                    break

                service_match = re.match(r"^  ([A-Za-z0-9][A-Za-z0-9_-]*):\s*$", line)
                if service_match:
                    current_service = service_match.group(1)
                    service_to_container[current_service] = current_service
                    continue

                if not current_service:
                    continue

                container_match = re.match(r"^    container_name:\s*([^\s#]+)\s*$", line)
                if container_match:
                    raw = container_match.group(1).strip().strip('"').strip("'")
                    service_to_container[current_service] = raw

            return service_to_container
        except Exception as e:
            logger.warning(f"Error parsing compose file for services: {e}", exc_info=True)
            return {}

    def _format_entries_for_container(self, container_name: str, entries: List[Dict[str, Any]], lines: int) -> str:
        if not entries:
            return f"\n--- Logs for {container_name} ---\n(no log entries found)\n"

        # Keep only the most recent N entries, but output in chronological order for readability.
        entries.sort(key=lambda x: x["timestamp_ns"])
        tail = entries[-lines:] if lines > 0 else entries

        services_seen = sorted({e["service_name"] for e in tail if e.get("service_name")})
        services_str = f" (services: {', '.join(services_seen)})" if services_seen else ""

        output = [f"\n--- Logs for {container_name}{services_str} ---\n"]
        for e in tail:
            timestamp_s = int(e["timestamp_ns"]) / 1_000_000_000
            dt = datetime.fromtimestamp(timestamp_s, tz=timezone.utc)
            formatted_time = dt.strftime("%Y-%m-%d %H:%M:%S")
            output.append(f"{e.get('service_name', 'unknown')} | {formatted_time} | {e.get('log_line', '')}")
        return "\n".join(output)

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

    async def get_compose_logs(
        self,
        lines: int = 100,
        services: Optional[List[str]] = None,
        exclude_containers: Optional[List[str]] = None,
        start_time: Optional[datetime] = None,
    ) -> Optional[str]:
        """
        Get logs from Docker Compose containers via Loki.

        Args:
            lines: Number of lines to retrieve per container (tail)
            services: List of specific services to get logs from (None for all)
            exclude_containers: Container/service names to exclude
            start_time: Start time window for Loki queries (defaults to 1 hour ago)

        Returns:
            String containing the logs or None if failed
        """
        try:
            logger.info(f"Collecting Docker Compose logs from Loki (per-container lines: {lines})")

            excluded = set(exclude_containers or [])
            requested = set(services or [])

            # Prefer enumerating actual running containers/services from Loki so this works in production.
            series = await self._get_loki_series(start_time=start_time)

            container_to_services: Dict[str, set] = {}
            container_to_matcher_key: Dict[str, str] = {}
            if series:
                for labels in series:
                    if labels.get("container"):
                        container = labels.get("container")
                        matcher_key = "container"
                    else:
                        container = labels.get("service")
                        matcher_key = "service"

                    service = labels.get("service") or labels.get("container") or "unknown"
                    if not container:
                        continue
                    container_to_services.setdefault(container, set()).add(service)
                    # Prefer "container" when available.
                    if matcher_key == "container" or container not in container_to_matcher_key:
                        container_to_matcher_key[container] = matcher_key

            # Fallback: parse compose file if Loki series endpoint isn't available yet.
            if not container_to_services:
                parsed = self._parse_compose_services()
                for service_name, container_name in parsed.items():
                    container_to_services.setdefault(container_name, set()).add(service_name)
                    container_to_matcher_key.setdefault(container_name, "container")

            if not container_to_services:
                fallback = f"=== Loki Log Collection Failed - {datetime.utcnow().isoformat()}Z ===\n"
                fallback += f"Could not enumerate containers/services for compose project '{self.compose_project}'.\n"
                fallback += f"Loki URL: {self.loki_url}\n"
                fallback += "This indicates either:\n"
                fallback += "1. Loki service is not running\n"
                fallback += "2. Promtail hasn't collected logs yet\n"
                fallback += "3. Network connectivity issue\n"
                return fallback

            # If a specific service list is provided, include containers that match either the
            # container name or any associated service name.
            def is_requested(container_name: str, service_names: set) -> bool:
                if not requested:
                    return True
                if container_name in requested:
                    return True
                return any(s in requested for s in service_names)

            # Query each container separately so "lines" applies per container.
            header = f"=== Container Logs from Loki - {datetime.utcnow().isoformat()}Z ==="
            output_parts = [header]

            for container_name in sorted(container_to_services.keys()):
                service_names = container_to_services.get(container_name, set())

                if container_name in excluded or any(s in excluded for s in service_names):
                    continue
                if not is_requested(container_name, service_names):
                    continue

                matcher_key = container_to_matcher_key.get(container_name, "container")
                query = f'{{compose_project="{self.compose_project}", {matcher_key}="{container_name}"}}'
                result = await self._query_loki(query, limit=lines, start_time=start_time)

                # If the runtime doesn't label streams with "container", fall back to "service".
                if (not result or not result.get("data", {}).get("result")) and matcher_key == "container":
                    if len(service_names) == 1:
                        service_value = next(iter(service_names))
                    else:
                        service_value = container_name
                    fallback_query = f'{{compose_project="{self.compose_project}", service="{service_value}"}}'
                    result = await self._query_loki(fallback_query, limit=lines, start_time=start_time)

                entries: List[Dict[str, Any]] = []
                if result and result.get("data", {}).get("result"):
                    for stream in result["data"]["result"]:
                        stream_labels = stream.get("stream", {})
                        service_name = stream_labels.get("service", "unknown")
                        for timestamp_ns, log_line in stream.get("values", []):
                            entries.append(
                                {
                                    "timestamp_ns": int(timestamp_ns),
                                    "service_name": service_name,
                                    "log_line": log_line,
                                }
                            )

                output_parts.append(self._format_entries_for_container(container_name, entries, lines))

            return "\n".join(output_parts).strip() + "\n"

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
