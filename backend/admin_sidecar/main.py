# backend/admin_sidecar/main.py
#
# Admin Sidecar — a tiny FastAPI application that exposes operational admin
# endpoints for satellite servers (preview, upload).
#
# This sidecar runs as a SEPARATE container alongside the main service container.
# It holds the Docker socket and ADMIN_LOG_API_KEY so the main container does NOT
# need either. This limits the blast radius if the main container is ever
# compromised (e.g. by a malicious uploaded file on the upload server).
#
# Endpoints:
#   GET  /admin/logs   — fetch recent Docker Compose logs (plain text)
#   POST /admin/update — git pull + docker compose build + docker compose up -d
#   GET  /health       — liveness probe
#
# Authentication:
#   All /admin/* endpoints require X-Admin-Log-Key matching ADMIN_LOG_API_KEY env var.
#
# Configuration (all via environment variables):
#   ADMIN_LOG_API_KEY      — shared secret for X-Admin-Log-Key header (required)
#   COMPOSE_PROJECT        — docker compose --project-name value
#   COMPOSE_FILE           — path to docker-compose.yml (absolute or relative to GIT_WORK_DIR)
#   SERVICES_ALLOWED       — comma-separated list of log-queryable services
#   SERVICE_UPDATE_TARGET  — service name to rebuild and restart on /admin/update
#   GIT_WORK_DIR           — git repository root on the host (default: /app)
#   PORT                   — port to listen on (default: 8001)
#
# Security notes:
#   - This container needs Docker socket access (/var/run/docker.sock) and
#     group_add for the docker GID.
#   - No user-facing traffic ever reaches this container — Caddy routes only
#     /admin/* to it, and only internally.
#   - All subprocess calls use list args (no shell=True) — no shell injection.
#   - The update endpoint fires a background task and returns 202 immediately;
#     the caller uses /admin/logs to monitor progress afterward.

import asyncio
import logging
import os
import re
import subprocess
import sys
from typing import Optional

from fastapi import FastAPI, Header, HTTPException, Query
from fastapi.responses import JSONResponse, PlainTextResponse

# =============================================================================
# Configuration
# =============================================================================

_ADMIN_KEY = os.environ.get("ADMIN_LOG_API_KEY", "")
_COMPOSE_PROJECT = os.environ.get("COMPOSE_PROJECT", "")
_COMPOSE_FILE = os.environ.get("COMPOSE_FILE", "")
_SERVICES_ALLOWED_RAW = os.environ.get("SERVICES_ALLOWED", "")
_SERVICE_UPDATE_TARGET = os.environ.get("SERVICE_UPDATE_TARGET", "")
_GIT_WORK_DIR = os.environ.get("GIT_WORK_DIR", "/app")
_PORT = int(os.environ.get("PORT", "8001"))

# Parse allowed services into a set (empty means all services in the project)
_SERVICES_ALLOWED: set[str] = {
    s.strip() for s in _SERVICES_ALLOWED_RAW.split(",") if s.strip()
}

# Hard limits
_MAX_LINES = 500
_MAX_SINCE_MINUTES = 1440  # 24 hours

# Update step timeouts (seconds)
_STEP_TIMEOUT_GIT = 120    # git pull can be slow on cold fetch
_STEP_TIMEOUT_BUILD = 600  # docker compose build can take several minutes
_STEP_TIMEOUT_UP = 60      # docker compose up -d is fast

# Tracks whether an update is already in progress (prevents concurrent updates)
_update_in_progress = False

# =============================================================================
# Logging
# =============================================================================

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
    handlers=[logging.StreamHandler(sys.stdout)],
)
logger = logging.getLogger(__name__)


# =============================================================================
# FastAPI application
# =============================================================================

app = FastAPI(
    title="OpenMates Admin Sidecar",
    description=(
        "Operational admin endpoints (logs, update) for OpenMates satellite servers. "
        "Runs as an isolated sidecar container with Docker socket access. "
        "Protected by X-Admin-Log-Key shared secret."
    ),
    version="1.0.0",
    # Never expose docs publicly — this is an internal admin tool
    docs_url=None,
    redoc_url=None,
)


# =============================================================================
# Auth helper
# =============================================================================

