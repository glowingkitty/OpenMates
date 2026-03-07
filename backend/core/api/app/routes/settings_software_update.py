# backend/core/api/app/routes/settings_software_update.py
"""
REST API endpoints for software update management.

Provides admin-only endpoints for:
- Checking for available updates (GitHub commits or Docker Hub images)
- Triggering software updates across all servers
- Polling update installation status
- Retrieving current version info for all services
- Managing auto-update configuration

Architecture context: See docs/architecture/software-updates.md
Tests: (none yet)
"""

import logging
import os
import subprocess
from datetime import datetime, timezone
from typing import Dict, Any, Optional

from fastapi import APIRouter, HTTPException, Request, Depends
import httpx

from backend.core.api.app.services.directus import DirectusService
from backend.core.api.app.services.cache import CacheService
from backend.core.api.app.services.limiter import limiter
from backend.core.api.app.routes.auth_routes.auth_dependencies import get_current_user
from backend.core.api.app.models.user import User
from backend.shared.python_schemas.software_update import (
    GITHUB_REPO_OWNER,
    GITHUB_REPO_NAME,
    GITHUB_REPO_URL,
    DeploymentMode,
    UpdateStatus,
    ServerName,
    CommitInfo,
    ServiceVersionInfo,
    UpdateCheckResult,
    InstallRequest,
    ServerUpdateStatus,
    InstallStatusResponse,
    VersionsResponse,
    SoftwareUpdateConfig,
    UpdateConfigRequest,
)

logger = logging.getLogger(__name__)

router = APIRouter(
    prefix="/v1/settings/software_update",
    tags=["Software Update"]
)

# =============================================================================
# Constants
# =============================================================================

# Cache keys for update state
CACHE_KEY_UPDATE_CHECK = "software_update:last_check"
CACHE_KEY_UPDATE_STATUS = "software_update:install_status"
CACHE_KEY_UPDATE_CONFIG = "software_update:config"

# Cache TTL for update check results (seconds)
UPDATE_CHECK_CACHE_TTL = 300  # 5 minutes

# Timeout for HTTP requests to sidecars / GitHub API (seconds)
SIDECAR_REQUEST_TIMEOUT = 30
GITHUB_API_TIMEOUT = 15

# GitHub API base URL
GITHUB_API_BASE = "https://api.github.com"

# Build info environment variables (injected at Docker build time)
ENV_BUILD_COMMIT_SHA = "BUILD_COMMIT_SHA"
ENV_BUILD_BRANCH = "BUILD_BRANCH"
ENV_BUILD_TIMESTAMP = "BUILD_TIMESTAMP"

# Sidecar URL environment variables
ENV_CORE_SIDECAR_URL = "CORE_SIDECAR_URL"
ENV_UPLOAD_SIDECAR_URL = "UPLOAD_SIDECAR_URL"
ENV_PREVIEW_SIDECAR_URL = "PREVIEW_SIDECAR_URL"
ENV_UPLOAD_SIDECAR_KEY = "SECRET__UPLOAD_SERVER__ADMIN_LOG_API_KEY"
ENV_PREVIEW_SIDECAR_KEY = "SECRET__PREVIEW_SERVER__ADMIN_LOG_API_KEY"
ENV_CORE_SIDECAR_KEY = "SECRET__CORE_SERVER__ADMIN_LOG_API_KEY"


# =============================================================================
# Dependencies
# =============================================================================

def get_directus_service(request: Request) -> DirectusService:
    """Get DirectusService from app state."""
    if not hasattr(request.app.state, 'directus_service'):
        logger.error("DirectusService not found in app.state")
        raise HTTPException(status_code=500, detail="Internal configuration error")
    return request.app.state.directus_service


def get_cache_service(request: Request) -> CacheService:
    """Get CacheService from app state."""
    if not hasattr(request.app.state, 'cache_service'):
        logger.error("CacheService not found in app.state")
        raise HTTPException(status_code=500, detail="Internal configuration error")
    return request.app.state.cache_service


