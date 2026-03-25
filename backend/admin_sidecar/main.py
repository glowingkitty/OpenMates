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
#   GET  /admin/logs          — fetch recent Docker Compose logs (plain text)
#   POST /admin/update        — git pull + docker compose build + docker compose up -d
#   GET  /admin/update/status — poll the current/last update status (JSON)
#   GET  /admin/version       — current version info: commit SHA, tag, branch (PUBLIC)
#   GET  /health              — liveness probe
#
# Authentication:
#   Most /admin/* endpoints require X-Admin-Log-Key matching ADMIN_LOG_API_KEY env var.
#   Exception: /admin/version is public — version info is not sensitive and the
#   sidecar is only reachable from localhost/Docker network.
#
# Configuration (all via environment variables):
#   ADMIN_LOG_API_KEY      — shared secret for X-Admin-Log-Key header (required)
#   COMPOSE_PROJECT        — docker compose --project-name value
#   COMPOSE_FILE           — path to docker-compose.yml (absolute or relative to GIT_WORK_DIR)
#   SERVICES_ALLOWED       — comma-separated list of log-queryable services
#   SERVICE_UPDATE_TARGET  — service name to rebuild and restart on /admin/update
#   SERVICE_UPDATE_EXTRAS  — comma-separated list of ADDITIONAL services to restart after
#                            the main target (e.g. "vault-setup" to re-populate secrets).
#                            These are restarted with `docker compose up -d`, not rebuilt.
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
import datetime
import logging
import os
import re
import subprocess
import sys
import time
from pathlib import Path
from typing import Optional

from fastapi import FastAPI, Header, HTTPException, Query
from fastapi.responses import JSONResponse, PlainTextResponse
from pydantic import BaseModel

# =============================================================================
# Configuration
# =============================================================================

_ADMIN_KEY = os.environ.get("ADMIN_LOG_API_KEY", "")
_COMPOSE_PROJECT = os.environ.get("COMPOSE_PROJECT", "")
_COMPOSE_FILE = os.environ.get("COMPOSE_FILE", "")
_SERVICES_ALLOWED_RAW = os.environ.get("SERVICES_ALLOWED", "")
_SERVICE_UPDATE_TARGET = os.environ.get("SERVICE_UPDATE_TARGET", "")
_SERVICE_UPDATE_EXTRAS_RAW = os.environ.get("SERVICE_UPDATE_EXTRAS", "")
_SERVICE_UPDATE_ALL = os.environ.get("SERVICE_UPDATE_ALL", "").lower() in ("true", "1", "yes")
_CLEAR_CACHE_ON_UPDATE = os.environ.get("CLEAR_CACHE_ON_UPDATE", "").lower() in ("true", "1", "yes")
_CACHE_VOLUME_NAME = os.environ.get("CACHE_VOLUME_NAME", "")
_GIT_WORK_DIR = os.environ.get("GIT_WORK_DIR", "/app")
_PORT = int(os.environ.get("PORT", "8001"))

# Parse allowed services into a set (empty means all services in the project)
_SERVICES_ALLOWED: set[str] = {
    s.strip() for s in _SERVICES_ALLOWED_RAW.split(",") if s.strip()
}

# Parse extra services to restart after the main target (e.g. vault-setup)
_SERVICE_UPDATE_EXTRAS: list[str] = [
    s.strip() for s in _SERVICE_UPDATE_EXTRAS_RAW.split(",") if s.strip()
]

# Hard limits
_MAX_LINES = 500
_MAX_SINCE_MINUTES = 1440  # 24 hours

# Update step timeouts (seconds)
_STEP_TIMEOUT_GIT = 120    # git pull can be slow on cold fetch
_STEP_TIMEOUT_BUILD = 600  # docker compose build can take several minutes
_STEP_TIMEOUT_UP = 60      # docker compose up -d is fast

# =============================================================================
# Update state (in-memory — resets on sidecar restart)
# =============================================================================

# Whether an update is currently running (prevents concurrent updates)
_update_in_progress = False

# Result of the most recent completed update (None if none has run yet)
_last_update_result: Optional[dict] = None