def _require_admin_key(x_admin_log_key: Optional[str]) -> None:
    """
    Validate the X-Admin-Log-Key request header against ADMIN_LOG_API_KEY env var.

    Returns 503 if ADMIN_LOG_API_KEY is not configured (endpoint disabled).
    Returns 401 on key mismatch.
    """
    if not _ADMIN_KEY:
        logger.error(
            "[AdminSidecar] ADMIN_LOG_API_KEY is not set — "
            "set this env var to enable admin endpoints"
        )
        raise HTTPException(
            status_code=503,
            detail="Admin endpoints not configured (ADMIN_LOG_API_KEY not set)",
        )
    if not x_admin_log_key or x_admin_log_key != _ADMIN_KEY:
        logger.warning("[AdminSidecar] Rejected request with invalid or missing X-Admin-Log-Key")
        raise HTTPException(status_code=401, detail="Invalid or missing admin API key")


# =============================================================================
# Logs helper
# =============================================================================

async def _fetch_docker_logs(
    services: list[str],
    lines: int,
    since_minutes: int,
    search: Optional[str],
) -> str:
    """
    Fetch logs from Docker Compose containers using `docker compose logs`.

    Uses asyncio.to_thread to avoid blocking the async event loop.
    All arguments are passed as a list (no shell=True) — injection safe.

    Args:
        services:       Service names to include (e.g. ["preview"]).
        lines:          Number of log lines per service (tail).
        since_minutes:  Return only logs from the last N minutes.
        search:         Optional regex pattern to grep lines (case-insensitive).

    Returns:
        Formatted log output as plain text.
    """
    compose_file_abs = (
        os.path.join(_GIT_WORK_DIR, _COMPOSE_FILE) if _COMPOSE_FILE else None
    )

    cmd = ["docker", "compose"]
    if _COMPOSE_PROJECT:
        cmd += ["--project-name", _COMPOSE_PROJECT]
    if compose_file_abs:
        cmd += ["-f", compose_file_abs]
    cmd += [
        "logs",
        "--no-color",
        "--timestamps",
        f"--tail={lines}",
        f"--since={since_minutes}m",
        *services,
    ]

    logger.info(
        "[AdminSidecar/logs] Fetching logs: services=%s lines=%d since=%dm search=%r",
        services,
        lines,
        since_minutes,
        search,
    )

    def _run() -> str:
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
                    "[AdminSidecar/logs] docker compose logs failed (exit %d): %s",
                    result.returncode,
                    result.stderr[:500],
                )
                return (
                    f"[Error] docker compose logs exited with code {result.returncode}\n"
                    + result.stderr[:500]
                )
            return output
        except subprocess.TimeoutExpired:
            logger.error("[AdminSidecar/logs] docker compose logs timed out after 30s")
            return "[Error] Log fetch timed out after 30 seconds"
        except FileNotFoundError:
            logger.error(
                "[AdminSidecar/logs] 'docker' command not found — "
                "is the Docker socket mounted?"
            )
            return (
                "[Error] 'docker' command not found. "
                "Mount /var/run/docker.sock and install the Docker CLI in this container."
            )
        except Exception as exc:
            logger.error("[AdminSidecar/logs] Unexpected error: %s", exc, exc_info=True)
            return f"[Error] Failed to fetch logs: {exc}"

    raw = await asyncio.to_thread(_run)

    # Apply optional regex search filter
    if search and raw and not raw.startswith("[Error]"):
        try:
            pattern = re.compile(search, re.IGNORECASE)
            matched = [line for line in raw.splitlines() if pattern.search(line)]
            raw = ("\n".join(matched) + "\n") if matched else f"[No lines matched: {search!r}]\n"
        except re.error as exc:
            raw = f"[Warning] Invalid search pattern {search!r}: {exc}\n\n" + raw

    return raw


# =============================================================================
# Update helper
# =============================================================================