async def require_admin(
    current_user: User = Depends(get_current_user),
    directus_service: DirectusService = Depends(get_directus_service)
) -> User:
    """Dependency to ensure user has admin privileges."""
    is_admin = await directus_service.admin.is_user_admin(current_user.id)
    if not is_admin:
        raise HTTPException(status_code=403, detail="Admin privileges required")
    return current_user


# =============================================================================
# Helper Functions
# =============================================================================

def _detect_deployment_mode() -> DeploymentMode:
    """
    Auto-detect whether this installation uses git (cloned repo) or Docker Hub
    (pre-built images) by checking for the .git directory.

    Git-cloned setups volume-mount the project root into containers, so .git
    is visible. Docker Hub images are self-contained without .git.
    """
    # Check multiple locations where .git might be visible
    git_paths = [
        "/app/.git",           # Standard app directory
        "/app/backend/.git",   # Nested mount
    ]
    # Also check GIT_WORK_DIR if set (used by admin sidecar)
    git_work_dir = os.environ.get("GIT_WORK_DIR", "")
    if git_work_dir:
        git_paths.append(os.path.join(git_work_dir, ".git"))

    for path in git_paths:
        if os.path.isdir(path):
            return DeploymentMode.GIT

    return DeploymentMode.DOCKER


async def _get_current_commit_info() -> Optional[CommitInfo]:
    """
    Get the current commit info.

    Priority:
    1. Build-time env vars (BUILD_COMMIT_SHA etc.) — for Docker Hub images
    2. Core admin sidecar /admin/version endpoint — for git-cloned deployments
       (the API container doesn't have git, but the sidecar mounts the repo)
    3. Git commands as last resort (works if source is volume-mounted into /app)
    """
    # 1. Try build-time env vars (injected by Docker build args)
    sha = os.environ.get(ENV_BUILD_COMMIT_SHA, "")
    if sha:
        short_sha = sha[:7]
        return CommitInfo(
            sha=sha,
            short_sha=short_sha,
            message=os.environ.get("BUILD_COMMIT_MESSAGE", ""),
            date=os.environ.get(ENV_BUILD_TIMESTAMP, ""),
            url=f"{GITHUB_REPO_URL}/commit/{sha}",
            tag=os.environ.get("BUILD_VERSION_TAG", ""),
            tag_url=(
                f"{GITHUB_REPO_URL}/releases/tag/{os.environ.get('BUILD_VERSION_TAG', '')}"
                if os.environ.get("BUILD_VERSION_TAG", "") else ""
            ),
        )

    # 2. Try core admin sidecar (has git access via volume mount)
    core_sidecar_url = os.environ.get(ENV_CORE_SIDECAR_URL, "")
    if core_sidecar_url:
        sidecar_data = await _call_sidecar_public(
            core_sidecar_url, "/admin/version"
        )
        if sidecar_data and sidecar_data.get("commit"):
            commit_data = sidecar_data["commit"]
            sha = commit_data.get("sha", "")
            if sha:
                return CommitInfo(
                    sha=sha,
                    short_sha=sha[:7],
                    message=commit_data.get("message", ""),
                    date=commit_data.get("date", ""),
                    url=f"{GITHUB_REPO_URL}/commit/{sha}",
                    tag=commit_data.get("tag", ""),
                    tag_url=commit_data.get("tag_url", ""),
                )

    # 3. Fall back to git command (works when source is volume-mounted)
    try:
        sha = subprocess.run(
            ["git", "rev-parse", "HEAD"],
            capture_output=True, text=True, timeout=5,
            cwd="/app"
        ).stdout.strip()
        if not sha:
            return None

        short_sha = sha[:7]

        message = subprocess.run(
            ["git", "log", "-1", "--format=%s"],
            capture_output=True, text=True, timeout=5,
            cwd="/app"
        ).stdout.strip()

        date = subprocess.run(
            ["git", "log", "-1", "--format=%aI"],
            capture_output=True, text=True, timeout=5,
            cwd="/app"
        ).stdout.strip()

        # Try to get the nearest tag
        tag = ""
        try:
            tag_result = subprocess.run(
                ["git", "describe", "--tags", "--abbrev=0"],
                capture_output=True, text=True, timeout=5,
                cwd="/app"
            )
            if tag_result.returncode == 0:
                tag = tag_result.stdout.strip()
        except Exception:
            pass

        tag_url = f"{GITHUB_REPO_URL}/releases/tag/{tag}" if tag else ""

        return CommitInfo(
            sha=sha,
            short_sha=short_sha,
            message=message,
            date=date,
            url=f"{GITHUB_REPO_URL}/commit/{sha}",
            tag=tag,
            tag_url=tag_url,
        )
    except (subprocess.TimeoutExpired, FileNotFoundError, Exception) as e:
        logger.warning("Could not get current commit info via git: %s", e)
        return None