# Daily test runs are now handled by a system crontab (see `crontab -l`)
# that invokes scripts/run-tests-daily.sh directly on the host.
# The sidecar no longer orchestrates test execution.


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

# Mark the host git repo as safe so git commands work inside the container
# (the repo owner UID on the host differs from the container user).
if _GIT_WORK_DIR:
    try:
        subprocess.run(
            ["git", "config", "--global", "--add", "safe.directory", _GIT_WORK_DIR],
            check=True,
            capture_output=True,
        )
    except Exception:
        pass  # Non-fatal — git commands will fail with a clear error later

app = FastAPI(
    title="OpenMates Admin Sidecar",
    description=(
        "Operational admin endpoints (logs, update) for OpenMates satellite servers. "
        "Runs as an isolated sidecar container with Docker socket access. "
        "Protected by X-Admin-Log-Key shared secret."
    ),
    version="1.1.0",
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

def _run_update_script() -> tuple[bool, str, list[dict]]:
    """
    Execute the full update sequence synchronously (intended for asyncio.to_thread).

    Steps:
      1. git pull                         — fetch latest code
      2. docker compose build <target>    — rebuild the target service image
      3. docker compose up -d <target>    — restart the target service with new image
      4. docker compose up -d <extras>    — restart any extra services (e.g. vault-setup)
                                           so that secrets/init work is re-run

    Returns:
        (success: bool, log_output: str, steps: list[dict])

        Each step dict contains:
          - name: str       — human-readable step label
          - success: bool   — whether the step completed successfully
          - duration_s: float — wall-clock seconds the step took
          - output: str     — truncated stdout+stderr (max 2000 chars)
    """
    work_dir = _GIT_WORK_DIR
    compose_file_abs = (
        os.path.join(work_dir, _COMPOSE_FILE) if _COMPOSE_FILE else None
    )
    target = _SERVICE_UPDATE_TARGET

    log_lines: list[str] = []
    steps: list[dict] = []

    def _step(label: str, cmd: list[str], timeout: int) -> bool:
        """Run one step; append output to log_lines; return success."""
        log_lines.append(f"\n=== {label} ===")
        logger.info("[AdminSidecar/update] Step '%s': %s", label, " ".join(cmd))
        step_start = time.monotonic()
        step_record: dict = {"name": label, "success": False, "duration_s": 0.0, "output": ""}
        steps.append(step_record)
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
            step_record["output"] = combined[:2000]
            step_record["duration_s"] = round(time.monotonic() - step_start, 1)
            if result.returncode != 0:
                logger.error(
                    "[AdminSidecar/update] Step '%s' FAILED (exit %d) after %.1fs:\n%s",
                    label,
                    result.returncode,
                    step_record["duration_s"],
                    combined[:1000],
                )
                return False
            logger.info(
                "[AdminSidecar/update] Step '%s' succeeded in %.1fs",
                label,
                step_record["duration_s"],
            )
            step_record["success"] = True
            return True
        except subprocess.TimeoutExpired:
            elapsed = round(time.monotonic() - step_start, 1)
            msg = f"[Error] Timed out after {timeout}s"
            log_lines.append(msg)
            step_record["output"] = msg
            step_record["duration_s"] = elapsed
            logger.error(
                "[AdminSidecar/update] Step '%s' timed out after %ds (elapsed %.1fs)",
                label,
                timeout,
                elapsed,
            )
            return False
        except FileNotFoundError as exc:
            elapsed = round(time.monotonic() - step_start, 1)
            msg = f"[Error] Command not found: {exc}"
            log_lines.append(msg)
            step_record["output"] = msg
            step_record["duration_s"] = elapsed
            logger.error(
                "[AdminSidecar/update] Step '%s' — command not found: %s", label, exc
            )
            return False
        except Exception as exc:
            elapsed = round(time.monotonic() - step_start, 1)
            msg = f"[Error] {exc}"
            log_lines.append(msg)
            step_record["output"] = msg
            step_record["duration_s"] = elapsed
            logger.error(
                "[AdminSidecar/update] Step '%s' unexpected error: %s",
                label,
                exc,
                exc_info=True,
            )
            return False

    # Build compose base args (reused for build and up)
    compose_base = ["docker", "compose"]
    if _COMPOSE_PROJECT:
        compose_base += ["--project-name", _COMPOSE_PROJECT]
    if compose_file_abs:
        compose_base += ["-f", compose_file_abs]

    # Detect deployment mode
    git_dir = os.path.join(work_dir, ".git")
    is_git_mode = os.path.isdir(git_dir)

    # Step 1: git pull (only in git mode)
    if is_git_mode:
        if not _step("git pull", ["git", "pull"], _STEP_TIMEOUT_GIT):
            return False, "\n".join(log_lines), steps
    else:
        log_lines.append("\n=== Skipping git pull (Docker Hub mode) ===")

    if _SERVICE_UPDATE_ALL:
        # Multi-service mode (core server): build ALL images first, then swap ALL at once.
        # This is the "smart grouping" strategy — build has no downtime, then ~30s swap.

        # Step 2a: Optional cache volume removal (between build and up)
        if _CLEAR_CACHE_ON_UPDATE and _CACHE_VOLUME_NAME:
            # Note: cache is cleared AFTER build but BEFORE up, so the new
            # containers start with a clean cache.
            log_lines.append(
                f"\n=== Cache clearing scheduled for volume '{_CACHE_VOLUME_NAME}' ==="
            )

        if is_git_mode:
            # Step 2b: Build all service images (no downtime — old containers keep running)
            if not _step(
                "docker compose build (all services)",
                compose_base + ["build"],
                _STEP_TIMEOUT_BUILD,
            ):
                return False, "\n".join(log_lines), steps
        else:
            # Docker Hub mode: pull pre-built images instead of building
            if not _step(
                "docker compose pull (all services)",
                compose_base + ["pull"],
                _STEP_TIMEOUT_BUILD,
            ):
                return False, "\n".join(log_lines), steps

        # Step 2c: Clear cache volume if configured
        if _CLEAR_CACHE_ON_UPDATE and _CACHE_VOLUME_NAME:
            # Stop the cache container first, remove volume, then it will be
            # recreated on the next `up -d`
            _step(
                "docker compose stop cache (for volume cleanup)",
                compose_base + ["stop", "cache"],
                _STEP_TIMEOUT_UP,
            )
            _step(
                f"docker volume rm {_CACHE_VOLUME_NAME}",
                ["docker", "volume", "rm", "-f", _CACHE_VOLUME_NAME],
                _STEP_TIMEOUT_UP,
            )

        # Step 3: Swap all containers at once (brief ~30s downtime)
        if not _step(
            "docker compose up -d (all services — swap to new images)",
            compose_base + ["up", "-d"],
            _STEP_TIMEOUT_UP,
        ):
            return False, "\n".join(log_lines), steps

    else:
        # Single-service mode (satellite servers): build and restart just the target
        if is_git_mode:
            # Step 2: docker compose build <target>
            if not _step(
                f"docker compose build {target}",
                compose_base + ["build", target],
                _STEP_TIMEOUT_BUILD,
            ):
                return False, "\n".join(log_lines), steps
        else:
            # Docker Hub mode: pull just the target image
            if not _step(
                f"docker compose pull {target}",
                compose_base + ["pull", target],
                _STEP_TIMEOUT_BUILD,
            ):
                return False, "\n".join(log_lines), steps

        # Step 3: docker compose up -d <target>
        if not _step(
            f"docker compose up -d {target}",
            compose_base + ["up", "-d", target],
            _STEP_TIMEOUT_UP,
        ):
            return False, "\n".join(log_lines), steps

    # Step 4 (optional): restart extra services (e.g. vault-setup re-populates secrets)
    # These are NOT rebuilt — just restarted so their entrypoint re-runs.
    if _SERVICE_UPDATE_EXTRAS:
        extras_label = ", ".join(_SERVICE_UPDATE_EXTRAS)
        if not _step(
            f"docker compose up -d {extras_label} (extras — re-init secrets/setup)",
            compose_base + ["up", "-d"] + _SERVICE_UPDATE_EXTRAS,
            _STEP_TIMEOUT_UP,
        ):
            # Extra restart failure is logged but does NOT mark the overall update as failed,
            # because the main service is already running the new code.
            logger.warning(
                "[AdminSidecar/update] Extra services restart failed — "
                "main service is still up but secrets may not be refreshed"
            )
            log_lines.append(
                "\n[Warning] Extra services restart failed — "
                "main service is running new code but secrets may need manual refresh"
            )

    return True, "\n".join(log_lines), steps


async def _run_update_background(started_at: str) -> None:
    """
    Run the update sequence in a background thread and store the result.
    Releases the in-progress lock when done and writes to _last_update_result.
    Meant to be launched as an asyncio background task via asyncio.create_task().
    """
    global _update_in_progress, _last_update_result

    logger.info("[AdminSidecar/update] Background update starting (started_at=%s)", started_at)
    wall_start = time.monotonic()

    try:
        success, output, steps = await asyncio.to_thread(_run_update_script)
        elapsed_s = round(time.monotonic() - wall_start, 1)

        if success:
            logger.info(
                "[AdminSidecar/update] Update SUCCEEDED in %.1fs", elapsed_s
            )
        else:
            logger.error(
                "[AdminSidecar/update] Update FAILED after %.1fs:\n%s",
                elapsed_s,
                output[-3000:],
            )

        _last_update_result = {
            "status": "success" if success else "failed",
            "started_at": started_at,
            "finished_at": datetime.datetime.utcnow().isoformat() + "Z",
            "duration_s": elapsed_s,
            "target": _SERVICE_UPDATE_TARGET,
            "extras": _SERVICE_UPDATE_EXTRAS,
            "steps": steps,
        }
    except Exception as exc:
        elapsed_s = round(time.monotonic() - wall_start, 1)
        logger.error(
            "[AdminSidecar/update] Unexpected error in background update after %.1fs: %s",
            elapsed_s,
            exc,
            exc_info=True,
        )
        _last_update_result = {
            "status": "failed",
            "started_at": started_at,
            "finished_at": datetime.datetime.utcnow().isoformat() + "Z",
            "duration_s": elapsed_s,
            "target": _SERVICE_UPDATE_TARGET,
            "extras": _SERVICE_UPDATE_EXTRAS,
            "steps": [],
            "error": str(exc),
        }
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
        "Use GET /admin/update/status to poll progress. "
        "Use GET /admin/logs?services=admin-sidecar to see detailed step output. "
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
    Use GET /admin/update/status to poll for completion.

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
            detail="An update is already in progress. Use GET /admin/update/status to monitor.",
        )

    _update_in_progress = True
    started_at = datetime.datetime.utcnow().isoformat() + "Z"
    logger.info(
        "[AdminSidecar/update] Update triggered for service '%s' (extras: %s) at %s",
        _SERVICE_UPDATE_TARGET,
        _SERVICE_UPDATE_EXTRAS or "none",
        started_at,
    )

    # Fire-and-forget: run in background, return 202 immediately
    asyncio.create_task(_run_update_background(started_at))

    return JSONResponse(
        status_code=202,
        content={
            "status": "accepted",
            "started_at": started_at,
            "target": _SERVICE_UPDATE_TARGET,
            "extras": _SERVICE_UPDATE_EXTRAS,
            "message": (
                f"Update started for service '{_SERVICE_UPDATE_TARGET}'. "
                "Poll GET /admin/update/status for progress, or "
                "GET /admin/logs?services=admin-sidecar to see step-by-step output."
            ),
        },
    )


