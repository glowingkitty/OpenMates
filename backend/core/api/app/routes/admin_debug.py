# backend/core/api/app/routes/admin_debug.py
"""
REST API endpoints for admin debugging functionality.

These endpoints allow admins to remotely debug production issues without SSH access:
- Query Docker Compose logs via Loki
- Manage issue reports (list, view, delete)
- Inspect chats, users, embeds, demo chats
- Inspect recent AI processing requests

SECURITY:
- Requires API key authentication with admin role verification
- Excluded from public API documentation (include_in_schema=False)
- Rate limited to 30 requests/minute
- Only allows querying predefined list of services for logs (excludes vault, etc.)

API DOMAINS:
- Production: api.openmates.org
- Development: api.dev.openmates.org
"""

import hashlib
import logging
import os
from datetime import datetime, timedelta, timezone
from typing import Any, Dict, List, Optional

import yaml
from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel

from backend.core.api.app.models.user import User
from backend.core.api.app.routes.auth_routes.auth_dependencies import (
    get_cache_service,
    get_directus_service,
    get_encryption_service,
)
from backend.core.api.app.services.cache import CacheService
from backend.core.api.app.services.directus import DirectusService
from backend.core.api.app.services.limiter import limiter
from backend.core.api.app.services.loki_log_collector import loki_log_collector
from backend.core.api.app.utils.api_key_auth import (
    ApiKeyNotFoundError,
    DeviceNotApprovedError,
    get_api_key_auth_service,
)
from backend.core.api.app.utils.encryption import EncryptionService

logger = logging.getLogger(__name__)


def censor_email(email: Optional[str]) -> Optional[str]:
    """
    Censor an email address to protect user privacy.

    Shows only the first 2 characters of the local part and the full domain.
    Example: "john.doe@example.com" -> "jo***@example.com"

    Args:
        email: Full email address string, or None

    Returns:
        Censored email string, or None if input is None
    """
    if not email or '@' not in email:
        return email
    local, domain = email.rsplit('@', 1)
    if len(local) <= 2:
        censored_local = local[0] + '***' if local else '***'
    else:
        censored_local = local[:2] + '***'
    return f"{censored_local}@{domain}"


router = APIRouter(
    prefix="/v1/admin/debug",
    tags=["Admin Debug"]
)


# ============================================================================
# ALLOWED SERVICES FOR LOG QUERIES
# ============================================================================
# Security: Only allow querying specific services to prevent access to sensitive logs
# Excluded: vault, vault-setup (secrets), grafana, prometheus, loki, promtail, cadvisor (monitoring infra)

ALLOWED_LOG_SERVICES = [
    # Core services
    "api",
    "cms",
    "cms-database",
    "task-worker",
    "task-scheduler",
    # App services (apps)
    "app-ai",
    "app-web",
    "app-videos",
    "app-news",
    "app-maps",
    "app-code",
    "app-travel",
    "app-images",
    # App workers
    "app-ai-worker",
    "app-web-worker",
    "app-images-worker",
    # Infrastructure (cache only - safe to query)
    "cache",
]


# ============================================================================
# AUTHENTICATION DEPENDENCY
# ============================================================================

def get_s3_service(request: Request):
    """Get the S3 service instance from app state."""
    return request.app.state.s3_service


async def require_admin_api_key(
    request: Request,
    directus_service: DirectusService = Depends(get_directus_service),
) -> User:
    """
    Validates API key from Authorization header and verifies admin privileges.
    
    This dependency:
    1. Extracts API key from "Authorization: Bearer <key>" header
    2. Validates the API key and gets the associated user
    3. Verifies the user has admin privileges
    
    Returns:
        User object if authenticated as admin
        
    Raises:
        HTTPException(401): If API key is missing or invalid
        HTTPException(403): If user is not an admin
    """
    # Extract API key from Authorization header
    auth_header = request.headers.get("Authorization")
    if not auth_header or not auth_header.startswith("Bearer "):
        raise HTTPException(
            status_code=401, 
            detail="Missing or invalid Authorization header. Expected: Bearer <api_key>"
        )
    
    api_key = auth_header[7:]  # Remove "Bearer " prefix
    
    if not api_key:
        raise HTTPException(status_code=401, detail="API key is empty")
    
    try:
        # Authenticate using API key auth service
        api_key_auth_service = get_api_key_auth_service(request)
        user_info = await api_key_auth_service.authenticate_api_key(api_key, request=request)
        
        user_id = user_info.get("user_id")
        if not user_id:
            raise HTTPException(status_code=401, detail="Invalid API key")
        
        # Verify admin privileges
        is_admin = await directus_service.admin.is_user_admin(user_id)
        if not is_admin:
            logger.warning(f"Non-admin user {user_id} attempted to access admin debug endpoint")
            raise HTTPException(status_code=403, detail="Admin privileges required")
        
        # Fetch user profile to create User object
        success, user_data, profile_message = await directus_service.get_user_profile(user_id)
        if not success or not user_data:
            raise HTTPException(status_code=500, detail=f"Could not fetch user data: {profile_message}")
        
        logger.info(f"Admin API key authenticated for user {user_id}")
        
        return User(
            id=user_id,
            username=user_data.get("username", ""),
            is_admin=True,
            credits=user_data.get("credits", 0),
            vault_key_id=user_data.get("vault_key_id", ""),
            language=user_data.get("language", "en"),
        )
        
    except HTTPException:
        raise
    except DeviceNotApprovedError as e:
        logger.warning(f"Admin API key device not approved: {e}")
        raise HTTPException(status_code=403, detail=str(e))
    except ApiKeyNotFoundError as e:
        logger.warning(f"Admin API key not found: {e}")
        raise HTTPException(status_code=401, detail=str(e))
    except Exception as e:
        logger.error(f"Admin API key authentication error: {e}", exc_info=True)
        raise HTTPException(status_code=401, detail="API key authentication failed")