async def _get_current_branch() -> str:
    """
    Get the current git branch name.

    Priority:
    1. BUILD_BRANCH env var (Docker Hub builds)
    2. Core admin sidecar /admin/version endpoint
    3. Git command as last resort
    """
    branch = os.environ.get(ENV_BUILD_BRANCH, "")
    if branch:
        return branch

    # Try core admin sidecar
    core_sidecar_url = os.environ.get(ENV_CORE_SIDECAR_URL, "")
    if core_sidecar_url:
        sidecar_data = await _call_sidecar_public(
            core_sidecar_url, "/admin/version"
        )
        if sidecar_data:
            branch = sidecar_data.get("branch", "")
            if branch:
                return branch

    # Fall back to git
    try:
        result = subprocess.run(
            ["git", "rev-parse", "--abbrev-ref", "HEAD"],
            capture_output=True, text=True, timeout=5,
            cwd="/app"
        )
        return result.stdout.strip() or "unknown"
    except (subprocess.TimeoutExpired, FileNotFoundError, Exception):
        return "unknown"


async def _fetch_latest_github_commit(branch: str) -> Optional[CommitInfo]:
    """
    Fetch the latest commit from the GitHub repository for the given branch.

    Uses the GitHub API (unauthenticated: 60 req/hour, authenticated: 5000 req/hour).
    """
    github_token = os.environ.get("GITHUB_TOKEN", "")
    headers = {
        "Accept": "application/vnd.github.v3+json",
        "User-Agent": "OpenMates-Updater/1.0",
    }
    if github_token:
        headers["Authorization"] = f"token {github_token}"

    url = f"{GITHUB_API_BASE}/repos/{GITHUB_REPO_OWNER}/{GITHUB_REPO_NAME}/commits/{branch}"

    try:
        async with httpx.AsyncClient(timeout=GITHUB_API_TIMEOUT) as client:
            response = await client.get(url, headers=headers)

            if response.status_code == 403:
                logger.warning(
                    "GitHub API rate limit hit. Add GITHUB_TOKEN env var for higher limits."
                )
                return None

            if response.status_code != 200:
                logger.error(
                    "GitHub API returned %d for %s: %s",
                    response.status_code, url, response.text[:200]
                )
                return None

            data = response.json()
            sha = data.get("sha", "")
            commit_data = data.get("commit", {})

            return CommitInfo(
                sha=sha,
                short_sha=sha[:7],
                message=commit_data.get("message", "").split("\n")[0],
                date=commit_data.get("author", {}).get("date", ""),
                url=data.get("html_url", f"{GITHUB_REPO_URL}/commit/{sha}"),
            )
    except httpx.TimeoutException:
        logger.error("GitHub API request timed out for branch '%s'", branch)
        return None
    except Exception as e:
        logger.error("Failed to fetch latest commit from GitHub: %s", e, exc_info=True)
        return None


async def _count_commits_behind(current_sha: str, latest_sha: str, branch: str) -> int:
    """
    Count how many commits the current version is behind the latest.
    Uses the GitHub compare API.
    """
    if not current_sha or not latest_sha:
        return 0
    if current_sha == latest_sha:
        return 0

    github_token = os.environ.get("GITHUB_TOKEN", "")
    headers = {
        "Accept": "application/vnd.github.v3+json",
        "User-Agent": "OpenMates-Updater/1.0",
    }
    if github_token:
        headers["Authorization"] = f"token {github_token}"

    url = (
        f"{GITHUB_API_BASE}/repos/{GITHUB_REPO_OWNER}/{GITHUB_REPO_NAME}"
        f"/compare/{current_sha}...{latest_sha}"
    )

    try:
        async with httpx.AsyncClient(timeout=GITHUB_API_TIMEOUT) as client:
            response = await client.get(url, headers=headers)
            if response.status_code == 200:
                data = response.json()
                return data.get("ahead_by", 0)
    except Exception as e:
        logger.warning("Could not count commits behind: %s", e)

    return 0