@app.get(
    "/admin/update/status",
    summary="Poll the current or last update status",
    description=(
        "Returns the status of a running update (in_progress) or the result of the "
        "last completed update (success / failed). Returns 404 if no update has run "
        "since this sidecar last started. "
        "Requires X-Admin-Log-Key header matching ADMIN_LOG_API_KEY env var."
    ),
)
async def get_update_status(
    x_admin_log_key: Optional[str] = Header(None),
) -> JSONResponse:
    """
    Poll update progress.

    Possible 'status' values:
      - "in_progress" — an update is currently running
      - "success"     — the last update completed successfully
      - "failed"      — the last update failed (check 'steps' for which step failed)
      - "never_run"   — no update has run since this sidecar container started

    The 'steps' array in completed results contains per-step details:
      - name, success, duration_s, output (truncated to 2000 chars)
    """
    _require_admin_key(x_admin_log_key)

    if _update_in_progress:
        return JSONResponse(
            status_code=200,
            content={
                "status": "in_progress",
                "target": _SERVICE_UPDATE_TARGET,
                "extras": _SERVICE_UPDATE_EXTRAS,
                "message": (
                    "Update is currently running. "
                    "GET /admin/logs?services=admin-sidecar to see live step output."
                ),
            },
        )

    if _last_update_result is None:
        return JSONResponse(
            status_code=404,
            content={
                "status": "never_run",
                "message": "No update has run since this sidecar last started.",
            },
        )

    return JSONResponse(status_code=200, content=_last_update_result)