# ============================================================================
# RESPONSE MODELS
# ============================================================================

class LogsResponse(BaseModel):
    """Response model for log queries."""
    logs: str
    services_queried: List[str]
    lines_per_service: int
    time_window_minutes: int
    search_pattern: Optional[str]
    timestamp: str


class IssueListItem(BaseModel):
    """Summary item for issue list."""
    id: str
    title: str
    description: Optional[str]
    contact_email: Optional[str]
    chat_or_embed_url: Optional[str]
    timestamp: str
    created_at: str
    processed: bool


class IssuesListResponse(BaseModel):
    """Response model for issue list."""
    issues: List[IssueListItem]
    total: int
    limit: int
    offset: int


class IssueDetailResponse(BaseModel):
    """Response model for issue details."""
    id: str
    title: str
    description: Optional[str]
    contact_email: Optional[str]
    chat_or_embed_url: Optional[str]
    timestamp: str
    estimated_location: Optional[str]
    device_info: Optional[str]
    created_at: str
    updated_at: str
    processed: bool
    full_report: Optional[Dict[str, Any]] = None


class DeleteIssueResponse(BaseModel):
    """Response model for issue deletion."""
    success: bool
    message: str
    deleted_from_s3: bool


class InspectResponse(BaseModel):
    """Generic response model for inspection endpoints."""
    success: bool
    data: Dict[str, Any]
    generated_at: str


# ============================================================================
# LOGS ENDPOINT
# ============================================================================

@router.get("/logs", response_model=LogsResponse)
@limiter.limit("30/minute")
async def get_compose_logs(
    request: Request,
    services: Optional[str] = None,
    lines: int = 100,
    since_minutes: int = 60,
    search: Optional[str] = None,
    admin_user: User = Depends(require_admin_api_key),
) -> LogsResponse:
    """
    Query Docker Compose logs from Loki.
    
    This endpoint allows querying logs from predefined services via Loki.
    Useful for debugging production issues without SSH access.
    
    Args:
        services: Comma-separated list of services to query (default: all allowed)
        lines: Number of lines per container (default: 100, max: 500)
        since_minutes: Time window in minutes (default: 60, max: 1440 = 24h)
        search: Optional regex pattern to filter log lines
        
    Returns:
        LogsResponse with formatted log output
        
    Security:
        - Requires admin API key
        - Only allows querying predefined services (excludes vault, monitoring infra)
    """
    logger.info(f"Admin {admin_user.id} requesting logs (services={services}, lines={lines}, since={since_minutes}m)")
    
    # Validate and parse services
    requested_services: List[str] = []
    if services:
        requested_services = [s.strip() for s in services.split(",") if s.strip()]
        
        # Validate each requested service is in the allowed list
        invalid_services = [s for s in requested_services if s not in ALLOWED_LOG_SERVICES]
        if invalid_services:
            raise HTTPException(
                status_code=400,
                detail=f"Invalid services: {invalid_services}. Allowed services: {ALLOWED_LOG_SERVICES}"
            )
    else:
        # Default to all allowed services
        requested_services = ALLOWED_LOG_SERVICES.copy()
    
    # Validate limits
    lines = min(max(lines, 1), 500)  # Clamp between 1 and 500
    since_minutes = min(max(since_minutes, 1), 1440)  # Clamp between 1 and 1440 (24h)
    
    # Calculate start time
    start_time = datetime.now(timezone.utc) - timedelta(minutes=since_minutes)
    
    try:
        # Query Loki for logs
        logs = await loki_log_collector.get_compose_logs(
            lines=lines,
            services=requested_services,
            exclude_containers=None,  # We already filtered to allowed services
            start_time=start_time,
        )
        
        if not logs:
            logs = f"No logs found for services: {requested_services}"
        
        # Apply search pattern if provided
        if search and logs:
            import re
            try:
                pattern = re.compile(search, re.IGNORECASE)
                filtered_lines = []
                for line in logs.split("\n"):
                    if pattern.search(line) or line.startswith("===") or line.startswith("---"):
                        filtered_lines.append(line)
                logs = "\n".join(filtered_lines)
            except re.error as e:
                raise HTTPException(status_code=400, detail=f"Invalid regex pattern: {e}")
        
        return LogsResponse(
            logs=logs,
            services_queried=requested_services,
            lines_per_service=lines,
            time_window_minutes=since_minutes,
            search_pattern=search,
            timestamp=datetime.now(timezone.utc).isoformat(),
        )
        
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error querying logs: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=f"Failed to query logs: {str(e)}")


# ============================================================================
# ISSUE REPORTS ENDPOINTS
# ============================================================================