def _run_update_script() -> tuple[bool, str]:
    """
    Execute the full update sequence synchronously (intended for asyncio.to_thread).

    Steps:
      1. git pull              — fetch latest code
      2. docker compose build  — rebuild the target service image
      3. docker compose up -d  — restart the target service

    Returns:
        (success: bool, log_output: str)
    """
    work_dir = _GIT_WORK_DIR
    compose_file_abs = (
        os.path.join(work_dir, _COMPOSE_FILE) if _COMPOSE_FILE else None
    )
    target = _SERVICE_UPDATE_TARGET

    log_lines: list[str] = []

    def _step(label: str, cmd: list[str], timeout: int) -> bool:
        """Run one step; append output to log_lines; return success."""
        log_lines.append(f"=== {label} ===")
        logger.info("[AdminSidecar/update] Step '%s': %s", label, " ".join(cmd))
        try:
            result = subprocess.run(
                cmd,
                cwd=work_dir,
                capture_output=True,
                text=True,
                timeout=timeout,
            )
            combined = (result.stdout or "") + (result.stderr or "")
            log_lines.append(combined)
            if result.returncode != 0:
                logger.error(
                    "[AdminSidecar/update] Step '%s' failed (exit %d): %s",
                    label,
                    result.returncode,
                    combined[:500],
                )
                return False
            logger.info("[AdminSidecar/update] Step '%s' succeeded", label)
            return True
        except subprocess.TimeoutExpired:
            msg = f"[Error] Timed out after {timeout}s"
            log_lines.append(msg)
            logger.error("[AdminSidecar/update] Step '%s' timed out", label)
            return False
        except FileNotFoundError as exc:
            msg = f"[Error] Command not found: {exc}"
            log_lines.append(msg)
            logger.error("[AdminSidecar/update] Step '%s' — command not found: %s", label, exc)
            return False
        except Exception as exc:
            msg = f"[Error] {exc}"
            log_lines.append(msg)
            logger.error("[AdminSidecar/update] Step '%s' unexpected error: %s", label, exc, exc_info=True)
            return False

    # Build compose base args (reused for build and up)
    compose_base = ["docker", "compose"]
    if _COMPOSE_PROJECT:
        compose_base += ["--project-name", _COMPOSE_PROJECT]
    if compose_file_abs:
        compose_base += ["-f", compose_file_abs]

    # Step 1: git pull
    if not _step("git pull", ["git", "pull"], _STEP_TIMEOUT_GIT):
        return False, "\n".join(log_lines)

    # Step 2: docker compose build
    if not _step(
        f"docker compose build {target}",
        compose_base + ["build", target],
        _STEP_TIMEOUT_BUILD,
    ):
        return False, "\n".join(log_lines)

    # Step 3: docker compose up -d
    if not _step(
        f"docker compose up -d {target}",
        compose_base + ["up", "-d", target],
        _STEP_TIMEOUT_UP,
    ):
        return False, "\n".join(log_lines)

    return True, "\n".join(log_lines)


async def _run_update_background() -> None:
    """
    Run the update sequence in a background thread and release the lock when done.
    Meant to be launched as an asyncio background task via asyncio.create_task().
    """
    global _update_in_progress
    logger.info("[AdminSidecar/update] Starting background update")
    try:
        success, output = await asyncio.to_thread(_run_update_script)
        if success:
            logger.info("[AdminSidecar/update] Update completed successfully")
        else:
            logger.error("[AdminSidecar/update] Update FAILED:\n%s", output[-2000:])
    finally:
        _update_in_progress = False
        logger.info("[AdminSidecar/update] Lock released")


# =============================================================================
# Routes
# =============================================================================

@app.get("/health", include_in_schema=False)
async def health() -> dict:
    """Liveness probe for Docker healthcheck."""
    return {"status": "ok", "service": "admin-sidecar"}