@app.get(
    "/admin/version",
    summary="Get current version info (commit SHA, branch, tag, deployment mode)",
    description=(
        "Returns the current git commit SHA, branch name, version tag, build "
        "timestamp, and deployment mode (git or docker) for this server. "
        "This endpoint is PUBLIC (no auth required) because version info is not "
        "sensitive and the sidecar is only reachable from localhost/Docker network."
    ),
)
async def get_version() -> JSONResponse:
    """
    Return current version info for this server.

    This endpoint is intentionally public (no _require_admin_key) because:
    - Version info is not sensitive (it's public on GitHub)
    - The sidecar is bound to 127.0.0.1 / Docker network only
    - The core API needs to call this without an admin key on first startup

    Detects deployment mode by checking for .git directory:
    - If .git exists in GIT_WORK_DIR -> git mode
    - Otherwise -> docker mode

    Version info is read from:
    1. BUILD_COMMIT_SHA / BUILD_BRANCH / BUILD_TIMESTAMP env vars (if set at build time)
    2. git commands (if running in git mode with volume-mounted repo)
    3. git describe --tags for the nearest release tag
    """
    work_dir = _GIT_WORK_DIR
    git_dir = os.path.join(work_dir, ".git")

    # Detect deployment mode
    deployment_mode = "git" if os.path.isdir(git_dir) else "docker"

    # Try build-time env vars first
    sha = os.environ.get("BUILD_COMMIT_SHA", "")
    branch = os.environ.get("BUILD_BRANCH", "")
    build_timestamp = os.environ.get("BUILD_TIMESTAMP", "")
    message = os.environ.get("BUILD_COMMIT_MESSAGE", "")

    # Fall back to git commands if env vars not set and .git exists
    if not sha and deployment_mode == "git":
        try:
            result = subprocess.run(
                ["git", "rev-parse", "HEAD"],
                capture_output=True, text=True, timeout=5, cwd=work_dir,
            )
            sha = result.stdout.strip()
        except Exception as e:
            logger.warning("[AdminSidecar/version] git rev-parse failed: %s", e)

    if not branch and deployment_mode == "git":
        try:
            result = subprocess.run(
                ["git", "rev-parse", "--abbrev-ref", "HEAD"],
                capture_output=True, text=True, timeout=5, cwd=work_dir,
            )
            branch = result.stdout.strip()
        except Exception as e:
            logger.warning("[AdminSidecar/version] git branch detection failed: %s", e)

    if not message and sha and deployment_mode == "git":
        try:
            result = subprocess.run(
                ["git", "log", "-1", "--format=%s"],
                capture_output=True, text=True, timeout=5, cwd=work_dir,
            )
            message = result.stdout.strip()
        except Exception as e:
            logger.warning("[AdminSidecar/version] git log failed: %s", e)

    # Get the latest version tag (e.g. "v0.5.0-alpha").
    # We use `git tag --sort=-v:refname` (latest by version sort) instead of
    # `git describe --tags --abbrev=0` because describe only finds tags that
    # are ancestors of HEAD. On `dev`, tags created on `main` would be missed.
    tag = os.environ.get("BUILD_VERSION_TAG", "")
    if not tag and deployment_mode == "git":
        try:
            result = subprocess.run(
                ["git", "tag", "--sort=-v:refname"],
                capture_output=True, text=True, timeout=5, cwd=work_dir,
            )
            if result.returncode == 0 and result.stdout.strip():
                tag = result.stdout.strip().splitlines()[0]
        except Exception as e:
            logger.warning("[AdminSidecar/version] git tag listing failed: %s", e)

    # Build the tag URL (GitHub release page)
    tag_url = ""
    if tag:
        tag_url = f"https://github.com/glowingkitty/OpenMates/releases/tag/{tag}"

    commit_info = None
    if sha:
        commit_info = {
            "sha": sha,
            "short_sha": sha[:7],
            "message": message,
            "date": build_timestamp,
            "tag": tag,
            "tag_url": tag_url,
        }

    return JSONResponse(
        status_code=200,
        content={
            "deployment_mode": deployment_mode,
            "branch": branch,
            "build_timestamp": build_timestamp,
            "commit": commit_info,
            "tag": tag,
            "tag_url": tag_url,
            "service_update_target": _SERVICE_UPDATE_TARGET,
        },
    )






