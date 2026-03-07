# backend/core/api/app/tasks/software_update_tasks.py
"""
Celery tasks for periodic software update checking and auto-installation.

Provides a Beat-scheduled task that:
- Checks GitHub for new commits (respecting the configured interval)
- Creates an admin notification if an update is found
- Optionally triggers auto-installation if enabled

Architecture context: See docs/architecture/software-updates.md
Tests: (none yet)
"""

import logging
import asyncio
import os
from datetime import datetime, timezone

import httpx

from backend.core.api.app.tasks.celery_config import app
from backend.core.api.app.tasks.base_task import BaseServiceTask
from backend.shared.python_schemas.software_update import (
    GITHUB_REPO_OWNER,
    GITHUB_REPO_NAME,
    GITHUB_REPO_URL,
    DEFAULT_AUTO_CHECK_INTERVAL_HOURS,
)

logger = logging.getLogger(__name__)

# =============================================================================
# Constants
# =============================================================================

# Cache keys (must match settings_software_update.py)
CACHE_KEY_UPDATE_CHECK = "software_update:last_check"
CACHE_KEY_UPDATE_CONFIG = "software_update:config"
CACHE_KEY_UPDATE_STATUS = "software_update:install_status"

# Cache TTL for update check results (seconds)
UPDATE_CHECK_CACHE_TTL = 300  # 5 minutes

# GitHub API configuration
GITHUB_API_BASE = "https://api.github.com"
GITHUB_API_TIMEOUT = 15  # seconds

# Sidecar configuration
SIDECAR_REQUEST_TIMEOUT = 30  # seconds
ENV_CORE_SIDECAR_URL = "CORE_SIDECAR_URL"
ENV_CORE_SIDECAR_KEY = "SECRET__CORE_SERVER__ADMIN_LOG_API_KEY"
ENV_UPLOAD_SIDECAR_URL = "UPLOAD_SIDECAR_URL"
ENV_UPLOAD_SIDECAR_KEY = "SECRET__UPLOAD_SERVER__ADMIN_LOG_API_KEY"
ENV_PREVIEW_SIDECAR_URL = "PREVIEW_SIDECAR_URL"
ENV_PREVIEW_SIDECAR_KEY = "SECRET__PREVIEW_SERVER__ADMIN_LOG_API_KEY"

# Notification keys
NOTIFICATION_COLLECTION = "notifications"


# =============================================================================
# Celery Task
# =============================================================================

@app.task(
    name="software_update.auto_check",
    base=BaseServiceTask,
    bind=True,
)
def auto_check_for_updates(self):
    """
    Periodic task to check GitHub for new commits and optionally auto-install.

    Behavior:
    1. Read auto-update config from cache
    2. If auto_check_enabled is False, skip
    3. Check if enough time has passed since the last check (respects interval)
    4. Fetch latest commit from GitHub and compare with current
    5. If update available: create admin notification
    6. If auto_update_enabled: trigger installation via sidecars
    """
    return asyncio.run(_run_auto_check(self))