@app.get(
    "/admin/logs",
    response_class=PlainTextResponse,
    summary="Fetch Docker Compose logs",
    description=(
        "Returns recent logs from Docker Compose containers on this VM. "
        "Requires X-Admin-Log-Key header matching ADMIN_LOG_API_KEY env var."
    ),
)
async def get_admin_logs(
    services: Optional[str] = Query(
        default=None,
        description="Comma-separated list of services. Defaults to all allowed services.",
    ),
    lines: int = Query(
        default=100,
        ge=1,
        le=_MAX_LINES,
        description=f"Number of log lines per service (max {_MAX_LINES})",
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
    """Fetch Docker Compose logs. Auth via X-Admin-Log-Key."""
    _require_admin_key(x_admin_log_key)

    # Parse and validate requested services
    if services:
        requested = {s.strip() for s in services.split(",") if s.strip()}
        if _SERVICES_ALLOWED:
            unknown = requested - _SERVICES_ALLOWED
            if unknown:
                raise HTTPException(
                    status_code=400,
                    detail=(
                        f"Unknown service(s): {sorted(unknown)}. "
                        f"Allowed: {sorted(_SERVICES_ALLOWED)}"
                    ),
                )
        service_list = sorted(requested)
    elif _SERVICES_ALLOWED:
        # Default: first service in the allowed set (deterministic)
        service_list = [sorted(_SERVICES_ALLOWED)[0]]
    else:
        # No filter configured — fetch all services
        service_list = []

    output = await _fetch_docker_logs(
        services=service_list,
        lines=lines,
        since_minutes=since_minutes,
        search=search,
    )
    return PlainTextResponse(content=output)


@app.post(
    "/admin/update",
    summary="Trigger self-update (git pull + rebuild + restart)",
    description=(
        "Runs git pull, rebuilds the target Docker service image, and restarts it. "
        "Returns 202 immediately; update runs in the background. "
        "Use GET /admin/logs to monitor progress. "
        "Requires X-Admin-Log-Key header matching ADMIN_LOG_API_KEY env var.\n\n"
        "Returns 409 if an update is already in progress."
    ),
)
async def post_admin_update(
    x_admin_log_key: Optional[str] = Header(None),
) -> JSONResponse:
    """
    Trigger a self-update: git pull → docker compose build → docker compose up -d.

    Returns 202 immediately. The update runs as a background task.
    Use GET /admin/logs to monitor progress.

    Returns 409 if an update is already running.
    Returns 503 if SERVICE_UPDATE_TARGET is not configured.
    """
    global _update_in_progress

    _require_admin_key(x_admin_log_key)

    if not _SERVICE_UPDATE_TARGET:
        logger.error(
            "[AdminSidecar/update] SERVICE_UPDATE_TARGET env var is not set — "
            "cannot run update"
        )
        raise HTTPException(
            status_code=503,
            detail="Update endpoint not configured (SERVICE_UPDATE_TARGET not set)",
        )

    if _update_in_progress:
        logger.warning("[AdminSidecar/update] Update already in progress — rejecting request")
        raise HTTPException(
            status_code=409,
            detail="An update is already in progress. Check /admin/logs for progress.",
        )

    _update_in_progress = True
    logger.info(
        "[AdminSidecar/update] Update triggered for service '%s'", _SERVICE_UPDATE_TARGET
    )

    # Fire-and-forget: run in background, return 202 immediately
    asyncio.create_task(_run_update_background())

    return JSONResponse(
        status_code=202,
        content={
            "status": "accepted",
            "message": (
                f"Update started for service '{_SERVICE_UPDATE_TARGET}'. "
                "Use GET /admin/logs to monitor progress."
            ),
        },
    )


# =============================================================================
# Startup log
# =============================================================================

@app.on_event("startup")
async def _log_config() -> None:
    """Log effective configuration at startup."""
    logger.info("=" * 60)
    logger.info("OpenMates Admin Sidecar starting")
    logger.info("  COMPOSE_PROJECT:       %s", _COMPOSE_PROJECT or "(not set)")
    logger.info("  COMPOSE_FILE:          %s", _COMPOSE_FILE or "(not set)")
    logger.info("  SERVICES_ALLOWED:      %s", sorted(_SERVICES_ALLOWED) or "(all)")
    logger.info("  SERVICE_UPDATE_TARGET: %s", _SERVICE_UPDATE_TARGET or "(not set — update disabled)")
    logger.info("  GIT_WORK_DIR:          %s", _GIT_WORK_DIR)
    logger.info("  PORT:                  %d", _PORT)
    logger.info("  ADMIN_LOG_API_KEY set: %s", bool(_ADMIN_KEY))
    logger.info("=" * 60)


# =============================================================================
# Entry point (dev only — production uses Dockerfile CMD)
# =============================================================================

if __name__ == "__main__":
    import uvicorn
    uvicorn.run("main:app", host="0.0.0.0", port=_PORT, log_level="info")
