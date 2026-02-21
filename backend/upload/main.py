# backend/upload/main.py
#
# FastAPI application entrypoint for the app-uploads microservice.
#
# This service handles file uploads from the browser:
#   - Authenticates the user via cookie (forwarded to core API's internal endpoint)
#   - Scans files for malware (ClamAV via TCP socket)
#   - Detects AI-generated images (SightEngine, non-blocking)
#   - Generates WEBP previews (Pillow)
#   - Encrypts files with AES-256-GCM (pure local encryption, no Vault)
#   - Wraps AES keys via core API internal endpoint (Vault Transit proxy)
#   - Uploads encrypted files to S3 (chatfiles bucket)
#   - Returns embed metadata the client uses to build TOON content
#
# All heavy services (ClamAV, S3, SightEngine) are initialised once at
# startup and stored in app.state for reuse across requests.
#
# Security architecture:
#   - This service runs on a SEPARATE VM with zero access to the main Vault,
#     Directus, or any user data.
#   - A local Vault (dev mode) stores ONLY S3 and SightEngine credentials.
#   - All Directus queries and Vault Transit key wrapping are proxied through
#     the core API's /internal/uploads/* endpoints.
#   - If this VM is compromised, the attacker gets only S3 write credentials
#     and SightEngine keys. They cannot decrypt existing files, access user
#     data, or reach the main Vault.
#
# Architecture: This service is intentionally self-contained. It does not
# import from backend.core or backend.shared to keep its dependency surface
# minimal and its Docker image lean.

import logging
import os
from contextlib import asynccontextmanager

from fastapi import FastAPI
from slowapi import Limiter, _rate_limit_exceeded_handler
from slowapi.errors import RateLimitExceeded
from slowapi.util import get_remote_address

from backend.upload.routes.upload_route import router as upload_router
from backend.upload.services.malware_scanner import MalwareScannerService
from backend.upload.services.file_encryption import FileEncryptionService
from backend.upload.services.preview_generator import PreviewGeneratorService
from backend.upload.services.sightengine_service import SightEngineService
from backend.upload.services.s3_upload import UploadsS3Service

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Rate limiter — shared across all routes (stored on app.state.limiter)
# ---------------------------------------------------------------------------
limiter = Limiter(key_func=get_remote_address)


# ---------------------------------------------------------------------------
# Application lifespan — initialise services on startup
# ---------------------------------------------------------------------------

@asynccontextmanager
async def lifespan(app: FastAPI):
    """
    Startup: initialise all heavy services once (S3, ClamAV, SightEngine, etc.).
    Shutdown: clean up resources.

    SightEngine credentials are loaded from the LOCAL Vault KV (populated by
    vault-setup init container). S3 credentials are also loaded from local
    Vault. The main Vault is never contacted from this service.
    """
    logger.info("[Uploads] Starting up app-uploads service...")

    # --- Malware scanner (ClamAV) ---
    # MalwareScannerService reads CLAMAV_HOST and CLAMAV_PORT from env vars directly
    malware_scanner = MalwareScannerService()
    try:
        await malware_scanner.health_check()
        logger.info("[Uploads] ClamAV connection: OK")
    except Exception as e:
        # ClamAV unavailable is CRITICAL — we do not start without it.
        # Uploads without malware scanning would be a security regression.
        logger.critical(f"[Uploads] ClamAV health check FAILED: {e}. Aborting startup.")
        raise RuntimeError(f"ClamAV unavailable at startup: {e}") from e
    app.state.malware_scanner = malware_scanner

    # --- File encryption (AES-256-GCM only — no Vault dependency) ---
    # Vault Transit key wrapping is handled by the core API's internal endpoint.
    # This service only generates AES keys and encrypts file bytes locally.
    file_encryption = FileEncryptionService()
    app.state.file_encryption = file_encryption
    logger.info("[Uploads] FileEncryptionService: ready (pure AES-256-GCM, no Vault)")

    # --- Image preview generator (Pillow) ---
    preview_generator = PreviewGeneratorService()
    app.state.preview_generator = preview_generator
    logger.info("[Uploads] PreviewGeneratorService: ready")

    # --- SightEngine AI detection (non-critical — graceful failure allowed) ---
    # Credentials are loaded from the LOCAL Vault KV (populated by vault-setup
    # init container from SECRET__SIGHTENGINE__* env vars). If credentials are
    # not available, detection is automatically disabled — uploads still succeed.
    sightengine = SightEngineService()
    await sightengine.initialize_from_vault(
        vault_url=os.environ.get("VAULT_URL", "http://vault:8200"),
        vault_token_path="/vault-data/api.token",
    )
    app.state.sightengine = sightengine
    if sightengine.is_enabled:
        logger.info("[Uploads] SightEngineService: ready (credentials from local Vault)")
    else:
        logger.warning(
            "[Uploads] SightEngineService: AI detection DISABLED — "
            "credentials not found in local Vault. Set SECRET__SIGHTENGINE__* env vars to enable."
        )

    # --- S3 upload service ---
    s3_service = UploadsS3Service()
    await s3_service.initialize()
    app.state.s3 = s3_service
    logger.info("[Uploads] UploadsS3Service: ready")

    # --- Rate limiter ---
    app.state.limiter = limiter

    logger.info("[Uploads] Startup complete. All services initialised.")

    yield  # Application runs here

    # Shutdown
    logger.info("[Uploads] Shutting down app-uploads service...")


# ---------------------------------------------------------------------------
# FastAPI application
# ---------------------------------------------------------------------------

app = FastAPI(
    title="OpenMates Uploads Service",
    description=(
        "Handles user file uploads with malware scanning, AI detection, "
        "preview generation, and encrypted S3 storage."
    ),
    version="1.0.0",
    lifespan=lifespan,
    # Disable default docs in production to reduce attack surface.
    # Override via environment if needed for debugging.
    docs_url="/docs" if os.environ.get("SERVER_ENVIRONMENT") != "production" else None,
    redoc_url=None,
)

# Attach rate limiter error handler
app.state.limiter = limiter
app.add_exception_handler(RateLimitExceeded, _rate_limit_exceeded_handler)

# Register upload routes
app.include_router(upload_router)


# ---------------------------------------------------------------------------
# Health endpoint (required for Docker healthcheck)
# ---------------------------------------------------------------------------

@app.get("/health", tags=["Health"])
async def health_check() -> dict:
    """
    Lightweight health check for Docker.
    Returns 200 if the service is running. Does NOT check downstream services
    (ClamAV, S3, local Vault) — those are validated at startup.
    """
    return {"status": "ok", "service": "app-uploads"}


# ---------------------------------------------------------------------------
# Entry point (for local development only — production uses Dockerfile CMD)
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    import uvicorn

    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
    )
    uvicorn.run(
        "backend.upload.main:app",
        host="0.0.0.0",
        port=int(os.environ.get("UPLOADS_APP_INTERNAL_PORT", "8000")),
        reload=False,
    )