async def _run_auto_check(task: BaseServiceTask) -> dict:
    """Async implementation of the auto-check task."""
    log_prefix = "SoftwareUpdateAutoCheck:"
    logger.info(f"{log_prefix} Starting periodic update check")

    try:
        await task.initialize_services()

        # 1. Read config from cache
        config = await task.cache_service.get(CACHE_KEY_UPDATE_CONFIG)
        if not config or not isinstance(config, dict):
            # Use defaults if no config saved
            config = {
                "auto_check_enabled": True,
                "auto_check_interval_hours": DEFAULT_AUTO_CHECK_INTERVAL_HOURS,
                "auto_update_enabled": False,
                "clear_cache_on_update": True,
            }

        if not config.get("auto_check_enabled", True):
            logger.info(f"{log_prefix} Auto-check is disabled, skipping")
            return {"success": True, "skipped": True, "reason": "auto_check_disabled"}

        # 2. Check if enough time has passed since last check
        last_check_at = config.get("last_check_at")
        interval_hours = config.get(
            "auto_check_interval_hours", DEFAULT_AUTO_CHECK_INTERVAL_HOURS
        )

        if last_check_at:
            try:
                last_check_dt = datetime.fromisoformat(last_check_at)
                now = datetime.now(timezone.utc)
                hours_since_check = (now - last_check_dt).total_seconds() / 3600

                if hours_since_check < interval_hours:
                    logger.info(
                        f"{log_prefix} Only {hours_since_check:.1f}h since last check "
                        f"(interval={interval_hours}h), skipping"
                    )
                    return {
                        "success": True,
                        "skipped": True,
                        "reason": "interval_not_reached",
                        "hours_since_check": round(hours_since_check, 1),
                        "interval_hours": interval_hours,
                    }
            except (ValueError, TypeError) as e:
                logger.warning(
                    f"{log_prefix} Could not parse last_check_at '{last_check_at}': {e}"
                )

        # 3. Get current commit info
        current_sha = _get_current_commit_sha()
        current_branch = _get_current_branch()

        if not current_sha:
            logger.warning(f"{log_prefix} Could not determine current commit SHA")
            return {"success": False, "error": "unknown_current_version"}

        # 4. Fetch latest commit from GitHub
        latest_commit = await _fetch_latest_github_commit(current_branch)
        if not latest_commit:
            logger.warning(f"{log_prefix} Could not fetch latest commit from GitHub")
            return {"success": False, "error": "github_api_failed"}

        latest_sha = latest_commit.get("sha", "")
        now_iso = datetime.now(timezone.utc).isoformat()

        # 5. Update config with last check timestamp
        config["last_check_at"] = now_iso
        await task.cache_service.set(CACHE_KEY_UPDATE_CONFIG, config, ttl=0)

        # 6. Compare versions
        if current_sha == latest_sha:
            logger.info(f"{log_prefix} Already up to date (commit {current_sha[:7]})")

            # Update cached check result
            await _cache_check_result(
                task.cache_service,
                update_available=False,
                current_sha=current_sha,
                latest_commit=latest_commit,
                branch=current_branch,
                checked_at=now_iso,
            )

            return {"success": True, "update_available": False}

        # Update is available
        commits_behind = await _count_commits_behind(
            current_sha, latest_sha, current_branch
        )
        latest_message = latest_commit.get("message", "")
        latest_short_sha = latest_sha[:7]

        logger.info(
            f"{log_prefix} Update available: {current_sha[:7]} → {latest_short_sha} "
            f"({commits_behind} commits behind). Latest: {latest_message[:80]}"
        )

        # Cache the check result for the API endpoint to read
        await _cache_check_result(
            task.cache_service,
            update_available=True,
            current_sha=current_sha,
            latest_commit=latest_commit,
            branch=current_branch,
            checked_at=now_iso,
            commits_behind=commits_behind,
        )

        # 7. Create admin notification about available update
        await _create_update_notification(
            task, latest_short_sha, commits_behind, latest_message
        )

        # 8. Auto-install if enabled
        auto_update_enabled = config.get("auto_update_enabled", False)
        if auto_update_enabled:
            logger.info(
                f"{log_prefix} Auto-update is enabled, triggering installation"
            )
            install_result = await _trigger_auto_install(task)
            return {
                "success": True,
                "update_available": True,
                "auto_install_triggered": True,
                "install_result": install_result,
            }

        return {
            "success": True,
            "update_available": True,
            "commits_behind": commits_behind,
            "latest_sha": latest_short_sha,
        }

    except Exception as e:
        logger.error(f"{log_prefix} Auto-check failed: {e}", exc_info=True)
        return {"success": False, "error": str(e)}
    finally:
        await task.cleanup_services()


# =============================================================================
# Helper Functions
# =============================================================================

def _get_current_commit_sha() -> str:
    """Get current commit SHA from env vars or git command."""
    import subprocess

    sha = os.environ.get("BUILD_COMMIT_SHA", "")
    if sha:
        return sha

    try:
        result = subprocess.run(
            ["git", "rev-parse", "HEAD"],
            capture_output=True, text=True, timeout=5,
            cwd="/app"
        )
        return result.stdout.strip()
    except (subprocess.TimeoutExpired, FileNotFoundError, Exception) as e:
        logger.warning("Could not get current commit SHA via git: %s", e)
        return ""