@router.get("/issues", response_model=IssuesListResponse)
@limiter.limit("30/minute")
async def list_issues(
    request: Request,
    search: Optional[str] = None,
    limit: int = 50,
    offset: int = 0,
    include_processed: bool = False,
    admin_user: User = Depends(require_admin_api_key),
    directus_service: DirectusService = Depends(get_directus_service),
    encryption_service: EncryptionService = Depends(get_encryption_service),
) -> IssuesListResponse:
    """
    List issue reports with optional filtering.
    
    Args:
        search: Search text in title/description
        limit: Max results (default: 50, max: 200)
        offset: Pagination offset
        include_processed: Include already processed issues (default: False)
        
    Returns:
        List of issue summaries with decrypted contact info
    """
    logger.info(f"Admin {admin_user.id} listing issues (search={search}, limit={limit}, offset={offset})")
    
    # Validate limits
    limit = min(max(limit, 1), 200)
    offset = max(offset, 0)
    
    try:
        # Build query parameters
        params: Dict[str, Any] = {
            "limit": limit,
            "offset": offset,
            "sort": "-created_at",
        }
        
        # Build filter
        filters: Dict[str, Any] = {}
        
        if search:
            # Search in title OR description (case-insensitive)
            filters["_or"] = [
                {"title": {"_icontains": search}},
                {"description": {"_icontains": search}},
            ]
        
        if not include_processed:
            # Exclude processed issues (show only unprocessed)
            # Note: processed might be null (not set) for old issues, so we handle both
            filters["_or"] = filters.get("_or", [])
            if "_or" in filters and filters["_or"]:
                # Wrap existing OR with AND
                params["filter"] = {
                    "_and": [
                        {"_or": filters["_or"]},
                        {"_or": [
                            {"processed": {"_eq": False}},
                            {"processed": {"_null": True}},
                        ]},
                    ]
                }
            else:
                params["filter"] = {
                    "_or": [
                        {"processed": {"_eq": False}},
                        {"processed": {"_null": True}},
                    ]
                }
        elif "_or" in filters and filters["_or"]:
            params["filter"] = {"_or": filters["_or"]}
        
        # Fetch issues
        issues = await directus_service.get_items("issues", params, no_cache=True, admin_required=True)
        
        # Get total count for pagination
        count_params = params.copy()
        count_params["limit"] = 1
        count_params["meta"] = "filter_count"
        
        # Decrypt and format results
        result_issues: List[IssueListItem] = []
        for issue in issues or []:
            # Decrypt contact email
            decrypted_email = None
            if issue.get("encrypted_contact_email"):
                try:
                    decrypted_email = await encryption_service.decrypt_issue_report_email(
                        issue["encrypted_contact_email"]
                    )
                except Exception as e:
                    logger.warning(f"Failed to decrypt email for issue {issue.get('id')}: {e}")
            
            # Decrypt URL
            decrypted_url = None
            if issue.get("encrypted_chat_or_embed_url"):
                try:
                    decrypted_url = await encryption_service.decrypt_issue_report_data(
                        issue["encrypted_chat_or_embed_url"]
                    )
                except Exception as e:
                    logger.warning(f"Failed to decrypt URL for issue {issue.get('id')}: {e}")
            
            result_issues.append(IssueListItem(
                id=issue["id"],
                title=issue.get("title", ""),
                description=issue.get("description"),
                contact_email=censor_email(decrypted_email),
                chat_or_embed_url=decrypted_url,
                timestamp=issue.get("timestamp", ""),
                created_at=issue.get("created_at", ""),
                processed=issue.get("processed", False) or False,
            ))
        
        return IssuesListResponse(
            issues=result_issues,
            total=len(result_issues),  # Approximate, actual count would require separate query
            limit=limit,
            offset=offset,
        )
        
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error listing issues: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=f"Failed to list issues: {str(e)}")


@router.get("/issues/{issue_id}", response_model=IssueDetailResponse)
@limiter.limit("30/minute")
async def get_issue_detail(
    request: Request,
    issue_id: str,
    include_logs: bool = True,
    admin_user: User = Depends(require_admin_api_key),
    directus_service: DirectusService = Depends(get_directus_service),
    encryption_service: EncryptionService = Depends(get_encryption_service),
) -> IssueDetailResponse:
    """
    Get detailed information about a specific issue.
    
    Args:
        issue_id: UUID of the issue
        include_logs: Include full report from S3 (default: True)
        
    Returns:
        Full issue details with decrypted fields and optional logs
    """
    logger.info(f"Admin {admin_user.id} fetching issue detail: {issue_id}")
    
    try:
        # Fetch issue from Directus
        params = {
            "filter[id][_eq]": issue_id,
            "limit": 1,
        }
        issues = await directus_service.get_items("issues", params, no_cache=True, admin_required=True)
        
        if not issues:
            raise HTTPException(status_code=404, detail="Issue not found")
        
        issue = issues[0]
        
        # Decrypt all fields
        decrypted_email = None
        if issue.get("encrypted_contact_email"):
            try:
                decrypted_email = await encryption_service.decrypt_issue_report_email(
                    issue["encrypted_contact_email"]
                )
            except Exception as e:
                logger.warning(f"Failed to decrypt email: {e}")
        
        decrypted_url = None
        if issue.get("encrypted_chat_or_embed_url"):
            try:
                decrypted_url = await encryption_service.decrypt_issue_report_data(
                    issue["encrypted_chat_or_embed_url"]
                )
            except Exception as e:
                logger.warning(f"Failed to decrypt URL: {e}")
        
        decrypted_location = None
        if issue.get("encrypted_estimated_location"):
            try:
                decrypted_location = await encryption_service.decrypt_issue_report_data(
                    issue["encrypted_estimated_location"]
                )
            except Exception as e:
                logger.warning(f"Failed to decrypt location: {e}")
        
        decrypted_device_info = None
        if issue.get("encrypted_device_info"):
            try:
                decrypted_device_info = await encryption_service.decrypt_issue_report_data(
                    issue["encrypted_device_info"]
                )
            except Exception as e:
                logger.warning(f"Failed to decrypt device info: {e}")
        
        # Fetch full report from S3 if requested
        full_report = None
        if include_logs and issue.get("encrypted_issue_report_yaml_s3_key"):
            try:
                s3_service = get_s3_service(request)
                
                # Decrypt S3 key
                s3_object_key = await encryption_service.decrypt_issue_report_data(
                    issue["encrypted_issue_report_yaml_s3_key"]
                )
                
                if s3_object_key:
                    from backend.core.api.app.services.s3.config import get_bucket_name
                    bucket_name = get_bucket_name('issue_logs', os.getenv('SERVER_ENVIRONMENT', 'development'))
                    
                    # Download encrypted YAML
                    encrypted_yaml_bytes = await s3_service.get_file(
                        bucket_name=bucket_name,
                        object_key=s3_object_key
                    )
                    
                    if encrypted_yaml_bytes:
                        encrypted_yaml_str = encrypted_yaml_bytes.decode('utf-8')
                        decrypted_yaml = await encryption_service.decrypt_issue_report_data(
                            encrypted_yaml_str
                        )
                        
                        # Parse YAML
                        full_report = yaml.safe_load(decrypted_yaml)
                        # Censor any email addresses in the S3 report
                        if isinstance(full_report, dict):
                            report_inner = full_report.get('issue_report', full_report)
                            report_meta = report_inner.get('metadata', {}) if isinstance(report_inner, dict) else {}
                            if report_meta.get('contact_email'):
                                report_meta['contact_email'] = censor_email(report_meta['contact_email'])
                        logger.info(f"Successfully fetched issue report from S3 for issue {issue_id}")
            except Exception as e:
                logger.warning(f"Failed to fetch S3 report for issue {issue_id}: {e}", exc_info=True)
        
        return IssueDetailResponse(
            id=issue["id"],
            title=issue.get("title", ""),
            description=issue.get("description"),
            contact_email=censor_email(decrypted_email),
            chat_or_embed_url=decrypted_url,
            timestamp=issue.get("timestamp", ""),
            estimated_location=decrypted_location,
            device_info=decrypted_device_info,
            created_at=issue.get("created_at", ""),
            updated_at=issue.get("updated_at", ""),
            processed=issue.get("processed", False) or False,
            full_report=full_report,
        )
        
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error fetching issue {issue_id}: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=f"Failed to fetch issue: {str(e)}")


