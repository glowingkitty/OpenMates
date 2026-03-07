# backend/shared/python_schemas/software_update.py
"""
Pydantic models for the software update system.

Shared request/response schemas used by:
- Core API settings endpoints (/v1/settings/software_update/*)
- Admin sidecar version reporting
- Celery auto-check/auto-update tasks

Architecture context: See docs/architecture/software-updates.md
"""

from enum import Enum
from typing import Optional, List
from pydantic import BaseModel, Field


# =============================================================================
# Constants
# =============================================================================

GITHUB_REPO_OWNER = "glowingkitty"
GITHUB_REPO_NAME = "OpenMates"
GITHUB_REPO_URL = f"https://github.com/{GITHUB_REPO_OWNER}/{GITHUB_REPO_NAME}"

# Default interval for auto-checking updates (hours)
DEFAULT_AUTO_CHECK_INTERVAL_HOURS = 6

# Maximum auto-check interval (hours)
MAX_AUTO_CHECK_INTERVAL_HOURS = 168  # 1 week

# Minimum auto-check interval (hours)
MIN_AUTO_CHECK_INTERVAL_HOURS = 1


# =============================================================================
# Enums
# =============================================================================

class DeploymentMode(str, Enum):
    """How the server was deployed — determines the update strategy."""
    GIT = "git"          # Cloned from GitHub: git pull + docker compose build + up
    DOCKER = "docker"    # Pulled from Docker Hub: docker compose pull + up


class UpdateStatus(str, Enum):
    """Overall status of an update operation across all servers."""
    IDLE = "idle"                  # No update in progress
    IN_PROGRESS = "in_progress"   # Update is running
    SUCCESS = "success"           # Last update completed successfully
    FAILED = "failed"             # Last update failed
    NEVER_RUN = "never_run"       # No update has ever been triggered


class ServerName(str, Enum):
    """Identifier for each server in the multi-server setup."""
    CORE = "core"          # Core API server (28+ containers)
    UPLOAD = "upload"      # Upload server (separate VM)
    PREVIEW = "preview"    # Preview server (separate VM)


# =============================================================================
# Version Info Models
# =============================================================================

class CommitInfo(BaseModel):
    """Information about a specific git commit."""
    sha: str = Field(..., description="Full commit SHA hash")
    short_sha: str = Field(..., description="Short 7-char commit SHA")
    message: str = Field("", description="Commit message (first line)")
    date: str = Field("", description="Commit date (ISO 8601)")
    url: str = Field("", description="GitHub URL to view this commit")


class ServiceVersionInfo(BaseModel):
    """Version info for a single service/server."""
    name: str = Field(..., description="Service name (e.g., 'core', 'upload', 'preview', 'web_app')")
    commit: Optional[CommitInfo] = Field(None, description="Current commit info")
    branch: str = Field("", description="Current git branch")
    build_timestamp: str = Field("", description="When this build was created (ISO 8601)")
    deployment_mode: DeploymentMode = Field(
        DeploymentMode.GIT, description="How this service was deployed"
    )
    reachable: bool = Field(True, description="Whether this server could be contacted")
    error: Optional[str] = Field(None, description="Error message if server unreachable")


# =============================================================================
# Check for Updates Models
# =============================================================================

class UpdateCheckResult(BaseModel):
    """Result of checking whether a software update is available."""
    update_available: bool = Field(..., description="Whether a newer version is available")
    deployment_mode: DeploymentMode = Field(..., description="Detected deployment mode")
    current_version: Optional[CommitInfo] = Field(
        None, description="Currently running version"
    )
    latest_version: Optional[CommitInfo] = Field(
        None, description="Latest available version (from GitHub or Docker Hub)"
    )
    commits_behind: int = Field(
        0, description="Number of commits behind latest (git mode only)"
    )
    checked_at: str = Field(..., description="When this check was performed (ISO 8601)")
    error: Optional[str] = Field(
        None, description="Error message if check failed (e.g., GitHub API rate limit)"
    )


# =============================================================================
# Install / Update Models
# =============================================================================

class InstallRequest(BaseModel):
    """Request to start a software update installation."""
    clear_cache: bool = Field(
        True, description="Whether to clear the cache volume during update"
    )


class ServerUpdateStatus(BaseModel):
    """Update status for a single server."""
    server: ServerName = Field(..., description="Which server this status is for")
    status: UpdateStatus = Field(..., description="Current update status")
    started_at: Optional[str] = Field(None, description="When update started (ISO 8601)")
    finished_at: Optional[str] = Field(None, description="When update finished (ISO 8601)")
    duration_s: Optional[float] = Field(None, description="Duration in seconds")
    steps: List[dict] = Field(
        default_factory=list,
        description="Per-step details (name, success, duration_s, output)"
    )
    error: Optional[str] = Field(None, description="Error message if failed")


class InstallStatusResponse(BaseModel):
    """Aggregated update status across all servers."""
    overall_status: UpdateStatus = Field(
        ..., description="Overall status (worst-case across all servers)"
    )
    servers: List[ServerUpdateStatus] = Field(
        default_factory=list, description="Per-server update status"
    )
    started_at: Optional[str] = Field(None, description="When the update was initiated")


# =============================================================================
# Version Info Response
# =============================================================================

class VersionsResponse(BaseModel):
    """Current version information for all services."""
    services: List[ServiceVersionInfo] = Field(
        default_factory=list, description="Version info for each service"
    )
    deployment_mode: DeploymentMode = Field(
        ..., description="Detected deployment mode for this installation"
    )
    github_repo_url: str = Field(
        GITHUB_REPO_URL, description="GitHub repository URL"
    )


# =============================================================================
# Auto-Update Configuration Models
# =============================================================================

class SoftwareUpdateConfig(BaseModel):
    """Configuration for automatic update checking and installation."""
    auto_check_enabled: bool = Field(
        True, description="Whether to periodically check for updates"
    )
    auto_check_interval_hours: int = Field(
        DEFAULT_AUTO_CHECK_INTERVAL_HOURS,
        ge=MIN_AUTO_CHECK_INTERVAL_HOURS,
        le=MAX_AUTO_CHECK_INTERVAL_HOURS,
        description="How often to check for updates (hours)"
    )
    auto_update_enabled: bool = Field(
        False, description="Whether to automatically install updates when found"
    )
    clear_cache_on_update: bool = Field(
        True, description="Whether to clear cache volume during updates"
    )
    last_check_at: Optional[str] = Field(
        None, description="When the last auto-check was performed (ISO 8601)"
    )
    last_update_at: Optional[str] = Field(
        None, description="When the last update was installed (ISO 8601)"
    )


class UpdateConfigRequest(BaseModel):
    """Request to update auto-update configuration. All fields optional — only
    provided fields are updated (PATCH semantics)."""
    auto_check_enabled: Optional[bool] = Field(
        None, description="Whether to periodically check for updates"
    )
    auto_check_interval_hours: Optional[int] = Field(
        None,
        ge=MIN_AUTO_CHECK_INTERVAL_HOURS,
        le=MAX_AUTO_CHECK_INTERVAL_HOURS,
        description="How often to check for updates (hours)"
    )
    auto_update_enabled: Optional[bool] = Field(
        None, description="Whether to automatically install updates when found"
    )
    clear_cache_on_update: Optional[bool] = Field(
        None, description="Whether to clear cache volume during updates"
    )