# =============================================================================
# Admin-triggered claude issue investigation
# =============================================================================

class _InvestigateRequest(BaseModel):
    """Payload sent by the API container to trigger a Claude Code investigation."""
    issue_id: str
    issue_title: str
    issue_description: str = ""
    chat_or_embed_url: str = ""
    console_logs: str = ""
    action_history: str = ""
    screenshot_presigned_url: str = ""
    environment: str = "development"
    domain: str = ""


def _build_investigate_prompt(data: _InvestigateRequest) -> str:
    """
    Load the prompt template and substitute all placeholders.

    Template path: scripts/prompts/admin-issue-investigation.md (relative to GIT_WORK_DIR).
    Falls back to an inline minimal prompt if the file is missing.
    """
    template_path = Path(_GIT_WORK_DIR) / "scripts" / "prompts" / "admin-issue-investigation.md"

    if template_path.is_file():
        template = template_path.read_text()
    else:
        logger.warning(
            "[AdminSidecar/investigate] Prompt template not found at %s — using inline fallback",
            template_path,
        )
        template = (
            "You are investigating a user-reported issue for the OpenMates project.\n\n"
            "Environment: {{ENVIRONMENT}}\nDomain: {{DOMAIN}}\n"
            "Issue ID: {{ISSUE_ID}}\nTitle: {{ISSUE_TITLE}}\n"
            "Description:\n{{ISSUE_DESCRIPTION}}\n\n"
            "Console logs:\n{{CONSOLE_LOGS}}\n\n"
            "Action history:\n{{ACTION_HISTORY}}\n\n"
            "Screenshot: {{SCREENSHOT_URL}}\n\n"
            "Diagnose the root cause and propose a concrete fix."
        )

    date_str = datetime.datetime.utcnow().strftime("%Y-%m-%d %H:%M UTC")

    return (
        template
        .replace("{{ISSUE_ID}}", data.issue_id)
        .replace("{{ISSUE_TITLE}}", data.issue_title)
        .replace("{{ISSUE_DESCRIPTION}}", data.issue_description or "(not provided)")
        .replace("{{CHAT_OR_EMBED_URL}}", data.chat_or_embed_url or "(none)")
        .replace("{{CONSOLE_LOGS}}", data.console_logs or "(not provided)")
        .replace("{{ACTION_HISTORY}}", data.action_history or "(not provided)")
        .replace("{{SCREENSHOT_URL}}", data.screenshot_presigned_url or "(no screenshot)")
        .replace("{{ENVIRONMENT}}", data.environment)
        .replace("{{DOMAIN}}", data.domain or "(unknown)")
        .replace("{{DATE}}", date_str)
    )


