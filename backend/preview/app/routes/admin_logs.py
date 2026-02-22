# backend/preview/app/routes/admin_logs.py
#
# GET /admin/logs — fetch recent Docker logs from the preview server container.
#
# This endpoint is for operational debugging of the preview server.
# It runs `docker compose logs` via subprocess and returns the output as plain text.
#
# Authentication:
#   Requests must include `X-Admin-Log-Key: <key>` matching the
#   ADMIN_LOG_API_KEY environment variable on this VM.
#
# Usage via admin_debug_cli.py (from the dev/prod API server):
#   docker exec api python /app/backend/scripts/admin_debug_cli.py preview-logs
#   docker exec api python /app/backend/scripts/admin_debug_cli.py preview-logs --since 30 --search "ERROR"
#
# Security considerations:
#   - The API key is a simple shared secret stored in the preview VM's .env file.
#   - `docker` subprocess access requires the Docker socket mounted read-only
#     at /var/run/docker.sock inside the preview container.
#   - All arguments are passed as a list (no shell=True) — no shell injection possible.
#   - Log output is truncated server-side by --tail and --since flags.
#   - The endpoint is exempt from referer validation and rate limiting (admin tool).

import asyncio
import logging
import os
import re
import subprocess
from typing import Optional

from fastapi import APIRouter, Header, HTTPException, Query
from fastapi.responses import PlainTextResponse

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/admin", tags=["Admin"])

# ---------------------------------------------------------------------------
# Configuration
# ---------------------------------------------------------------------------

# Docker Compose project name for the preview stack (matches name: in docker-compose.preview.yml)
_COMPOSE_PROJECT = "openmates-preview"

# Only one service in the preview stack
_ALLOWED_SERVICES = {"preview"}

# Hard limits to keep responses manageable
_MAX_LINES = 500
_MAX_SINCE_MINUTES = 1440  # 24 hours


# ---------------------------------------------------------------------------
# Auth helper
# ---------------------------------------------------------------------------

def _require_admin_key(x_admin_log_key: Optional[str]) -> None:
    """
    Validate the admin log API key from the X-Admin-Log-Key request header.

    The expected key is read from the ADMIN_LOG_API_KEY environment variable.
    If the env var is not set, the endpoint is disabled entirely (returns 503).
    """
    expected_key = os.environ.get("ADMIN_LOG_API_KEY", "")
    if not expected_key:
        logger.error(
            "[AdminLogs] ADMIN_LOG_API_KEY is not configured — "
            "set this env var to enable the admin logs endpoint"
        )
        raise HTTPException(
            status_code=503,
            detail="Admin logs endpoint is not configured on this server",
        )
    if not x_admin_log_key or x_admin_log_key != expected_key:
        logger.warning("[AdminLogs] Rejected request with invalid or missing X-Admin-Log-Key")
        raise HTTPException(status_code=401, detail="Invalid or missing admin log API key")


# ---------------------------------------------------------------------------
# Log fetch helper
# ---------------------------------------------------------------------------