@router.delete("/issues/{issue_id}", response_model=DeleteIssueResponse)
@limiter.limit("30/minute")
async def delete_issue(
    request: Request,
    issue_id: str,
    admin_user: User = Depends(require_admin_api_key),
    directus_service: DirectusService = Depends(get_directus_service),
    encryption_service: EncryptionService = Depends(get_encryption_service),
) -> DeleteIssueResponse:
    """
    Delete an issue report (from Directus and S3).
    
    This performs a full delete:
    - Deletes the encrypted YAML file from S3 (if exists)
    - Deletes the issue record from Directus
    
    Args:
        issue_id: UUID of the issue to delete
        
    Returns:
        Confirmation of deletion
    """
    logger.info(f"Admin {admin_user.id} deleting issue: {issue_id}")
    
    try:
        # Fetch issue to get S3 key
        params = {
            "filter[id][_eq]": issue_id,
            "limit": 1,
        }
        issues = await directus_service.get_items("issues", params, no_cache=True, admin_required=True)
        
        if not issues:
            raise HTTPException(status_code=404, detail="Issue not found")
        
        issue = issues[0]
        deleted_from_s3 = False
        
        # Delete from S3 if exists
        if issue.get("encrypted_issue_report_yaml_s3_key"):
            try:
                s3_service = get_s3_service(request)
                
                # Decrypt S3 key
                s3_object_key = await encryption_service.decrypt_issue_report_data(
                    issue["encrypted_issue_report_yaml_s3_key"]
                )
                
                if s3_object_key:
                    # delete_file expects bucket_key and file_key (issue_logs → resolves to bucket name)
                    await s3_service.delete_file(
                        bucket_key='issue_logs',
                        file_key=s3_object_key
                    )
                    deleted_from_s3 = True
                    logger.info(f"Deleted S3 file for issue {issue_id}: {s3_object_key}")
            except Exception as e:
                logger.warning(f"Failed to delete S3 file for issue {issue_id}: {e}")
        
        # Delete from Directus
        success = await directus_service.delete_item("issues", issue_id, admin_required=True)
        if not success:
            raise HTTPException(status_code=500, detail="Failed to delete issue from database")
        
        logger.info(f"Admin {admin_user.id} successfully deleted issue {issue_id}")
        
        return DeleteIssueResponse(
            success=True,
            message=f"Issue {issue_id} deleted successfully",
            deleted_from_s3=deleted_from_s3,
        )
        
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error deleting issue {issue_id}: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=f"Failed to delete issue: {str(e)}")


# ============================================================================
# INSPECTION ENDPOINTS
# ============================================================================