async def _call_sidecar_public(
    base_url: str,
    path: str,
) -> Optional[dict]:
    """
    Make an HTTP GET request to a public (no-auth) sidecar endpoint.

    Used for /admin/version which is intentionally unauthenticated.
    Returns parsed JSON response or None on failure.
    """
    if not base_url:
        return None

    url = f"{base_url.rstrip('/')}{path}"
    try:
        async with httpx.AsyncClient(timeout=SIDECAR_REQUEST_TIMEOUT) as client:
            response = await client.get(url)
            if response.status_code == 200:
                return response.json()
            else:
                logger.warning(
                    "Sidecar public request GET %s returned %d: %s",
                    url, response.status_code, response.text[:200]
                )
                return None
    except httpx.ConnectError:
        logger.warning("Could not connect to sidecar at %s", base_url)
        return None
    except httpx.TimeoutException:
        logger.warning("Sidecar public request timed out: GET %s", url)
        return None
    except Exception as e:
        logger.error("Sidecar public request failed: GET %s: %s", url, e, exc_info=True)
        return None


async def _call_sidecar(
    base_url: str,
    path: str,
    api_key: str,
    method: str = "GET",
    json_body: Optional[dict] = None,
) -> Optional[dict]:
    """
    Make an HTTP request to an authenticated admin sidecar endpoint.

    Returns parsed JSON response or None on failure.
    """
    if not base_url or not api_key:
        return None

    url = f"{base_url.rstrip('/')}{path}"
    headers = {"X-Admin-Log-Key": api_key}

    try:
        async with httpx.AsyncClient(timeout=SIDECAR_REQUEST_TIMEOUT) as client:
            if method == "POST":
                response = await client.post(url, headers=headers, json=json_body or {})
            else:
                response = await client.get(url, headers=headers)

            if response.status_code in (200, 202):
                return response.json()
            else:
                logger.warning(
                    "Sidecar request %s %s returned %d: %s",
                    method, url, response.status_code, response.text[:200]
                )
                return None
    except httpx.ConnectError:
        logger.warning("Could not connect to sidecar at %s", base_url)
        return None
    except httpx.TimeoutException:
        logger.warning("Sidecar request timed out: %s %s", method, url)
        return None
    except Exception as e:
        logger.error("Sidecar request failed: %s %s: %s", method, url, e, exc_info=True)
        return None


async def _get_sidecar_version(
    server_name: ServerName,
    base_url: str,
    api_key: str,
) -> ServiceVersionInfo:
    """Get version info from a sidecar's /admin/version endpoint."""
    info = ServiceVersionInfo(
        name=server_name.value,
        deployment_mode=DeploymentMode.GIT,
        reachable=False,
    )

    # /admin/version is public (no auth required) — try without key first
    result = await _call_sidecar_public(base_url, "/admin/version")
    if not result:
        # Fall back to authenticated call for older sidecars
        result = await _call_sidecar(base_url, "/admin/version", api_key)
    if result:
        info.reachable = True
        if "commit" in result and result["commit"]:
            sha = result["commit"].get("sha", "")
            tag = result["commit"].get("tag", "") or result.get("tag", "")
            tag_url = result["commit"].get("tag_url", "") or result.get("tag_url", "")
            info.commit = CommitInfo(
                sha=sha,
                short_sha=sha[:7] if sha else "",
                message=result["commit"].get("message", ""),
                date=result["commit"].get("date", ""),
                url=f"{GITHUB_REPO_URL}/commit/{sha}" if sha else "",
                tag=tag,
                tag_url=tag_url,
            )
        info.branch = result.get("branch", "")
        info.build_timestamp = result.get("build_timestamp", "")
        info.deployment_mode = DeploymentMode(
            result.get("deployment_mode", "git")
        )
    else:
        info.error = "Could not reach server"

    return info


# =============================================================================
# API Endpoints
# =============================================================================