def _get_current_branch() -> str:
    """Get current git branch name."""
    import subprocess

    branch = os.environ.get("BUILD_BRANCH", "")
    if branch:
        return branch

    try:
        result = subprocess.run(
            ["git", "rev-parse", "--abbrev-ref", "HEAD"],
            capture_output=True, text=True, timeout=5,
            cwd="/app"
        )
        return result.stdout.strip() or "dev"
    except (subprocess.TimeoutExpired, FileNotFoundError, Exception):
        return "dev"


async def _fetch_latest_github_commit(branch: str) -> dict | None:
    """Fetch the latest commit data from GitHub API."""
    github_token = os.environ.get("GITHUB_TOKEN", "")
    headers = {
        "Accept": "application/vnd.github.v3+json",
        "User-Agent": "OpenMates-Updater/1.0",
    }
    if github_token:
        headers["Authorization"] = f"token {github_token}"

    url = (
        f"{GITHUB_API_BASE}/repos/{GITHUB_REPO_OWNER}/{GITHUB_REPO_NAME}"
        f"/commits/{branch}"
    )

    try:
        async with httpx.AsyncClient(timeout=GITHUB_API_TIMEOUT) as client:
            response = await client.get(url, headers=headers)

            if response.status_code == 403:
                logger.warning(
                    "GitHub API rate limit hit during auto-check. "
                    "Add GITHUB_TOKEN env var for higher limits."
                )
                return None

            if response.status_code != 200:
                logger.error(
                    "GitHub API returned %d during auto-check: %s",
                    response.status_code, response.text[:200]
                )
                return None

            data = response.json()
            sha = data.get("sha", "")
            commit_data = data.get("commit", {})

            return {
                "sha": sha,
                "short_sha": sha[:7],
                "message": commit_data.get("message", "").split("\n")[0],
                "date": commit_data.get("author", {}).get("date", ""),
                "url": data.get(
                    "html_url", f"{GITHUB_REPO_URL}/commit/{sha}"
                ),
            }
    except httpx.TimeoutException:
        logger.error("GitHub API request timed out during auto-check")
        return None
    except Exception as e:
        logger.error("Failed to fetch latest commit during auto-check: %s", e)
        return None


async def _count_commits_behind(
    current_sha: str, latest_sha: str, branch: str
) -> int:
    """Count how many commits the current version is behind."""
    if not current_sha or not latest_sha or current_sha == latest_sha:
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
                return response.json().get("ahead_by", 0)
    except Exception as e:
        logger.warning("Could not count commits behind during auto-check: %s", e)

    return 0


async def _cache_check_result(
    cache_service,
    *,
    update_available: bool,
    current_sha: str,
    latest_commit: dict,
    branch: str,
    checked_at: str,
    commits_behind: int = 0,
) -> None:
    """Cache the update check result so the API /check endpoint can return it."""
    result = {
        "update_available": update_available,
        "deployment_mode": "git",
        "current_version": {
            "sha": current_sha,
            "short_sha": current_sha[:7],
            "message": "",
            "date": "",
            "url": f"{GITHUB_REPO_URL}/commit/{current_sha}",
        },
        "latest_version": latest_commit,
        "commits_behind": commits_behind,
        "checked_at": checked_at,
    }
    await cache_service.set(CACHE_KEY_UPDATE_CHECK, result, ttl=UPDATE_CHECK_CACHE_TTL)