@router.get("/inspect/chat/{chat_id}", response_model=InspectResponse)
@limiter.limit("30/minute")
async def inspect_chat(
    request: Request,
    chat_id: str,
    messages_limit: int = 20,
    embeds_limit: int = 20,
    usage_limit: int = 20,
    include_cache: bool = True,
    admin_user: User = Depends(require_admin_api_key),
    directus_service: DirectusService = Depends(get_directus_service),
    cache_service: CacheService = Depends(get_cache_service),
) -> InspectResponse:
    """
    Inspect a chat including metadata, messages, embeds, usage, and cache status.
    
    Equivalent to running: docker exec api python /app/backend/scripts/inspect_chat.py <chat_id>
    
    Args:
        chat_id: UUID of the chat to inspect
        messages_limit: Max messages to return (default: 20)
        embeds_limit: Max embeds to return (default: 20)
        usage_limit: Max usage entries to return (default: 20)
        include_cache: Include cache status (default: True)
        
    Returns:
        Comprehensive chat inspection data
    """
    logger.info(f"Admin {admin_user.id} inspecting chat: {chat_id}")
    
    try:
        # Fetch chat metadata
        chat_params = {
            "filter[id][_eq]": chat_id,
            "fields": "*",
            "limit": 1,
        }
        chats = await directus_service.get_items("chats", chat_params, no_cache=True)
        chat_metadata = chats[0] if chats else None
        
        # Fetch messages
        messages_params = {
            "filter[chat_id][_eq]": chat_id,
            "fields": "*",
            "sort": "created_at",
            "limit": messages_limit,
        }
        messages = await directus_service.get_items("messages", messages_params, no_cache=True) or []
        
        # Fetch embeds (using hashed chat_id)
        hashed_chat_id = hashlib.sha256(chat_id.encode()).hexdigest()
        embeds_params = {
            "filter[hashed_chat_id][_eq]": hashed_chat_id,
            "fields": "*",
            "sort": "-created_at",
            "limit": embeds_limit,
        }
        embeds = await directus_service.get_items("embeds", embeds_params, no_cache=True) or []
        
        # Fetch usage entries
        usage_params = {
            "filter[chat_id][_eq]": chat_id,
            "fields": "*",
            "sort": "-created_at",
            "limit": usage_limit,
        }
        usage_entries = await directus_service.get_items("usage", usage_params, no_cache=True, admin_required=True) or []
        
        # Check cache status
        cache_info = {}
        if include_cache:
            try:
                client = await cache_service.client
                if client:
                    # Scan for user-specific cache keys for this chat
                    pattern = f"user:*:chat:{chat_id}:*"
                    cursor = 0
                    found_keys = []
                    user_id = None
                    
                    while True:
                        cursor, keys = await client.scan(cursor, match=pattern, count=100)
                        for k in keys:
                            key_str = k.decode('utf-8') if isinstance(k, bytes) else k
                            found_keys.append(key_str)
                            # Extract user_id
                            parts = key_str.split(':')
                            if len(parts) >= 2 and parts[0] == 'user':
                                user_id = parts[1]
                        if cursor == 0:
                            break
                    
                    cache_info["discovered_user_id"] = user_id
                    cache_info["found_keys"] = found_keys[:20]  # Limit keys shown
                    cache_info["total_keys_found"] = len(found_keys)
                    
                    # Check specific cache entries if user_id found
                    if user_id:
                        versions_key = f"user:{user_id}:chat:{chat_id}:versions"
                        versions_data = await client.hgetall(versions_key)
                        if versions_data:
                            cache_info["chat_versions"] = {
                                k.decode('utf-8'): v.decode('utf-8') 
                                for k, v in versions_data.items()
                            }
            except Exception as e:
                cache_info["error"] = str(e)
        
        return InspectResponse(
            success=True,
            data={
                "chat_id": chat_id,
                "chat_metadata": chat_metadata,
                "messages": {
                    "count": len(messages),
                    "items": messages,
                },
                "embeds": {
                    "count": len(embeds),
                    "items": embeds,
                },
                "usage": {
                    "count": len(usage_entries),
                    "items": usage_entries,
                },
                "cache": cache_info,
            },
            generated_at=datetime.now(timezone.utc).isoformat(),
        )
        
    except Exception as e:
        logger.error(f"Error inspecting chat {chat_id}: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=f"Failed to inspect chat: {str(e)}")


@router.get("/inspect/user/{email}", response_model=InspectResponse)
@limiter.limit("30/minute")
async def inspect_user(
    request: Request,
    email: str,
    recent_limit: int = 5,
    include_cache: bool = True,
    admin_user: User = Depends(require_admin_api_key),
    directus_service: DirectusService = Depends(get_directus_service),
    encryption_service: EncryptionService = Depends(get_encryption_service),
    cache_service: CacheService = Depends(get_cache_service),
) -> InspectResponse:
    """
    Inspect a user by email including metadata, decrypted fields, counts, and cache status.
    
    Equivalent to running: docker exec api python /app/backend/scripts/inspect_user.py <email>
    
    Args:
        email: User's email address
        recent_limit: Max recent activities to return (default: 5)
        include_cache: Include cache status (default: True)
        
    Returns:
        Comprehensive user inspection data
    """
    logger.info(f"Admin {admin_user.id} inspecting user: {email}")
    
    try:
        import base64
        
        # Hash email for lookup
        email_bytes = email.strip().lower().encode('utf-8')
        hashed_email = base64.b64encode(hashlib.sha256(email_bytes).digest()).decode('utf-8')
        
        # Fetch user data
        url = f"{directus_service.base_url}/users"
        admin_token = await directus_service.ensure_auth_token(admin_required=True)
        headers = {"Authorization": f"Bearer {admin_token}"}
        params = {
            "filter[hashed_email][_eq]": hashed_email,
            "fields": "*",
            "limit": 1,
        }
        
        response = await directus_service._make_api_request("GET", url, params=params, headers=headers)
        if response.status_code != 200:
            raise HTTPException(status_code=404, detail="User not found")
        
        data = response.json().get("data", [])
        if not data:
            raise HTTPException(status_code=404, detail=f"User with email {email} not found")
        
        user_data = data[0]
        user_id = user_data.get("id")
        
        # Check admin status
        is_server_admin = await directus_service.admin.is_user_admin(user_id)
        user_data["is_server_admin"] = is_server_admin
        
        # Hash user_id for related lookups
        hashed_user_id = hashlib.sha256(user_id.encode()).hexdigest()
        
        # Get counts of related items
        counts = {}
        collections = [
            ("chats", "hashed_user_id", hashed_user_id),
            ("embeds", "hashed_user_id", hashed_user_id),
            ("usage", "user_id_hash", hashed_user_id),
            ("api_keys", "user_id", user_id),
        ]
        
        for coll, field, val in collections:
            try:
                count_params = {
                    f"filter[{field}][_eq]": val,
                    "limit": 1,
                    "meta": "filter_count",
                }
                count_url = f"{directus_service.base_url}/items/{coll}"
                count_resp = await directus_service._make_api_request("GET", count_url, params=count_params, headers=headers)
                if count_resp.status_code == 200:
                    counts[coll] = count_resp.json().get("meta", {}).get("filter_count", 0)
            except Exception:
                counts[coll] = 0
        
        # Get recent chats
        recent_chats = await directus_service.get_items("chats", {
            "filter[hashed_user_id][_eq]": hashed_user_id,
            "sort": "-updated_at",
            "limit": recent_limit,
            "fields": "id,created_at,updated_at",
        }, no_cache=True) or []
        
        # Check cache status
        cache_info = {}
        if include_cache:
            try:
                client = await cache_service.client
                if client:
                    # Check primed flag
                    primed_key = f"user:{user_id}:cache_status:primed_flag"
                    cache_info["primed"] = bool(await client.get(primed_key))
                    
                    # Check chat_ids_versions count
                    cv_key = f"user:{user_id}:chat_ids_versions"
                    cache_info["chat_ids_versions_count"] = await client.zcard(cv_key)
                    
                    # Scan for all user keys
                    pattern = f"user:{user_id}:*"
                    cursor = 0
                    found_keys = []
                    while True:
                        cursor, keys = await client.scan(cursor, match=pattern, count=100)
                        found_keys.extend([k.decode('utf-8') if isinstance(k, bytes) else k for k in keys])
                        if cursor == 0:
                            break
                    cache_info["total_keys_found"] = len(found_keys)
                    cache_info["sample_keys"] = sorted(found_keys)[:10]
            except Exception as e:
                cache_info["error"] = str(e)
        
        # Remove sensitive encrypted fields from response (keep only metadata)
        safe_user_data = {k: v for k, v in user_data.items() if not k.startswith("encrypted_")}
        safe_user_data["has_encrypted_fields"] = [k for k in user_data.keys() if k.startswith("encrypted_")]
        
        return InspectResponse(
            success=True,
            data={
                "email": censor_email(email),
                "user_metadata": safe_user_data,
                "item_counts": counts,
                "recent_chats": recent_chats,
                "cache": cache_info,
            },
            generated_at=datetime.now(timezone.utc).isoformat(),
        )
        
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error inspecting user {email}: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=f"Failed to inspect user: {str(e)}")