@router.get(
    "/check",
    response_model=UpdateCheckResult,
    summary="Check for available software updates",
    description=(
        "Checks whether a newer version of OpenMates is available. "
        "In git mode: compares current commit against the latest commit on GitHub. "
        "In docker mode: checks Docker Hub for newer image tags (not yet implemented). "
        "Results are cached for 5 minutes to avoid GitHub API rate limits. "
        "Admin only."
    ),
)
@limiter.limit("10/minute")
async def check_for_updates(
    request: Request,
    admin_user: User = Depends(require_admin),
    cache_service: CacheService = Depends(get_cache_service),
) -> UpdateCheckResult:
    """Check GitHub or Docker Hub for available software updates."""
    now = datetime.now(timezone.utc).isoformat()

    # Check cache first
    cached = await cache_service.get(CACHE_KEY_UPDATE_CHECK)
    if cached and isinstance(cached, dict):
        logger.info("Returning cached update check result")
        return UpdateCheckResult(**cached)

    deployment_mode = _detect_deployment_mode()

    if deployment_mode == DeploymentMode.DOCKER:
        # Docker Hub checking is not yet implemented (no images published yet)
        result = UpdateCheckResult(
            update_available=False,
            deployment_mode=deployment_mode,
            current_version=None,
            latest_version=None,
            commits_behind=0,
            checked_at=now,
            error="Docker Hub update checking is not yet available. Images are not yet published.",
        )
        return result

    # Git mode: compare current commit with latest on GitHub
    current_commit = await _get_current_commit_info()
    branch = await _get_current_branch()

    latest_commit = await _fetch_latest_github_commit(branch)

    if latest_commit is None:
        result = UpdateCheckResult(
            update_available=False,
            deployment_mode=deployment_mode,
            current_version=current_commit,
            latest_version=None,
            commits_behind=0,
            checked_at=now,
            error="Could not reach GitHub API. Check your internet connection or add GITHUB_TOKEN for higher rate limits.",
        )
        return result

    # Compare SHAs
    update_available = (
        current_commit is not None
        and current_commit.sha != latest_commit.sha
    )

    commits_behind = 0
    if update_available and current_commit:
        commits_behind = await _count_commits_behind(
            current_commit.sha, latest_commit.sha, branch
        )

    result = UpdateCheckResult(
        update_available=update_available,
        deployment_mode=deployment_mode,
        current_version=current_commit,
        latest_version=latest_commit,
        commits_behind=commits_behind,
        checked_at=now,
    )

    # Cache the result
    await cache_service.set(
        CACHE_KEY_UPDATE_CHECK,
        result.model_dump(),
        ttl=UPDATE_CHECK_CACHE_TTL,
    )

    return result


