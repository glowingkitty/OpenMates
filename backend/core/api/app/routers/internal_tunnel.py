# backend/core/api/app/routers/internal_tunnel.py
#
# Ephemeral Cloudflare Tunnel management for GitHub Actions CI.
#
# Provides HMAC-authenticated endpoints to open/close temporary tunnels
# that expose the dev server to remote GitHub Actions runners. Tunnels
# are short-lived (max 2 hours) and only one can be active at a time.
#
# Security:
# - HMAC-SHA256 signature validation on every request
# - Timestamp validation (60-second replay window)
# - Single-tunnel mutex (prevents parallel exposure)
# - Auto-close safety net (2-hour max TTL via background task)
#
# Architecture: docs/architecture/github-actions-ci.md

import hashlib
import hmac
import json
import logging
import os
import subprocess
import time
from typing import Optional

from fastapi import APIRouter, HTTPException, Request
from pydantic import BaseModel, Field

from backend.core.api.app.services.cache import CacheService

logger = logging.getLogger(__name__)

router = APIRouter(
    prefix="/internal/tunnel",
    tags=["Internal - Tunnel"],
)

# --- Constants ---
TUNNEL_MAX_TTL_SECONDS = 7200  # 2 hours
TUNNEL_CACHE_KEY = "ephemeral_tunnel:active"
TUNNEL_SECRET_ENV = "TUNNEL_TRIGGER_SECRET"
TIMESTAMP_TOLERANCE_SECONDS = 60


# --- Models ---

class TunnelOpenRequest(BaseModel):
    run_id: str = Field(..., max_length=200)
    requested_by: str = Field(default="github-actions", max_length=100)


class TunnelOpenResponse(BaseModel):
    tunnel_url: str
    session_id: str
    expires_in: int = TUNNEL_MAX_TTL_SECONDS


class TunnelCloseRequest(BaseModel):
    session_id: str


class TunnelCloseResponse(BaseModel):
    status: str


# --- HMAC verification ---

def _verify_hmac(request: Request, body: bytes) -> None:
    """
    Verify HMAC-SHA256 signature and timestamp freshness.
    Raises HTTPException on failure.
    """
    secret = os.getenv(TUNNEL_SECRET_ENV)
    if not secret:
        raise HTTPException(status_code=503, detail="Tunnel service not configured")

    signature = request.headers.get("X-Hmac-Signature")
    timestamp = request.headers.get("X-Timestamp")

    if not signature or not timestamp:
        raise HTTPException(status_code=401, detail="Missing signature or timestamp")

    # Timestamp freshness check (replay prevention)
    try:
        ts = int(timestamp)
        if abs(time.time() - ts) > TIMESTAMP_TOLERANCE_SECONDS:
            raise HTTPException(status_code=401, detail="Request timestamp too old or too far in future")
    except ValueError:
        raise HTTPException(status_code=401, detail="Invalid timestamp")

    # HMAC verification
    expected = hmac.new(
        secret.encode(),
        timestamp.encode() + body,
        hashlib.sha256,
    ).hexdigest()

    if not hmac.compare_digest(signature, expected):
        raise HTTPException(status_code=401, detail="Invalid HMAC signature")


# --- Endpoints ---