@router.get("/inspect/embed/{embed_id}", response_model=InspectResponse)
@limiter.limit("30/minute")
async def inspect_embed(
    request: Request,
    embed_id: str,
    admin_user: User = Depends(require_admin_api_key),
    directus_service: DirectusService = Depends(get_directus_service),
) -> InspectResponse:
    """
    Inspect an embed including metadata, encryption keys, and child embeds.
    
    Equivalent to running: docker exec api python /app/backend/scripts/inspect_embed.py <embed_id>
    
    Args:
        embed_id: The embed ID to inspect
        
    Returns:
        Embed data, encryption keys, and child embeds
    """
    logger.info(f"Admin {admin_user.id} inspecting embed: {embed_id}")
    
    try:
        # Fetch embed
        embed_params = {
            "filter[embed_id][_eq]": embed_id,
            "fields": "*",
            "limit": 1,
        }
        embeds = await directus_service.get_items("embeds", embed_params, no_cache=True)
        embed = embeds[0] if embeds else None
        
        if not embed:
            raise HTTPException(status_code=404, detail=f"Embed not found: {embed_id}")
        
        # Fetch embed keys
        hashed_embed_id = hashlib.sha256(embed_id.encode()).hexdigest()
        keys_params = {
            "filter[hashed_embed_id][_eq]": hashed_embed_id,
            "fields": "*",
        }
        embed_keys = await directus_service.get_items("embed_keys", keys_params, no_cache=True) or []
        
        # Fetch child embeds if any
        child_embeds = []
        child_ids = embed.get("embed_ids", [])
        if child_ids:
            for child_id in child_ids[:10]:  # Limit to 10 children
                child_params = {
                    "filter[embed_id][_eq]": child_id,
                    "fields": "*",
                    "limit": 1,
                }
                child_results = await directus_service.get_items("embeds", child_params, no_cache=True)
                if child_results:
                    child_embeds.append(child_results[0])
        
        return InspectResponse(
            success=True,
            data={
                "embed_id": embed_id,
                "embed": embed,
                "embed_keys": {
                    "count": len(embed_keys),
                    "items": embed_keys,
                },
                "child_embeds": {
                    "count": len(child_embeds),
                    "items": child_embeds,
                },
            },
            generated_at=datetime.now(timezone.utc).isoformat(),
        )
        
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error inspecting embed {embed_id}: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=f"Failed to inspect embed: {str(e)}")