def _write_agent_trigger(data: _InvestigateRequest) -> str:
    """
    Write a JSON trigger file to the shared bind-mount so the host-side
    agent-trigger-watcher.sh can pick it up and run claude on the host.

    The sidecar runs inside Docker and cannot execute host binaries (claude).
    Instead it writes a trigger file to ``<GIT_WORK_DIR>/scripts/.agent-triggers/``
    which is on the bind-mounted project root, visible to the host.

    Returns:
        The path to the written trigger file.
    """
    import json as _json

    prompt = _build_investigate_prompt(data)
    date_str = datetime.datetime.utcnow().strftime("%Y-%m-%d")
    session_title = f"issue-investigation {data.issue_id[:8]} {date_str}"

    trigger_dir = Path(_GIT_WORK_DIR) / "scripts" / ".agent-triggers"
    trigger_dir.mkdir(parents=True, exist_ok=True)

    trigger_file = trigger_dir / f"{data.issue_id}.json"
    payload = {
        "issue_id": data.issue_id,
        "prompt": prompt,
        "session_title": session_title,
        "environment": data.environment,
        "domain": data.domain,
        "created_at": datetime.datetime.utcnow().isoformat() + "Z",
    }

    trigger_file.write_text(_json.dumps(payload, indent=2))
    logger.info(
        "[AdminSidecar/investigate] Wrote trigger file: %s (issue_id=%s)",
        trigger_file,
        data.issue_id,
    )
    return str(trigger_file)