@router.post(
    "/install",
    summary="Start software update installation",
    description=(
        "Triggers a software update across all servers (core, upload, preview). "
        "Returns 202 immediately — use GET /install_status to poll progress. "
        "In git mode: runs git pull → docker compose build → docker compose up -d. "
        "Admin only."
    ),
)
@limiter.limit("2/minute")
async def install_update(
    request: Request,
    body: InstallRequest = InstallRequest(),
    admin_user: User = Depends(require_admin),
    cache_service: CacheService = Depends(get_cache_service),
) -> Dict[str, Any]:
    """Trigger software update installation on all servers."""
    now = datetime.now(timezone.utc).isoformat()

    # Check if an update is already in progress
    current_status = await cache_service.get(CACHE_KEY_UPDATE_STATUS)
    if current_status and isinstance(current_status, dict):
        if current_status.get("overall_status") == UpdateStatus.IN_PROGRESS.value:
            raise HTTPException(
                status_code=409,
                detail="An update is already in progress. Use GET /install_status to monitor."
            )

    # Initialize status in cache as IN_PROGRESS
    initial_status = InstallStatusResponse(
        overall_status=UpdateStatus.IN_PROGRESS,
        servers=[
            ServerUpdateStatus(
                server=ServerName.CORE,
                status=UpdateStatus.IN_PROGRESS,
                started_at=now,
            ),
        ],
        started_at=now,
    )

    # Add upload/preview servers if sidecar URLs are configured
    upload_url = os.environ.get(ENV_UPLOAD_SIDECAR_URL, "")
    preview_url = os.environ.get(ENV_PREVIEW_SIDECAR_URL, "")

    if upload_url:
        initial_status.servers.append(
            ServerUpdateStatus(
                server=ServerName.UPLOAD,
                status=UpdateStatus.IN_PROGRESS,
                started_at=now,
            )
        )
    if preview_url:
        initial_status.servers.append(
            ServerUpdateStatus(
                server=ServerName.PREVIEW,
                status=UpdateStatus.IN_PROGRESS,
                started_at=now,
            )
        )

    await cache_service.set(
        CACHE_KEY_UPDATE_STATUS,
        initial_status.model_dump(),
        ttl=3600,  # 1 hour TTL — install should finish well before this
    )

    # Trigger updates on all servers via their sidecars
    core_sidecar_url = os.environ.get(ENV_CORE_SIDECAR_URL, "")
    core_sidecar_key = os.environ.get(ENV_CORE_SIDECAR_KEY, "")
    upload_sidecar_key = os.environ.get(ENV_UPLOAD_SIDECAR_KEY, "")
    preview_sidecar_key = os.environ.get(ENV_PREVIEW_SIDECAR_KEY, "")

    servers_triggered = []
    errors = []

    # Trigger core server update
    if core_sidecar_url and core_sidecar_key:
        result = await _call_sidecar(
            core_sidecar_url, "/admin/update", core_sidecar_key, method="POST"
        )
        if result:
            servers_triggered.append("core")
        else:
            errors.append("Failed to trigger core server update")
    else:
        errors.append(
            "Core sidecar not configured. Set CORE_SIDECAR_URL and "
            "SECRET__CORE_SERVER__ADMIN_LOG_API_KEY environment variables."
        )

    # Trigger upload server update
    if upload_url and upload_sidecar_key:
        result = await _call_sidecar(
            upload_url, "/admin/update", upload_sidecar_key, method="POST"
        )
        if result:
            servers_triggered.append("upload")
        else:
            errors.append("Failed to trigger upload server update")

    # Trigger preview server update
    if preview_url and preview_sidecar_key:
        result = await _call_sidecar(
            preview_url, "/admin/update", preview_sidecar_key, method="POST"
        )
        if result:
            servers_triggered.append("preview")
        else:
            errors.append("Failed to trigger preview server update")

    if not servers_triggered:
        # No servers were triggered — update the cache status to failed
        failed_status = InstallStatusResponse(
            overall_status=UpdateStatus.FAILED,
            servers=[
                ServerUpdateStatus(
                    server=ServerName.CORE,
                    status=UpdateStatus.FAILED,
                    started_at=now,
                    error="; ".join(errors),
                )
            ],
            started_at=now,
        )
        await cache_service.set(
            CACHE_KEY_UPDATE_STATUS,
            failed_status.model_dump(),
            ttl=3600,
        )
        raise HTTPException(
            status_code=503,
            detail=f"Could not trigger update on any server: {'; '.join(errors)}"
        )

    # Clear the update check cache so next check reflects new state
    await cache_service.delete(CACHE_KEY_UPDATE_CHECK)

    return {
        "status": "accepted",
        "started_at": now,
        "servers_triggered": servers_triggered,
        "errors": errors if errors else None,
        "message": (
            f"Update triggered on {len(servers_triggered)} server(s). "
            "Use GET /install_status to poll progress."
        ),
    }