@router.get("/inspect/demo-chat/{demo_id}", response_model=InspectResponse)
@limiter.limit("30/minute")
async def inspect_demo_chat(
    request: Request,
    demo_id: str,
    language: str = "en",
    messages_limit: int = 20,
    embeds_limit: int = 20,
    include_cache: bool = True,
    admin_user: User = Depends(require_admin_api_key),
    directus_service: DirectusService = Depends(get_directus_service),
    cache_service: CacheService = Depends(get_cache_service),
) -> InspectResponse:
    """
    Inspect a demo chat including metadata, translations, messages, and embeds.
    
    Equivalent to running: docker exec api python /app/backend/scripts/inspect_demo_chat.py <demo_id>
    
    Args:
        demo_id: Demo ID (demo-1, demo-2, etc.) or UUID
        language: Language for messages (default: en)
        messages_limit: Max messages to return (default: 20)
        embeds_limit: Max embeds to return (default: 20)
        include_cache: Include cache status (default: True)
        
    Returns:
        Comprehensive demo chat inspection data
    """
    logger.info(f"Admin {admin_user.id} inspecting demo chat: {demo_id} (lang={language})")
    
    try:
        import json
        
        # Resolve demo_id to UUID
        demo_chat_uuid = None
        demo_metadata = None
        
        if demo_id.startswith("demo-"):
            # Display ID - need to find by index
            try:
                index = int(demo_id.split("-")[1]) - 1
                demos_params = {
                    "filter": {
                        "status": {"_eq": "published"},
                        "is_active": {"_eq": True},
                    },
                    "sort": ["-created_at"],
                    "fields": "*",
                    "limit": 100,
                }
                demos = await directus_service.get_items("demo_chats", demos_params, no_cache=True)
                if demos and len(demos) > index:
                    demo_metadata = demos[index]
                    demo_chat_uuid = demo_metadata.get("id")
            except (ValueError, IndexError):
                pass
        else:
            # Assume UUID
            demo_params = {
                "filter[id][_eq]": demo_id,
                "fields": "*",
                "limit": 1,
            }
            demos = await directus_service.get_items("demo_chats", demo_params, no_cache=True)
            if demos:
                demo_metadata = demos[0]
                demo_chat_uuid = demo_metadata.get("id")
        
        if not demo_chat_uuid:
            raise HTTPException(status_code=404, detail=f"Demo chat not found: {demo_id}")
        
        # Fetch translations
        translations_params = {
            "filter[demo_chat_id][_eq]": demo_chat_uuid,
            "fields": "*",
            "sort": "language",
        }
        translations = await directus_service.get_items("demo_chat_translations", translations_params, no_cache=True) or []
        
        # Fetch messages for language
        messages_params = {
            "filter": {
                "demo_chat_id": {"_eq": demo_chat_uuid},
                "language": {"_eq": language},
            },
            "fields": "*",
            "sort": ["original_created_at"],
            "limit": messages_limit,
        }
        messages = await directus_service.get_items("demo_messages", messages_params, no_cache=True) or []
        
        # Fetch embeds (always 'original' language)
        embeds_params = {
            "filter": {
                "demo_chat_id": {"_eq": demo_chat_uuid},
                "language": {"_eq": "original"},
            },
            "fields": "*",
            "sort": ["-original_created_at"],
            "limit": embeds_limit,
        }
        embeds = await directus_service.get_items("demo_embeds", embeds_params, no_cache=True) or []
        
        # Check cache status
        cache_info = {}
        if include_cache:
            try:
                client = await cache_service.client
                if client:
                    # Check demo chat data cache
                    languages = ['en', 'de', 'fr', 'es', 'it', 'pt', 'ja', 'ko', 'zh']
                    demo_data_cache = {}
                    for lang in languages:
                        demo_data_key = f"public:demo_chat:data:{demo_id}:{lang}"
                        demo_data = await client.get(demo_data_key)
                        if demo_data:
                            try:
                                parsed = json.loads(demo_data.decode('utf-8'))
                                demo_data_cache[lang] = {
                                    "exists": True,
                                    "message_count": len(parsed.get("chat_data", {}).get("messages", [])),
                                }
                            except (json.JSONDecodeError, UnicodeDecodeError):
                                demo_data_cache[lang] = {"exists": True, "parse_error": True}
                        else:
                            demo_data_cache[lang] = {"exists": False}
                    cache_info["demo_data_cache"] = demo_data_cache
            except Exception as e:
                cache_info["error"] = str(e)
        
        return InspectResponse(
            success=True,
            data={
                "demo_id": demo_id,
                "demo_chat_uuid": demo_chat_uuid,
                "language": language,
                "demo_metadata": demo_metadata,
                "translations": {
                    "count": len(translations),
                    "available_languages": [t.get("language") for t in translations],
                    "items": translations,
                },
                "messages": {
                    "count": len(messages),
                    "language": language,
                    "items": messages,
                },
                "embeds": {
                    "count": len(embeds),
                    "items": embeds,
                },
                "cache": cache_info,
            },
            generated_at=datetime.now(timezone.utc).isoformat(),
        )
        
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error inspecting demo chat {demo_id}: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=f"Failed to inspect demo chat: {str(e)}")