@app.post(
    "/admin/claude-investigate",
    summary="Trigger a Claude Code plan-mode investigation for a reported issue",
    description=(
        "Called by the API container when an admin submits an issue report with "
        "'Submit to agent' enabled. Writes a JSON trigger file to the shared "
        "bind-mount at scripts/.agent-triggers/ for the host-side watcher to "
        "pick up and run claude. "
        "Requires X-Admin-Log-Key header matching ADMIN_LOG_API_KEY env var."
    ),
    include_in_schema=False,
)
async def post_claude_investigate(
    body: _InvestigateRequest,
    x_admin_log_key: Optional[str] = Header(None),
) -> JSONResponse:
    """
    Write a trigger file for host-side claude investigation.

    Returns 202 immediately. The host-side agent-trigger-watcher.sh service
    polls for new trigger files and runs claude on the host where the
    binary is installed.
    """
    _require_admin_key(x_admin_log_key)

    logger.info(
        "[AdminSidecar/investigate] Received investigation request "
        "(issue_id=%s, env=%s, domain=%s)",
        body.issue_id,
        body.environment,
        body.domain,
    )

    try:
        trigger_path = _write_agent_trigger(body)
    except Exception as exc:
        logger.error(
            "[AdminSidecar/investigate] Failed to write trigger file "
            "(issue_id=%s): %s",
            body.issue_id,
            exc,
            exc_info=True,
        )
        return JSONResponse(
            status_code=500,
            content={
                "status": "error",
                "issue_id": body.issue_id,
                "message": f"Failed to write trigger file: {exc}",
            },
        )

    return JSONResponse(
        status_code=202,
        content={
            "status": "accepted",
            "issue_id": body.issue_id,
            "trigger_file": trigger_path,
            "message": (
                "Trigger file written. The host-side agent-trigger-watcher "
                "will pick it up and start a Claude Code investigation."
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
    logger.info("  COMPOSE_PROJECT:         %s", _COMPOSE_PROJECT or "(not set)")
    logger.info("  COMPOSE_FILE:            %s", _COMPOSE_FILE or "(not set)")
    logger.info("  SERVICES_ALLOWED:        %s", sorted(_SERVICES_ALLOWED) or "(all)")
    logger.info(
        "  SERVICE_UPDATE_TARGET:   %s",
        _SERVICE_UPDATE_TARGET or "(not set — update disabled)",
    )
    logger.info(
        "  SERVICE_UPDATE_EXTRAS:   %s",
        _SERVICE_UPDATE_EXTRAS or "(none)",
    )
    logger.info(
        "  SERVICE_UPDATE_ALL:      %s",
        _SERVICE_UPDATE_ALL,
    )
    logger.info(
        "  CLEAR_CACHE_ON_UPDATE:   %s",
        _CLEAR_CACHE_ON_UPDATE,
    )
    logger.info(
        "  CACHE_VOLUME_NAME:       %s",
        _CACHE_VOLUME_NAME or "(not set)",
    )
    logger.info("  GIT_WORK_DIR:            %s", _GIT_WORK_DIR)
    logger.info("  PORT:                    %d", _PORT)
    logger.info("  ADMIN_LOG_API_KEY set:   %s", bool(_ADMIN_KEY))
    logger.info("=" * 60)


# =============================================================================
# Entry point (dev only — production uses Dockerfile CMD)
# =============================================================================

if __name__ == "__main__":
    import uvicorn
    uvicorn.run("main:app", host="0.0.0.0", port=_PORT, log_level="info")
