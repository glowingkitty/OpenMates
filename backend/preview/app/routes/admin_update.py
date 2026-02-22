# backend/preview/app/routes/admin_update.py
#
# POST /admin/update — pull latest code and rebuild/restart Docker containers.
#
# This endpoint allows the admin CLI to trigger a full self-update of the
# preview server: git pull + docker compose build + docker compose up.
#
# IMPORTANT: This endpoint exists ONLY on the preview and upload satellite servers.
# It must NEVER be added to the production/dev core API server.
# The core API server runs sensitive user data services and must remain isolated.
#
# Authentication:
#   Requests must include `X-Admin-Log-Key: <key>` matching the
#   ADMIN_LOG_API_KEY environment variable on this VM.
#
# Usage via admin_debug_cli.py (from the dev/prod API server):
#   docker exec api python /app/backend/scripts/admin_debug_cli.py preview-update
#
# What this does (in order):
#   1. cd to the project root (GIT_WORK_DIR env var, defaults to /app)
#   2. git pull (fetches latest code from the current branch)
#   3. docker compose build <service> (rebuilds the image with new code)
#   4. docker compose up -d <service> (restarts the container)
#
# Security considerations:
#   - Protected by the same X-Admin-Log-Key secret used for /admin/logs.
#   - git pull is limited to the current branch — no branch switching.
#   - All subprocess calls use list args (no shell=True) — no shell injection.
#   - Docker socket must be mounted (already required for /admin/logs).
#   - The container running this code needs write access to the project dir
#     (already required by the existing docker socket setup).
#   - Output is streamed as plain text for live progress monitoring.
#   - This endpoint is intentionally NOT available on the core API server.

import asyncio
import logging
import os
import subprocess
from typing import Optional

from fastapi import APIRouter, Header, HTTPException
from fastapi.responses import StreamingResponse

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/admin", tags=["Admin"])

# ---------------------------------------------------------------------------
# Configuration
# ---------------------------------------------------------------------------

# Docker Compose project name (matches name: in docker-compose.preview.yml)
_COMPOSE_PROJECT = "openmates-preview"

# Service name within the compose stack to rebuild and restart
_SERVICE_NAME = "preview"

# Compose file path (relative to project root or absolute)
_COMPOSE_FILE = "backend/preview/docker-compose.preview.yml"

# Default working directory — the git repository root.
# Override via GIT_WORK_DIR env var if the project is checked out elsewhere.
_GIT_WORK_DIR = os.environ.get("GIT_WORK_DIR", "/app")

# Timeout for each individual subprocess step (seconds)
_STEP_TIMEOUT_GIT = 120    # git pull can be slow on first run
_STEP_TIMEOUT_BUILD = 600  # docker build can take several minutes
_STEP_TIMEOUT_UP = 60      # docker compose up -d is fast


# ---------------------------------------------------------------------------
# Auth helper (re-uses same pattern as admin_logs.py)
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
            "[AdminUpdate] ADMIN_LOG_API_KEY is not configured — "
            "set this env var to enable the admin update endpoint"
        )
        raise HTTPException(
            status_code=503,
            detail="Admin update endpoint is not configured on this server (ADMIN_LOG_API_KEY not set)",
        )
    if not x_admin_log_key or x_admin_log_key != expected_key:
        logger.warning("[AdminUpdate] Rejected request with invalid or missing X-Admin-Log-Key")
        raise HTTPException(status_code=401, detail="Invalid or missing admin log API key")


# ---------------------------------------------------------------------------
# Update logic
# ---------------------------------------------------------------------------

def _run_step(cmd: list[str], cwd: str, timeout: int, step_label: str) -> tuple[bool, str]:
    """
    Run a single update step as a subprocess.

    Args:
        cmd:         Command as a list of arguments (no shell=True — injection safe).
        cwd:         Working directory for the command.
        timeout:     Hard timeout in seconds.
        step_label:  Human-readable step name for log messages.

    Returns:
        (success: bool, output: str)
    """
    logger.info(f"[AdminUpdate] Running step '{step_label}': {' '.join(cmd)}")
    try:
        result = subprocess.run(
            cmd,
            cwd=cwd,
            capture_output=True,
            text=True,
            timeout=timeout,
        )
        combined = (result.stdout or "") + (result.stderr or "")
        if result.returncode != 0:
            logger.error(
                f"[AdminUpdate] Step '{step_label}' failed "
                f"(exit {result.returncode}): {combined[:500]}"
            )
            return False, combined
        logger.info(f"[AdminUpdate] Step '{step_label}' succeeded")
        return True, combined
    except subprocess.TimeoutExpired:
        msg = f"[Error] Step '{step_label}' timed out after {timeout}s"
        logger.error(f"[AdminUpdate] {msg}")
        return False, msg + "\n"
    except FileNotFoundError as exc:
        msg = f"[Error] Command not found for step '{step_label}': {exc}"
        logger.error(f"[AdminUpdate] {msg}")
        return False, msg + "\n"
    except Exception as exc:
        msg = f"[Error] Unexpected error in step '{step_label}': {exc}"
        logger.error(f"[AdminUpdate] {msg}", exc_info=True)
        return False, msg + "\n"