@router.get("/inspect/last-requests", response_model=InspectResponse)
@limiter.limit("30/minute")
async def inspect_last_requests(
    request: Request,
    chat_id: Optional[str] = None,
    admin_user: User = Depends(require_admin_api_key),
    cache_service: CacheService = Depends(get_cache_service),
    encryption_service: EncryptionService = Depends(get_encryption_service),
) -> InspectResponse:
    """
    Inspect the last 10 AI request debug entries.
    
    Equivalent to running: docker exec api python /app/backend/scripts/inspect_last_requests.py
    
    These entries contain preprocessor, main processor, and postprocessor input/output
    for debugging AI request processing. Entries expire after 30 minutes.
    
    Args:
        chat_id: Optional filter by chat ID
        
    Returns:
        List of debug request entries (most recent first)
    """
    logger.info(f"Admin {admin_user.id} inspecting last requests (chat_id={chat_id})")
    
    try:
        # Get debug entries from cache
        if chat_id:
            entries = await cache_service.get_debug_requests_for_chat(
                encryption_service=encryption_service,
                chat_id=chat_id
            )
        else:
            entries = await cache_service.get_all_debug_requests(
                encryption_service=encryption_service
            )
        
        # Sort entries chronologically (oldest first, like the script does)
        sorted_entries = sorted(entries, key=lambda e: e.get('timestamp', 0))
        
        # Format entries for response
        formatted_entries = []
        for i, entry in enumerate(sorted_entries, 1):
            formatted_entries.append({
                "request_number": i,
                "task_id": entry.get("task_id"),
                "chat_id": entry.get("chat_id"),
                "timestamp": entry.get("timestamp"),
                "preprocessor": {
                    "input": entry.get("preprocessor_input"),
                    "output": entry.get("preprocessor_output"),
                },
                "main_processor": {
                    "input": entry.get("main_processor_input"),
                    "output": entry.get("main_processor_output"),
                },
                "postprocessor": {
                    "input": entry.get("postprocessor_input"),
                    "output": entry.get("postprocessor_output"),
                },
            })
        
        return InspectResponse(
            success=True,
            data={
                "chat_id_filter": chat_id,
                "total_entries": len(formatted_entries),
                "note": "Debug entries expire after 30 minutes. Entries sorted chronologically (oldest first).",
                "requests": formatted_entries,
            },
            generated_at=datetime.now(timezone.utc).isoformat(),
        )
        
    except Exception as e:
        logger.error(f"Error inspecting last requests: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=f"Failed to inspect last requests: {str(e)}")


# ============================================================================
# UTILITY ENDPOINTS
# ============================================================================

@router.get("/allowed-services")
@limiter.limit("60/minute")
async def get_allowed_services(
    request: Request,
    admin_user: User = Depends(require_admin_api_key),
) -> Dict[str, Any]:
    """
    Get the list of services that can be queried for logs.
    
    Returns:
        List of allowed service names
    """
    return {
        "allowed_services": ALLOWED_LOG_SERVICES,
        "count": len(ALLOWED_LOG_SERVICES),
    }


# ============================================================================
# NEWSLETTER INSPECTION
# ============================================================================

@router.get("/newsletter", include_in_schema=False)
@limiter.limit("30/minute")
async def inspect_newsletter(
    request: Request,
    show_emails: bool = False,
    show_pending: bool = False,
    timeline: bool = False,
    admin_user: User = Depends(require_admin_api_key),
    directus_service: DirectusService = Depends(get_directus_service),
    cache_service: CacheService = Depends(get_cache_service),
    encryption_service: EncryptionService = Depends(get_encryption_service),
) -> Dict[str, Any]:
    """
    Inspect newsletter subscription data.

    Shows confirmed subscriber count, language breakdown, ignored email count,
    and optionally decrypted subscriber emails, pending cache entries, and timeline.

    Query params:
        show_emails: Decrypt and return subscriber email addresses
        show_pending: Include pending (unconfirmed) subscriptions from cache
        timeline: Include monthly subscription timeline
    """
    from collections import defaultdict

    result: Dict[str, Any] = {}

    try:
        # 1. Fetch all subscriber records with meta counts
        collection_url = f"{directus_service.base_url}/items/newsletter_subscribers"
        all_params = {
            "fields": "id,encrypted_email_address,hashed_email,confirmed_at,subscribed_at,language,darkmode,unsubscribe_token",
            "sort": "-subscribed_at",
            "limit": -1,
            "meta": "total_count,filter_count",
        }
        response = await directus_service._make_api_request("GET", collection_url, params=all_params)

        subscribers: List[Dict[str, Any]] = []
        total_records = 0
        if response.status_code == 200:
            data = response.json()
            subscribers = data.get("data", [])
            meta = data.get("meta", {})
            total_records = int(meta.get("total_count", len(subscribers)))

        confirmed_count = sum(1 for s in subscribers if s.get("confirmed_at"))
        unconfirmed_count = total_records - confirmed_count

        # 2. Language and darkmode breakdown
        lang_breakdown: Dict[str, int] = defaultdict(int)
        darkmode_count = 0
        for sub in subscribers:
            lang = sub.get("language", "unknown")
            lang_breakdown[lang] += 1
            if sub.get("darkmode"):
                darkmode_count += 1

        # 3. Ignored emails count
        ignored_count = 0
        try:
            ignored_url = f"{directus_service.base_url}/items/ignored_emails"
            ignored_resp = await directus_service._make_api_request(
                "GET", ignored_url, params={"limit": 1, "meta": "total_count"}
            )
            if ignored_resp.status_code == 200:
                ignored_meta = ignored_resp.json().get("meta", {})
                ignored_count = int(ignored_meta.get("total_count", 0))
        except Exception as e:
            logger.warning(f"Error fetching ignored emails count: {e}")

        result["summary"] = {
            "total_records_in_directus": total_records,
            "confirmed_subscribers": confirmed_count,
            "unconfirmed_records": unconfirmed_count,
            "ignored_blocked_emails": ignored_count,
            "language_breakdown": dict(sorted(lang_breakdown.items(), key=lambda x: -x[1])),
            "darkmode_subscribers": darkmode_count,
        }

        # 4. Pending subscriptions from cache
        if show_pending:
            pending_entries: List[Dict[str, Any]] = []
            try:
                keys = await cache_service.get_keys_by_pattern("newsletter_subscribe:*")
                for key in keys:
                    cache_data = await cache_service.get(key)
                    if cache_data:
                        token = key.replace("newsletter_subscribe:", "")
                        entry: Dict[str, Any] = {
                            "token": token[:8] + "...",
                            "email": censor_email(cache_data.get("email", "unknown")),
                            "language": cache_data.get("language", "en"),
                            "darkmode": cache_data.get("darkmode", False),
                            "created_at": cache_data.get("created_at", "unknown"),
                        }
                        try:
                            client = await cache_service.client
                            if client:
                                ttl_val = await client.ttl(key)
                                if ttl_val and ttl_val > 0:
                                    entry["expires_in_minutes"] = round(ttl_val / 60, 1)
                        except Exception:
                            pass
                        pending_entries.append(entry)
            except Exception as e:
                logger.warning(f"Error scanning cache for pending subscriptions: {e}")

            result["pending_in_cache"] = {
                "count": len(pending_entries),
                "entries": pending_entries,
            }

        # 5. Decrypted subscriber list
        if show_emails:
            subscriber_list: List[Dict[str, Any]] = []
            for sub in subscribers:
                encrypted = sub.get("encrypted_email_address", "")
                email = None
                if encrypted:
                    try:
                        email = await encryption_service.decrypt_newsletter_email(encrypted)
                    except Exception:
                        pass
                subscriber_list.append({
                    "id": sub.get("id"),
                    "email": email or "[decrypt failed]",
                    "confirmed_at": sub.get("confirmed_at"),
                    "subscribed_at": sub.get("subscribed_at"),
                    "language": sub.get("language", "unknown"),
                    "darkmode": sub.get("darkmode", False),
                    "has_unsubscribe_token": bool(sub.get("unsubscribe_token")),
                })
            result["subscribers"] = subscriber_list

        # 6. Monthly timeline
        if timeline:
            monthly: Dict[str, int] = defaultdict(int)
            for sub in subscribers:
                ts = sub.get("confirmed_at") or sub.get("subscribed_at")
                if ts:
                    try:
                        ts_str = ts.replace("Z", "+00:00") if isinstance(ts, str) else str(ts)
                        dt = datetime.fromisoformat(ts_str)
                        monthly[dt.strftime("%Y-%m")] += 1
                    except Exception:
                        pass
            result["timeline_monthly"] = dict(sorted(monthly.items()))

    except Exception as e:
        logger.error(f"Error inspecting newsletter: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=f"Error inspecting newsletter: {str(e)}")

    return result