@router.get(
    "/install_status",
    response_model=InstallStatusResponse,
    summary="Get software update installation status",
    description=(
        "Returns the current status of a running or last completed software update. "
        "Polls each server's sidecar for real-time status. "
        "Admin only."
    ),
)
@limiter.limit("30/minute")
async def get_install_status(
    request: Request,
    admin_user: User = Depends(require_admin),
    cache_service: CacheService = Depends(get_cache_service),
) -> InstallStatusResponse:
    """Poll update installation status from all server sidecars."""
    # First check our cached status to know which servers to query
    cached_status = await cache_service.get(CACHE_KEY_UPDATE_STATUS)
    if not cached_status or not isinstance(cached_status, dict):
        return InstallStatusResponse(
            overall_status=UpdateStatus.NEVER_RUN,
            servers=[],
        )

    # If the cached status is not in_progress, return it as-is
    if cached_status.get("overall_status") != UpdateStatus.IN_PROGRESS.value:
        return InstallStatusResponse(**cached_status)

    # Status is in_progress — poll each sidecar for real-time status
    servers: list[ServerUpdateStatus] = []

    # Poll core sidecar
    core_url = os.environ.get(ENV_CORE_SIDECAR_URL, "")
    core_key = os.environ.get(ENV_CORE_SIDECAR_KEY, "")
    if core_url and core_key:
        result = await _call_sidecar(core_url, "/admin/update/status", core_key)
        if result:
            status_str = result.get("status", "in_progress")
            servers.append(ServerUpdateStatus(
                server=ServerName.CORE,
                status=UpdateStatus(status_str) if status_str in UpdateStatus.__members__.values() else UpdateStatus.IN_PROGRESS,
                started_at=result.get("started_at"),
                finished_at=result.get("finished_at"),
                duration_s=result.get("duration_s"),
                steps=result.get("steps", []),
                error=result.get("error"),
            ))
        else:
            servers.append(ServerUpdateStatus(
                server=ServerName.CORE,
                status=UpdateStatus.IN_PROGRESS,
                error="Could not reach core sidecar for status",
            ))

    # Poll upload sidecar
    upload_url = os.environ.get(ENV_UPLOAD_SIDECAR_URL, "")
    upload_key = os.environ.get(ENV_UPLOAD_SIDECAR_KEY, "")
    if upload_url and upload_key:
        result = await _call_sidecar(upload_url, "/admin/update/status", upload_key)
        if result:
            status_str = result.get("status", "in_progress")
            servers.append(ServerUpdateStatus(
                server=ServerName.UPLOAD,
                status=UpdateStatus(status_str) if status_str in UpdateStatus.__members__.values() else UpdateStatus.IN_PROGRESS,
                started_at=result.get("started_at"),
                finished_at=result.get("finished_at"),
                duration_s=result.get("duration_s"),
                steps=result.get("steps", []),
                error=result.get("error"),
            ))

    # Poll preview sidecar
    preview_url = os.environ.get(ENV_PREVIEW_SIDECAR_URL, "")
    preview_key = os.environ.get(ENV_PREVIEW_SIDECAR_KEY, "")
    if preview_url and preview_key:
        result = await _call_sidecar(preview_url, "/admin/update/status", preview_key)
        if result:
            status_str = result.get("status", "in_progress")
            servers.append(ServerUpdateStatus(
                server=ServerName.PREVIEW,
                status=UpdateStatus(status_str) if status_str in UpdateStatus.__members__.values() else UpdateStatus.IN_PROGRESS,
                started_at=result.get("started_at"),
                finished_at=result.get("finished_at"),
                duration_s=result.get("duration_s"),
                steps=result.get("steps", []),
                error=result.get("error"),
            ))

    # Determine overall status (worst-case across all servers)
    all_statuses = {s.status for s in servers}
    if UpdateStatus.FAILED in all_statuses:
        overall = UpdateStatus.FAILED
    elif UpdateStatus.IN_PROGRESS in all_statuses:
        overall = UpdateStatus.IN_PROGRESS
    elif all(s.status == UpdateStatus.SUCCESS for s in servers) and servers:
        overall = UpdateStatus.SUCCESS
    else:
        overall = UpdateStatus.IN_PROGRESS

    response = InstallStatusResponse(
        overall_status=overall,
        servers=servers,
        started_at=cached_status.get("started_at"),
    )

    # If update is no longer in progress, update the cache with final status
    if overall != UpdateStatus.IN_PROGRESS:
        await cache_service.set(
            CACHE_KEY_UPDATE_STATUS,
            response.model_dump(),
            ttl=3600,
        )

    return response