async def _fetch_docker_logs(
    services: list[str],
    lines: int,
    since_minutes: int,
    search: Optional[str],
) -> str:
    """
    Fetch logs from Docker Compose containers using `docker compose logs`.

    Uses asyncio.to_thread to avoid blocking the async event loop.
    All arguments are passed as a list (no shell=True) — shell injection safe.

    Args:
        services:       Service names to fetch logs from (e.g. ["preview"]).
        lines:          Number of log lines per service (tail).
        since_minutes:  Return only logs from the last N minutes.
        search:         Optional regex pattern to grep logs (case-insensitive).

    Returns:
        Formatted log output as a plain text string.
    """
    cmd = [
        "docker", "compose",
        "--project-name", _COMPOSE_PROJECT,
        "logs",
        "--no-color",
        "--timestamps",
        f"--tail={lines}",
        f"--since={since_minutes}m",
        *services,
    ]

    logger.info(
        f"[AdminLogs] Fetching logs: services={services} "
        f"lines={lines} since={since_minutes}m search={search!r}"
    )

    def _run() -> str:
        """Synchronous subprocess call — runs in thread pool."""
        try:
            result = subprocess.run(
                cmd,
                capture_output=True,
                text=True,
                timeout=30,
            )
            # docker compose logs writes to stderr (includes container name prefixes)
            output = result.stderr or result.stdout or ""
            if result.returncode != 0 and not output:
                logger.error(
                    f"[AdminLogs] docker compose logs failed "
                    f"(exit {result.returncode}): {result.stderr[:500]}"
                )
                return f"[Error] docker compose logs exited with code {result.returncode}\n{result.stderr[:500]}"
            return output
        except subprocess.TimeoutExpired:
            logger.error("[AdminLogs] docker compose logs timed out after 30s")
            return "[Error] Log fetch timed out after 30 seconds"
        except FileNotFoundError:
            logger.error(
                "[AdminLogs] 'docker' command not found — "
                "is the Docker socket mounted in this container?"
            )
            return (
                "[Error] 'docker' command not found. "
                "The Docker socket must be mounted at /var/run/docker.sock "
                "with the Docker CLI available in this container.\n"
                "Add to docker-compose.preview.yml:\n"
                "  volumes:\n"
                "    - /var/run/docker.sock:/var/run/docker.sock:ro\n"
                "  group_add:\n"
                "    - <docker-group-gid>  # use: stat -c %g /var/run/docker.sock"
            )
        except Exception as exc:
            logger.error(f"[AdminLogs] Unexpected error fetching logs: {exc}", exc_info=True)
            return f"[Error] Failed to fetch logs: {exc}"

    raw_output = await asyncio.to_thread(_run)

    # Apply optional regex search filter (line-by-line grep)
    if search and raw_output and not raw_output.startswith("[Error]"):
        try:
            pattern = re.compile(search, re.IGNORECASE)
            lines_out = [line for line in raw_output.splitlines() if pattern.search(line)]
            if not lines_out:
                raw_output = f"[No lines matched search pattern: {search!r}]\n"
            else:
                raw_output = "\n".join(lines_out) + "\n"
        except re.error as exc:
            raw_output = f"[Warning] Invalid search pattern {search!r}: {exc}\n\n" + raw_output

    return raw_output


# ---------------------------------------------------------------------------
# Route
# ---------------------------------------------------------------------------

@router.get(
    "/logs",
    response_class=PlainTextResponse,
    summary="Fetch preview server Docker logs",
    description=(
        "Returns recent logs from the preview server Docker Compose container. "
        "Requires X-Admin-Log-Key header matching ADMIN_LOG_API_KEY env var.\n\n"
        "Available services: preview\n"
        "Called by: `admin_debug_cli.py preview-logs`"
    ),
)
async def get_admin_logs(
    services: Optional[str] = Query(
        default=None,
        description="Comma-separated list of services (default: preview). Allowed: preview",
    ),
    lines: int = Query(
        default=100,
        ge=1,
        le=_MAX_LINES,
        description=f"Number of log lines to return (max {_MAX_LINES})",
    ),
    since_minutes: int = Query(
        default=60,
        ge=1,
        le=_MAX_SINCE_MINUTES,
        description=f"Return logs from the last N minutes (max {_MAX_SINCE_MINUTES})",
    ),
    search: Optional[str] = Query(
        default=None,
        description="Regex pattern to filter log lines (case-insensitive)",
    ),
    x_admin_log_key: Optional[str] = Header(None),
) -> PlainTextResponse:
    """
    Fetch recent Docker logs from the preview server container.

    Auth: X-Admin-Log-Key header must match ADMIN_LOG_API_KEY env var.

    Requires Docker socket mounted in the preview container:
        volumes:
          - /var/run/docker.sock:/var/run/docker.sock:ro

    This endpoint is exempt from referer validation and rate limiting —
    it's an internal admin tool, and the API key provides access control.
    """
    # Auth check
    _require_admin_key(x_admin_log_key)

    # Parse and validate services
    if services:
        requested = {s.strip() for s in services.split(",") if s.strip()}
        unknown = requested - _ALLOWED_SERVICES
        if unknown:
            raise HTTPException(
                status_code=400,
                detail=f"Unknown service(s): {sorted(unknown)}. Allowed: {sorted(_ALLOWED_SERVICES)}",
            )
        service_list = sorted(requested)
    else:
        service_list = ["preview"]

    output = await _fetch_docker_logs(
        services=service_list,
        lines=lines,
        since_minutes=since_minutes,
        search=search,
    )

    return PlainTextResponse(content=output)