@router.post("/open", response_model=TunnelOpenResponse)
async def open_tunnel(request: Request):
    """
    Open an ephemeral Cloudflare Tunnel exposing the dev server.
    Only one tunnel may be active at a time.
    """
    body = await request.body()
    _verify_hmac(request, body)

    payload = TunnelOpenRequest(**json.loads(body))
    cache_service: CacheService = request.app.state.cache_service

    # --- Mutex: only one tunnel at a time ---
    existing = await cache_service.get(TUNNEL_CACHE_KEY)
    if existing:
        existing_data = json.loads(existing) if isinstance(existing, str) else existing
        raise HTTPException(
            status_code=409,
            detail=f"A tunnel is already active (session_id={existing_data.get('session_id', '?')})",
        )

    # --- Start cloudflared ---
    session_id = f"tunnel-{int(time.time())}-{payload.run_id[:20]}"

    try:
        # Use quick-tunnel (no Cloudflare account needed — generates a *.trycloudflare.com URL)
        proc = subprocess.Popen(
            ["cloudflared", "tunnel", "--url", "http://localhost:80", "--no-autoupdate"],
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
        )

        # cloudflared prints the URL to stderr — wait up to 30 seconds for it
        tunnel_url = None
        start = time.time()
        while time.time() - start < 30:
            line = proc.stderr.readline()
            if not line:
                if proc.poll() is not None:
                    break
                time.sleep(0.5)
                continue
            if "trycloudflare.com" in line and "https://" in line:
                # Extract URL from the line (format: "INF |  https://xxx.trycloudflare.com  |")
                # Must have both https:// and trycloudflare.com to avoid matching the
                # "Requesting new quick Tunnel on trycloudflare.com..." info line.
                for token in line.split():
                    token = token.strip().strip("|")
                    if token.startswith("https://") and "trycloudflare.com" in token:
                        tunnel_url = token.strip()
                        break
                if tunnel_url:
                    break

        if not tunnel_url:
            proc.terminate()
            raise HTTPException(status_code=500, detail="Failed to obtain tunnel URL from cloudflared")

        # Ensure URL has https prefix
        if not tunnel_url.startswith("https://"):
            tunnel_url = f"https://{tunnel_url}"

    except FileNotFoundError:
        raise HTTPException(
            status_code=503,
            detail="cloudflared binary not found. Install: https://developers.cloudflare.com/cloudflare-one/connections/connect-apps/install-and-setup/installation/",
        )
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Failed to start cloudflared: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail="Failed to start tunnel")

    # --- Store tunnel info in cache ---
    tunnel_info = {
        "session_id": session_id,
        "tunnel_url": tunnel_url,
        "pid": proc.pid,
        "run_id": payload.run_id,
        "requested_by": payload.requested_by,
        "opened_at": int(time.time()),
    }
    await cache_service.set(TUNNEL_CACHE_KEY, json.dumps(tunnel_info), ttl=TUNNEL_MAX_TTL_SECONDS)

    # --- Schedule auto-close safety net ---
    try:
        from backend.core.api.app.tasks.celery_config import app as celery_app
        celery_app.send_task(
            name="app.tasks.tunnel_auto_close",
            kwargs={"session_id": session_id, "pid": proc.pid},
            countdown=TUNNEL_MAX_TTL_SECONDS,
            queue="default",
        )
    except Exception as e:
        logger.warning(f"Failed to schedule tunnel auto-close task: {e}")

    logger.info(
        f"Opened ephemeral tunnel: {tunnel_url} (session={session_id}, "
        f"pid={proc.pid}, run_id={payload.run_id})"
    )

    return TunnelOpenResponse(
        tunnel_url=tunnel_url,
        session_id=session_id,
        expires_in=TUNNEL_MAX_TTL_SECONDS,
    )


@router.post("/close", response_model=TunnelCloseResponse)
async def close_tunnel(request: Request):
    """Close an active ephemeral tunnel by session ID."""
    body = await request.body()
    _verify_hmac(request, body)

    payload = TunnelCloseRequest(**json.loads(body))
    cache_service: CacheService = request.app.state.cache_service

    existing = await cache_service.get(TUNNEL_CACHE_KEY)
    if not existing:
        return TunnelCloseResponse(status="no_active_tunnel")

    tunnel_info = json.loads(existing) if isinstance(existing, str) else existing

    if tunnel_info.get("session_id") != payload.session_id:
        raise HTTPException(
            status_code=404,
            detail=f"Session {payload.session_id} does not match active tunnel",
        )

    # Kill the cloudflared process
    pid = tunnel_info.get("pid")
    if pid:
        try:
            os.kill(pid, 15)  # SIGTERM
            logger.info(f"Terminated cloudflared process (pid={pid})")
        except ProcessLookupError:
            logger.info(f"cloudflared process already gone (pid={pid})")
        except Exception as e:
            logger.warning(f"Failed to kill cloudflared (pid={pid}): {e}")

    # Remove from cache
    await cache_service.delete(TUNNEL_CACHE_KEY)

    logger.info(f"Closed tunnel session {payload.session_id}")
    return TunnelCloseResponse(status="closed")