@router.get(
    "/versions",
    response_model=VersionsResponse,
    summary="Get current version info for all services",
    description=(
        "Returns the current commit SHA, branch, and build timestamp for each "
        "server/service, along with GitHub commit links. "
        "Admin only."
    ),
)
@limiter.limit("30/minute")
async def get_versions(
    request: Request,
    admin_user: User = Depends(require_admin),
) -> VersionsResponse:
    """Get version information for all services."""
    deployment_mode = _detect_deployment_mode()
    services: list[ServiceVersionInfo] = []

    # Core API (this service) — version info from sidecar or build env vars
    core_info = ServiceVersionInfo(
        name="core",
        commit=await _get_current_commit_info(),
        branch=await _get_current_branch(),
        build_timestamp=os.environ.get(ENV_BUILD_TIMESTAMP, ""),
        deployment_mode=deployment_mode,
        reachable=True,
    )
    services.append(core_info)

    # Upload server (via sidecar)
    upload_url = os.environ.get(ENV_UPLOAD_SIDECAR_URL, "")
    upload_key = os.environ.get(ENV_UPLOAD_SIDECAR_KEY, "")
    if upload_url and upload_key:
        upload_info = await _get_sidecar_version(
            ServerName.UPLOAD, upload_url, upload_key
        )
        services.append(upload_info)

    # Preview server (via sidecar)
    preview_url = os.environ.get(ENV_PREVIEW_SIDECAR_URL, "")
    preview_key = os.environ.get(ENV_PREVIEW_SIDECAR_KEY, "")
    if preview_url and preview_key:
        preview_info = await _get_sidecar_version(
            ServerName.PREVIEW, preview_url, preview_key
        )
        services.append(preview_info)

    # Web App (frontend) — version info from SvelteKit build
    # The frontend commit SHA is the same as the core if deployed from the same repo
    web_app_info = ServiceVersionInfo(
        name="web_app",
        commit=core_info.commit,  # Same repo
        branch=core_info.branch,
        build_timestamp=core_info.build_timestamp,
        deployment_mode=deployment_mode,
        reachable=True,
    )
    services.append(web_app_info)

    return VersionsResponse(
        services=services,
        deployment_mode=deployment_mode,
        github_repo_url=GITHUB_REPO_URL,
    )


@router.get(
    "/config",
    response_model=SoftwareUpdateConfig,
    summary="Get auto-update configuration",
    description="Returns the current auto-check and auto-update settings. Admin only.",
)
@limiter.limit("30/minute")
async def get_update_config(
    request: Request,
    admin_user: User = Depends(require_admin),
    cache_service: CacheService = Depends(get_cache_service),
) -> SoftwareUpdateConfig:
    """Get current auto-update configuration from cache."""
    cached = await cache_service.get(CACHE_KEY_UPDATE_CONFIG)
    if cached and isinstance(cached, dict):
        return SoftwareUpdateConfig(**cached)

    # Return defaults if no config has been saved yet
    return SoftwareUpdateConfig()


@router.put(
    "/config",
    response_model=SoftwareUpdateConfig,
    summary="Update auto-update configuration",
    description=(
        "Update auto-check and auto-update settings. "
        "Only provided fields are updated (PATCH semantics). "
        "Admin only."
    ),
)
@limiter.limit("10/minute")
async def update_config(
    request: Request,
    body: UpdateConfigRequest,
    admin_user: User = Depends(require_admin),
    cache_service: CacheService = Depends(get_cache_service),
) -> SoftwareUpdateConfig:
    """Update auto-update configuration."""
    # Get current config
    cached = await cache_service.get(CACHE_KEY_UPDATE_CONFIG)
    current = SoftwareUpdateConfig(**(cached if cached and isinstance(cached, dict) else {}))

    # Apply updates (PATCH semantics — only update provided fields)
    update_data = body.model_dump(exclude_none=True)
    for key, value in update_data.items():
        setattr(current, key, value)

    # Persist to cache (long TTL — effectively persistent until server restart)
    # In the future, this should be persisted to Directus for durability
    await cache_service.set(
        CACHE_KEY_UPDATE_CONFIG,
        current.model_dump(),
        ttl=0,  # No expiry
    )

    logger.info(
        "Software update config updated by admin: auto_check=%s, auto_update=%s, interval=%dh",
        current.auto_check_enabled,
        current.auto_update_enabled,
        current.auto_check_interval_hours,
    )

    return current
