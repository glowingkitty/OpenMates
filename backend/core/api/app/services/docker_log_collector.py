"""
Docker Compose Log Collector Service

This service collects logs from the containerized backend environment.
Since this runs from within a Docker container, it uses alternative methods
to collect logs without requiring docker command access.
"""

import logging
import os
import tempfile
import glob
from typing import Optional, List
from datetime import datetime
import subprocess

logger = logging.getLogger(__name__)


class DockerLogCollectorService:
    """Service for collecting backend logs from within a containerized environment."""

    def __init__(self):
        self.log_locations = self._get_log_locations()

    def _get_log_locations(self) -> List[str]:
        """Get possible log file locations within the container environment."""
        possible_log_paths = [
            # Application logs (common locations)
            "/app/logs/*.log",
            "/app/*.log",
            "/var/log/*.log",
            "/var/log/app/*.log",
            "/logs/*.log",

            # Python/Gunicorn/uWSGI logs
            "/var/log/gunicorn/*.log",
            "/var/log/uwsgi/*.log",
            "/var/log/python/*.log",

            # Standard output/error that might be redirected to files
            "/proc/1/fd/1",  # stdout of PID 1 (main process)
            "/proc/1/fd/2",  # stderr of PID 1 (main process)

            # Supervisor logs if using supervisor
            "/var/log/supervisor/*.log",

            # Nginx logs if present
            "/var/log/nginx/access.log",
            "/var/log/nginx/error.log",

            # Journal logs if systemd is used (unlikely in container)
            "/var/log/journal/*/*",
        ]

        # Expand glob patterns and filter existing files
        existing_logs = []
        for pattern in possible_log_paths:
            try:
                if '*' in pattern:
                    # Expand glob pattern
                    matches = glob.glob(pattern)
                    existing_logs.extend(matches)
                else:
                    # Check if direct path exists
                    if os.path.exists(pattern) and os.path.isfile(pattern):
                        existing_logs.append(pattern)
            except Exception as e:
                logger.debug(f"Error checking log path {pattern}: {e}")

        # Remove duplicates and return
        return list(set(existing_logs))

    def _read_container_logs(self, log_paths: List[str], lines: int = 100) -> str:
        """
        Read logs directly from container log files or standard locations.

        Args:
            log_paths: List of log file paths to read
            lines: Number of lines to read from each log

        Returns:
            Combined log content as string
        """
        collected_logs = []

        for log_path in log_paths:
            try:
                if not os.path.exists(log_path):
                    continue

                # Skip if it's not a regular file (e.g., directories, devices)
                if not os.path.isfile(log_path):
                    continue

                logger.info(f"Reading logs from: {log_path}")

                # Use tail command if available for efficiency
                try:
                    result = subprocess.run(
                        ["tail", "-n", str(lines), log_path],
                        capture_output=True,
                        text=True,
                        timeout=10
                    )

                    if result.returncode == 0:
                        content = result.stdout
                    else:
                        # Fallback to Python file reading
                        raise subprocess.CalledProcessError(result.returncode, "tail")

                except (subprocess.CalledProcessError, FileNotFoundError, subprocess.TimeoutExpired):
                    # Fallback: read file directly with Python
                    with open(log_path, 'r', encoding='utf-8', errors='ignore') as f:
                        # Read last N lines efficiently
                        file_lines = f.readlines()
                        last_lines = file_lines[-lines:] if len(file_lines) > lines else file_lines
                        content = ''.join(last_lines)

                if content.strip():
                    collected_logs.append(f"\n=== Log from {log_path} ===\n")
                    collected_logs.append(content)
                    if not content.endswith('\n'):
                        collected_logs.append('\n')
                    collected_logs.append(f"=== End of {log_path} ===\n\n")

            except Exception as e:
                logger.warning(f"Could not read log file {log_path}: {e}")
                continue

        return ''.join(collected_logs) if collected_logs else None

    def _get_process_info(self) -> str:
        """Get information about running processes."""
        try:
            # Get process list
            result = subprocess.run(
                ["ps", "aux"],
                capture_output=True,
                text=True,
                timeout=10
            )

            if result.returncode == 0:
                return f"\n=== Running Processes ===\n{result.stdout}\n"
            else:
                return "\n=== Running Processes ===\nUnavailable\n"

        except Exception as e:
            logger.debug(f"Could not get process info: {e}")
            return "\n=== Running Processes ===\nUnavailable\n"

    def _get_container_info(self) -> str:
        """Get container environment information."""
        info_parts = []

        # Container hostname
        try:
            with open('/etc/hostname', 'r') as f:
                hostname = f.read().strip()
                info_parts.append(f"Container Hostname: {hostname}")
        except:
            info_parts.append("Container Hostname: Unknown")

        # Environment variables (filter sensitive ones)
        try:
            safe_env_vars = {}
            sensitive_keys = ['PASSWORD', 'SECRET', 'KEY', 'TOKEN', 'API_KEY']

            for key, value in os.environ.items():
                if not any(sensitive in key.upper() for sensitive in sensitive_keys):
                    safe_env_vars[key] = value
                else:
                    safe_env_vars[key] = '[REDACTED]'

            # Include some relevant environment variables
            relevant_vars = ['PATH', 'PYTHONPATH', 'LANG', 'TZ', 'USER', 'HOME', 'PWD']
            env_info = []
            for var in relevant_vars:
                if var in safe_env_vars:
                    env_info.append(f"{var}={safe_env_vars[var]}")

            if env_info:
                info_parts.append(f"Environment: {'; '.join(env_info[:10])}")  # Limit to 10 vars

        except Exception as e:
            logger.debug(f"Could not get environment info: {e}")
            info_parts.append("Environment: Unavailable")

        # Memory info
        try:
            with open('/proc/meminfo', 'r') as f:
                meminfo = f.read()
                # Extract total and available memory
                for line in meminfo.split('\n'):
                    if 'MemTotal:' in line or 'MemAvailable:' in line:
                        info_parts.append(line.strip())
        except:
            info_parts.append("Memory Info: Unavailable")

        return "\n=== Container Environment ===\n" + '\n'.join(info_parts) + "\n\n"

    def get_compose_logs(self, lines: int = 100, services: Optional[List[str]] = None) -> Optional[str]:
        """
        Get logs from the backend application running in the container.

        Args:
            lines: Number of lines to retrieve from each log file
            services: Ignored for compatibility (we read available log files)

        Returns:
            String containing the logs or None if no logs found
        """
        try:
            logger.info("Collecting backend logs from container environment")

            # Get available log paths
            available_logs = [path for path in self.log_locations if os.path.exists(path)]

            if not available_logs:
                logger.warning("No log files found in container")
                # Fallback: try to collect from common application output
                fallback_info = []
                fallback_info.append(f"=== Backend Log Collection - {datetime.utcnow().isoformat()}Z ===\n")
                fallback_info.append("No log files found in standard locations.\n")
                fallback_info.append("Available log locations checked:\n")
                for location in self.log_locations[:10]:  # Show first 10 for brevity
                    fallback_info.append(f"  - {location}\n")

                fallback_info.append(self._get_container_info())
                fallback_info.append(self._get_process_info())

                return ''.join(fallback_info)

            # Read logs from available files
            logs_content = self._read_container_logs(available_logs[:5], lines)  # Limit to 5 files max

            if logs_content:
                # Add header
                header = f"=== Backend Container Logs (last {lines} lines) - {datetime.utcnow().isoformat()}Z ===\n"

                # Add container info
                container_info = self._get_container_info()

                # Add process info
                process_info = self._get_process_info()

                return header + container_info + process_info + logs_content
            else:
                # Return basic container information if no logs found
                header = f"=== Backend Container Info - {datetime.utcnow().isoformat()}Z ===\n"
                container_info = self._get_container_info()
                process_info = self._get_process_info()

                return header + container_info + process_info + "No readable log content found.\n"

        except Exception as e:
            logger.error(f"Error collecting backend logs: {e}", exc_info=True)
            return f"Error collecting backend logs: {str(e)}"

    def get_service_status(self) -> Optional[str]:
        """
        Get the status of services running in the container.

        Returns:
            String containing service status or None if failed
        """
        try:
            status_info = []
            status_info.append(f"=== Backend Container Service Status - {datetime.utcnow().isoformat()}Z ===\n")

            # Add process information
            status_info.append(self._get_process_info())

            # Add container info
            status_info.append(self._get_container_info())

            # Check if specific services are running
            common_processes = ['python', 'gunicorn', 'uwsgi', 'nginx', 'supervisord']
            running_processes = []

            try:
                ps_result = subprocess.run(["ps", "-eo", "comm"], capture_output=True, text=True, timeout=10)
                if ps_result.returncode == 0:
                    ps_lines = ps_result.stdout.lower().split('\n')
                    for process in common_processes:
                        if any(process in line for line in ps_lines):
                            running_processes.append(process)

                if running_processes:
                    status_info.append(f"Detected Services: {', '.join(running_processes)}\n")
                else:
                    status_info.append("No common web services detected\n")

            except Exception as e:
                logger.debug(f"Could not check running processes: {e}")
                status_info.append("Service detection: Unavailable\n")

            return ''.join(status_info)

        except Exception as e:
            logger.error(f"Error getting service status: {e}")
            return f"Error getting service status: {str(e)}"

    def create_log_file(self, lines: int = 100, services: Optional[List[str]] = None) -> Optional[str]:
        """
        Create a temporary file with backend logs.

        Args:
            lines: Number of lines to retrieve
            services: Ignored for compatibility

        Returns:
            Path to the temporary file or None if failed
        """
        try:
            logs = self.get_compose_logs(lines, services)
            if not logs:
                return None

            # Create temporary file
            with tempfile.NamedTemporaryFile(mode='w', suffix='.log', prefix='backend_logs_', delete=False) as f:
                f.write(logs)
                f.write("\n\n")

                # Add service status
                status = self.get_service_status()
                if status:
                    f.write(status)

                return f.name

        except Exception as e:
            logger.error(f"Error creating log file: {e}")
            return None

    def is_docker_available(self) -> bool:
        """
        Check if we're running in a containerized environment.
        Since we're already in a container, this always returns True.
        """
        # Check for container indicators
        container_indicators = [
            os.path.exists('/.dockerenv'),
            os.path.exists('/proc/1/cgroup'),
            os.environ.get('container') == 'docker',
            os.path.exists('/etc/hostname')
        ]

        return any(container_indicators)


# Global instance
docker_log_collector = DockerLogCollectorService()