async def _run_update() -> asyncio.Queue:
    """
    Execute the full update sequence and push progress lines into an asyncio Queue.

    Runs each step in the thread pool to avoid blocking the event loop.
    Pushes None as sentinel when done.

    Returns:
        An asyncio.Queue that yields str lines and ends with None.
    """
    queue: asyncio.Queue[Optional[str]] = asyncio.Queue()

    async def _produce() -> None:
        """Run all update steps, pushing progress text into the queue."""
        work_dir = _GIT_WORK_DIR
        compose_file = os.path.join(work_dir, _COMPOSE_FILE)

        await queue.put("[AdminUpdate] Starting update for preview server\n")
        await queue.put(f"[AdminUpdate] Work dir: {work_dir}\n")
        await queue.put(f"[AdminUpdate] Compose file: {compose_file}\n")
        await queue.put(f"[AdminUpdate] Service: {_SERVICE_NAME}\n\n")

        # ----------------------------------------------------------------
        # Step 1: git pull
        # ----------------------------------------------------------------
        await queue.put("=== Step 1/3: git pull ===\n")
        success, output = await asyncio.to_thread(
            _run_step,
            ["git", "pull"],
            work_dir,
            _STEP_TIMEOUT_GIT,
            "git pull",
        )
        await queue.put(output)
        if not success:
            await queue.put("\n[FAILED] git pull failed. Aborting update.\n")
            await queue.put(None)
            return
        await queue.put("\n")

        # ----------------------------------------------------------------
        # Step 2: docker compose build
        # ----------------------------------------------------------------
        await queue.put("=== Step 2/3: docker compose build ===\n")
        success, output = await asyncio.to_thread(
            _run_step,
            [
                "docker", "compose",
                "--project-name", _COMPOSE_PROJECT,
                "-f", compose_file,
                "build", _SERVICE_NAME,
            ],
            work_dir,
            _STEP_TIMEOUT_BUILD,
            "docker compose build",
        )
        await queue.put(output)
        if not success:
            await queue.put("\n[FAILED] docker compose build failed. Aborting update.\n")
            await queue.put(None)
            return
        await queue.put("\n")

        # ----------------------------------------------------------------
        # Step 3: docker compose up -d
        # ----------------------------------------------------------------
        await queue.put("=== Step 3/3: docker compose up -d ===\n")
        success, output = await asyncio.to_thread(
            _run_step,
            [
                "docker", "compose",
                "--project-name", _COMPOSE_PROJECT,
                "-f", compose_file,
                "up", "-d", _SERVICE_NAME,
            ],
            work_dir,
            _STEP_TIMEOUT_UP,
            "docker compose up -d",
        )
        await queue.put(output)
        if not success:
            await queue.put("\n[FAILED] docker compose up failed.\n")
            await queue.put(None)
            return

        await queue.put("\n=== Update completed successfully ===\n")
        await queue.put(None)  # Sentinel — done

    # Launch the producer as a background task
    asyncio.create_task(_produce())
    return queue


async def _stream_update():
    """
    Generator that yields update progress lines as they become available.

    Used as the body of a StreamingResponse so the caller sees live output.
    """
    queue = await _run_update()
    while True:
        item = await queue.get()
        if item is None:
            break
        yield item


# ---------------------------------------------------------------------------
# Route
# ---------------------------------------------------------------------------

@router.post(
    "/update",
    response_class=StreamingResponse,
    summary="Pull latest code and rebuild/restart preview server",
    description=(
        "Triggers a self-update of the preview server:\n"
        "1. git pull\n"
        "2. docker compose build preview\n"
        "3. docker compose up -d preview\n\n"
        "Requires X-Admin-Log-Key header matching ADMIN_LOG_API_KEY env var.\n"
        "Called by: `admin_debug_cli.py preview-update`\n\n"
        "NOTE: This endpoint is intentionally absent from the core API server."
    ),
)
async def post_admin_update(
    x_admin_log_key: Optional[str] = Header(None),
) -> StreamingResponse:
    """
    Trigger a full self-update of the preview server.

    Auth: X-Admin-Log-Key header must match ADMIN_LOG_API_KEY env var.

    The response is streamed plain text — each line is a progress update.
    The request stays open until all steps complete (or one fails).

    This endpoint is intentionally NOT present on the core API server.
    """
    _require_admin_key(x_admin_log_key)

    logger.info("[AdminUpdate] Update triggered via /admin/update endpoint")

    return StreamingResponse(
        _stream_update(),
        media_type="text/plain",
    )
