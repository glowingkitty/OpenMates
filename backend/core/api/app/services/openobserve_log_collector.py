"""
OpenObserve Log Collector Service

Queries OpenObserve to collect logs from all Docker Compose containers.
Replaces the former Loki-based log collector. OpenObserve accepts Loki-compatible
push (via Promtail) and exposes a SQL search API for querying.

Architecture context: docs/architecture/admin-console-log-forwarding.md
Tests: None (inspection/admin infrastructure, not production logic)
"""

import logging
import aiohttp
import os
import re
import tempfile
from typing import Optional, List, Dict, Any
from datetime import datetime, timedelta, timezone

logger = logging.getLogger(__name__)

# OpenObserve SQL search API endpoint pattern (v0.70+):
#   POST /api/{org}/_search
# Body: {"query": {"sql": "SELECT ... FROM {stream}", "start_time": <µs>, "end_time": <µs>}}
OPENOBSERVE_ORG = "default"


class OpenObserveLogCollectorService:
    """Service for collecting Docker Compose logs via OpenObserve SQL search API."""

    def __init__(self):
        self.base_url = "http://openobserve:5080"
        self.org = OPENOBSERVE_ORG
        self.compose_project = "openmates-core"
        self.compose_file_path = os.getenv(
            "OPENMATES_COMPOSE_FILE", "/app/backend/core/docker-compose.yml"
        )
        # Basic auth credentials from environment (set by docker-compose via env_file)
        self._email = os.getenv("OPENOBSERVE_ROOT_EMAIL", "")
        self._password = os.getenv("OPENOBSERVE_ROOT_PASSWORD", "")

    def _auth(self) -> aiohttp.BasicAuth:
        return aiohttp.BasicAuth(self._email, self._password)

    async def _search(
        self,
        stream: str,
        sql: str,
        start_time: Optional[datetime] = None,
        end_time: Optional[datetime] = None,
        limit: int = 1000,
    ) -> Optional[List[Dict[str, Any]]]:
        """
        Execute a SQL search against an OpenObserve stream.

        Returns a flat list of hit dicts, or None on failure.
        OpenObserve SQL search docs (v0.70+):
          POST /api/{org}/_search
          Body: {"query": {"sql": "...", "start_time": <µs epoch>, "end_time": <µs epoch>}}
        """
        if start_time is None:
            start_time = datetime.now(timezone.utc) - timedelta(hours=1)
        if end_time is None:
            end_time = datetime.now(timezone.utc)

        start_us = int(start_time.timestamp() * 1_000_000)
        end_us = int(end_time.timestamp() * 1_000_000)

        # OpenObserve v0.70+ uses /api/{org}/_search (stream is in SQL FROM clause)
        # Previously: /api/{org}/{stream}/_search (removed in v0.70)
        url = f"{self.base_url}/api/{self.org}/_search"
        body = {
            "query": {
                "sql": sql,
                "start_time": start_us,
                "end_time": end_us,
            }
        }

        try:
            timeout = aiohttp.ClientTimeout(total=30)
            async with aiohttp.ClientSession(timeout=timeout, auth=self._auth()) as session:
                async with session.post(url, json=body) as response:
                    if response.status == 200:
                        result = await response.json()
                        return result.get("hits", [])
                    else:
                        error_text = await response.text()
                        logger.error(
                            f"OpenObserve search failed (stream={stream}, status={response.status}): "
                            f"{error_text[:300]}"
                        )
                        return None
        except Exception as e:
            logger.error(f"Error querying OpenObserve (stream={stream}): {e}", exc_info=True)
            return None

    async def _list_streams(self) -> Optional[List[str]]:
        """Return stream names available in the org."""
        url = f"{self.base_url}/api/{self.org}/streams"
        try:
            timeout = aiohttp.ClientTimeout(total=15)
            async with aiohttp.ClientSession(timeout=timeout, auth=self._auth()) as session:
                async with session.get(url) as response:
                    if response.status == 200:
                        data = await response.json()
                        return [s["name"] for s in data.get("list", [])]
                    return None
        except Exception as e:
            logger.warning(f"Error listing OpenObserve streams: {e}", exc_info=True)
            return None

    def _parse_compose_services(self) -> Dict[str, str]:
        """
        Parse docker-compose.yml to build service_name → container_name mapping.
        Used as fallback when stream enumeration fails.
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
            logger.warning(f"Error parsing compose file: {e}", exc_info=True)
            return {}

    def _format_entries_for_container(
        self, container_name: str, entries: List[Dict[str, Any]], lines: int
    ) -> str:
        if not entries:
            return f"\n--- Logs for {container_name} ---\n(no log entries found)\n"

        # Sort chronologically; tail to requested line count
        entries.sort(key=lambda x: x.get("_timestamp", 0))
        tail = entries[-lines:] if lines > 0 else entries

        services_seen = sorted({e.get("container", e.get("service", "")) for e in tail if e.get("container") or e.get("service")})
        services_str = f" (services: {', '.join(services_seen)})" if services_seen else ""

        output = [f"\n--- Logs for {container_name}{services_str} ---\n"]
        for e in tail:
            # OpenObserve stores timestamp as microseconds in _timestamp field
            ts_us = e.get("_timestamp", 0)
            dt = datetime.fromtimestamp(ts_us / 1_000_000, tz=timezone.utc)
            formatted_time = dt.strftime("%Y-%m-%d %H:%M:%S")
            service = e.get("service", e.get("container", "unknown"))
            log_line = e.get("log", e.get("message", ""))
            output.append(f"{service} | {formatted_time} | {log_line}")
        return "\n".join(output)

    async def get_compose_logs(
        self,
        lines: int = 100,
        services: Optional[List[str]] = None,
        exclude_containers: Optional[List[str]] = None,
        start_time: Optional[datetime] = None,
    ) -> Optional[str]:
        """
        Get logs from Docker Compose containers via OpenObserve.

        Args:
            lines: Max log lines to retrieve per container (tail)
            services: Specific services to include (None = all)
            exclude_containers: Container/service names to exclude
            start_time: Query window start (defaults to 1 hour ago)
        """
        try:
            logger.info(f"Collecting Docker Compose logs from OpenObserve (lines={lines})")

            excluded = set(exclude_containers or [])
            requested = set(services or [])

            # Enumerate containers from OpenObserve "default" stream
            # (Promtail sends container logs here with "container" label)
            container_sql = (
                f"SELECT DISTINCT container, service FROM \"default\" "
                f"WHERE compose_project = '{self.compose_project}' LIMIT 200"
            )
            hits = await self._search("default", container_sql, start_time=start_time)

            container_to_services: Dict[str, set] = {}
            if hits:
                for h in hits:
                    container = h.get("container") or h.get("service")
                    service = h.get("service") or container
                    if container:
                        container_to_services.setdefault(container, set()).add(service)

            # Fallback: parse compose file
            if not container_to_services:
                parsed = self._parse_compose_services()
                for svc, ctr in parsed.items():
                    container_to_services.setdefault(ctr, set()).add(svc)

            if not container_to_services:
                fallback = f"=== OpenObserve Log Collection Failed - {datetime.utcnow().isoformat()}Z ===\n"
                fallback += f"Could not enumerate containers for compose project '{self.compose_project}'.\n"
                fallback += f"OpenObserve URL: {self.base_url}\n"
                return fallback

            def is_requested(cname: str, snames: set) -> bool:
                if not requested:
                    return True
                return cname in requested or any(s in requested for s in snames)

            header = f"=== Container Logs from OpenObserve - {datetime.utcnow().isoformat()}Z ==="
            output_parts = [header]

            for container_name in sorted(container_to_services.keys()):
                service_names = container_to_services[container_name]

                if container_name in excluded or any(s in excluded for s in service_names):
                    continue
                if not is_requested(container_name, service_names):
                    continue

                sql = (
                    f"SELECT _timestamp, container, service, log, message "
                    f"FROM \"default\" "
                    f"WHERE compose_project = '{self.compose_project}' "
                    f"AND (container = '{container_name}' OR service = '{container_name}') "
                    f"ORDER BY _timestamp DESC LIMIT {lines}"
                )
                hits = await self._search("default", sql, start_time=start_time) or []
                output_parts.append(
                    self._format_entries_for_container(container_name, hits, lines)
                )

            return "\n".join(output_parts).strip() + "\n"

        except Exception as e:
            logger.error(f"Error collecting compose logs from OpenObserve: {e}", exc_info=True)
            return f"Error collecting logs from OpenObserve: {str(e)}"

    async def get_service_status(self) -> Optional[str]:
        """Get a quick service status summary from recent startup/error logs."""
        try:
            sql = (
                f"SELECT _timestamp, service, container, log, message "
                f"FROM \"default\" "
                f"WHERE compose_project = '{self.compose_project}' "
                f"AND (LOWER(log) LIKE '%started%' OR LOWER(log) LIKE '%ready%' "
                f"OR LOWER(log) LIKE '%listening%' OR LOWER(log) LIKE '%error%' "
                f"OR LOWER(log) LIKE '%failed%') "
                f"ORDER BY _timestamp DESC LIMIT 50"
            )
            hits = await self._search("default", sql) or []

            status_info = [f"=== Service Status from OpenObserve - {datetime.utcnow().isoformat()}Z ===\n"]
            services_seen: set = set()

            for h in hits:
                service = h.get("service", h.get("container", "unknown"))
                services_seen.add(service)
                ts_us = h.get("_timestamp", 0)
                dt = datetime.fromtimestamp(ts_us / 1_000_000, tz=timezone.utc)
                formatted_time = dt.strftime("%Y-%m-%d %H:%M:%S")
                log_line = h.get("log", h.get("message", ""))
                status_info.append(f"{service}: Last activity at {formatted_time}")
                lower = log_line.lower()
                if any(w in lower for w in ("error", "failed", "exception")):
                    status_info.append(f"  ⚠️  Recent error: {log_line[:100]}...")
                elif any(w in lower for w in ("started", "ready", "listening")):
                    status_info.append(f"  ✅ Status: {log_line[:100]}...")

            status_info.append(f"\nActive services detected: {', '.join(sorted(services_seen))}")
            return "\n".join(status_info)

        except Exception as e:
            logger.error(f"Error getting service status from OpenObserve: {e}")
            return f"Error getting service status: {str(e)}"

    async def create_log_file(
        self, lines: int = 100, services: Optional[List[str]] = None
    ) -> Optional[str]:
        """Create a temporary file with Docker Compose logs from OpenObserve."""
        try:
            logs = await self.get_compose_logs(lines, services)
            if not logs:
                return None

            with tempfile.NamedTemporaryFile(
                mode="w", suffix=".log", prefix="compose_logs_", delete=False
            ) as f:
                f.write(logs)
                f.write("\n\n")
                status = await self.get_service_status()
                if status:
                    f.write(status)
                return f.name

        except Exception as e:
            logger.error(f"Error creating log file: {e}")
            return None

    def is_docker_available(self) -> bool:
        """Compatibility shim — always True; actual availability is checked on first request."""
        return True

    async def test_openobserve_connection(self) -> bool:
        """Test if OpenObserve is accessible and healthy."""
        try:
            url = f"{self.base_url}/healthz"
            timeout = aiohttp.ClientTimeout(total=10)
            async with aiohttp.ClientSession(timeout=timeout) as session:
                async with session.get(url) as response:
                    return response.status == 200
        except Exception as e:
            logger.debug(f"OpenObserve connection test failed: {e}")
            return False


# Global singleton
openobserve_log_collector = OpenObserveLogCollectorService()