async def _create_update_notification(
    task: BaseServiceTask,
    latest_short_sha: str,
    commits_behind: int,
    latest_message: str,
) -> None:
    """
    Create an admin notification about an available update.

    Uses the existing notification infrastructure to alert admins.
    The notification is stored in Directus for persistence.
    """
    try:
        # Get all admin user IDs from Directus
        admin_users = await task.directus_service.admin.get_admin_users()
        if not admin_users:
            logger.info("No admin users found to notify about update")
            return

        for admin_user in admin_users:
            admin_user_id = admin_user.get("id")
            if not admin_user_id:
                continue

            # Store notification in the cache for push delivery
            # The notification system will pick it up and deliver it
            notification_data = {
                "type": "software_update",
                "user_id": admin_user_id,
                "title": "Software update available",
                "message": (
                    f"OpenMates {latest_short_sha} is available "
                    f"({commits_behind} commit{'s' if commits_behind != 1 else ''} behind)"
                ),
                "message_secondary": latest_message[:100] if latest_message else "",
                "created_at": datetime.now(timezone.utc).isoformat(),
            }

            # Store in cache with user-specific key for the notification system
            notification_key = f"notification:software_update:{admin_user_id}"
            await task.cache_service.set(
                notification_key, notification_data, ttl=86400  # 24 hours
            )

        logger.info(
            "Created software update notification for %d admin user(s)",
            len(admin_users),
        )

    except Exception as e:
        logger.error("Failed to create update notification: %s", e, exc_info=True)


async def _trigger_auto_install(task: BaseServiceTask) -> dict:
    """
    Trigger auto-installation by calling all server sidecars.

    Mirrors the logic of the /install API endpoint but runs from a Celery task.
    """
    now = datetime.now(timezone.utc).isoformat()
    servers_triggered = []
    errors = []

    # Prepare server configs
    servers = [
        (
            "core",
            os.environ.get(ENV_CORE_SIDECAR_URL, ""),
            os.environ.get(ENV_CORE_SIDECAR_KEY, ""),
        ),
        (
            "upload",
            os.environ.get(ENV_UPLOAD_SIDECAR_URL, ""),
            os.environ.get(ENV_UPLOAD_SIDECAR_KEY, ""),
        ),
        (
            "preview",
            os.environ.get(ENV_PREVIEW_SIDECAR_URL, ""),
            os.environ.get(ENV_PREVIEW_SIDECAR_KEY, ""),
        ),
    ]

    for name, sidecar_url, sidecar_key in servers:
        if not sidecar_url or not sidecar_key:
            continue

        try:
            url = f"{sidecar_url.rstrip('/')}/admin/update"
            headers = {"X-Admin-Log-Key": sidecar_key}

            async with httpx.AsyncClient(timeout=SIDECAR_REQUEST_TIMEOUT) as client:
                response = await client.post(url, headers=headers, json={})
                if response.status_code in (200, 202):
                    servers_triggered.append(name)
                    logger.info(
                        "Auto-update triggered on %s server (status %d)",
                        name, response.status_code,
                    )
                else:
                    error_msg = (
                        f"{name} sidecar returned {response.status_code}: "
                        f"{response.text[:100]}"
                    )
                    errors.append(error_msg)
                    logger.warning("Auto-update trigger failed: %s", error_msg)

        except httpx.ConnectError:
            errors.append(f"Could not connect to {name} sidecar")
            logger.warning("Could not connect to %s sidecar for auto-update", name)
        except httpx.TimeoutException:
            errors.append(f"{name} sidecar timed out")
            logger.warning("%s sidecar timed out during auto-update trigger", name)
        except Exception as e:
            errors.append(f"{name}: {str(e)}")
            logger.error(
                "Auto-update trigger error for %s: %s", name, e, exc_info=True
            )

    # Update the install status in cache
    if servers_triggered:
        install_status = {
            "overall_status": "in_progress",
            "servers": [
                {"server": s, "status": "in_progress", "started_at": now}
                for s in servers_triggered
            ],
            "started_at": now,
        }
        await task.cache_service.set(
            CACHE_KEY_UPDATE_STATUS, install_status, ttl=3600
        )

        # Update config with last_update_at
        config = await task.cache_service.get(CACHE_KEY_UPDATE_CONFIG)
        if config and isinstance(config, dict):
            config["last_update_at"] = now
            await task.cache_service.set(CACHE_KEY_UPDATE_CONFIG, config, ttl=0)

    return {
        "servers_triggered": servers_triggered,
        "errors": errors if errors else None,
    }
