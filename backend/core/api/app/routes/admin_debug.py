# backend/core/api/app/routes/admin_debug.py
"""
REST API endpoints for admin debugging functionality.

These endpoints allow admins to remotely debug production issues without SSH access:
- Query Docker Compose logs via OpenObserve
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

import asyncio
import hashlib
import logging
import os
import re
import time
from datetime import datetime, timedelta, timezone
from typing import Any, Dict, List, Literal, Optional, Union

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
from backend.core.api.app.services.openobserve_log_collector import openobserve_log_collector
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
# Excluded: vault, vault-setup (secrets), openobserve, prometheus, promtail, cadvisor (monitoring infra)

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
    "app-pdf",
    # App workers
    "app-ai-worker",
    "app-web-worker",
    "app-images-worker",
    "app-pdf-worker",
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
    is_from_admin: bool = False
    reported_by_user_id: Optional[str] = None
    linear_issue_identifier: Optional[str] = None


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
    is_from_admin: bool = False
    reported_by_user_id: Optional[str] = None
    linear_issue_identifier: Optional[str] = None
    full_report: Optional[Dict[str, Any]] = None
    # Screenshot verification (added to support E2E verification that the
    # screenshot attach flow and S3 upload worked end-to-end).
    has_screenshot: bool = False
    screenshot_presigned_url: Optional[str] = None
    # YAML S3 report presence — set by issue_report_email_task after the
    # YAML is encrypted and uploaded to S3. The test polls for this.
    has_yaml_report: bool = False


class DeleteIssueResponse(BaseModel):
    """Response model for issue deletion."""
    success: bool
    message: str
    deleted_from_s3: bool


class IssueTimelineEvent(BaseModel):
    """A single event in the issue timeline."""
    ts_us: int          # OpenObserve timestamp in microseconds
    level: str          # log level (info/warn/error/critical)
    source: str         # container name or 'browser'
    message: str        # log message (truncated to 200 chars)


class IssueTimelineResponse(BaseModel):
    """Unified browser + backend log timeline for an issue."""
    issue: Dict[str, Any]       # minimal issue metadata (id, title, created_at, reported_by_user_id)
    events: List[IssueTimelineEvent]
    start_us: int               # query window start (microseconds)
    end_us: int                 # query window end (microseconds)
    before_minutes: int
    after_minutes: int
    generated_at: str


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
    Query Docker Compose logs from OpenObserve.
    
    This endpoint allows querying logs from predefined services via OpenObserve.
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
        # Query OpenObserve for logs
        logs = await openobserve_log_collector.get_compose_logs(
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
                is_from_admin=issue.get("is_from_admin", False) or False,
                reported_by_user_id=issue.get("reported_by_user_id"),
                linear_issue_identifier=issue.get("linear_issue_identifier"),
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
        
        # Decrypt screenshot S3 key and generate a presigned URL for E2E verification.
        # The screenshot is uploaded synchronously in the /v1/settings/issues handler,
        # so it is available immediately after issue creation (unlike the YAML report
        # which is generated asynchronously by the email task).
        has_screenshot = bool(issue.get("encrypted_screenshot_s3_key"))
        screenshot_presigned_url: Optional[str] = None
        if has_screenshot:
            try:
                s3_service = get_s3_service(request)
                screenshot_s3_key = await encryption_service.decrypt_issue_report_data(
                    issue["encrypted_screenshot_s3_key"]
                )
                if screenshot_s3_key:
                    from backend.core.api.app.services.s3.config import get_bucket_name as _get_bucket_name
                    screenshot_bucket = _get_bucket_name('issue_logs', os.getenv('SERVER_ENVIRONMENT', 'development'))
                    screenshot_presigned_url = s3_service.generate_presigned_url(
                        bucket_name=screenshot_bucket,
                        file_key=screenshot_s3_key,
                        expiration=3600  # 1h is enough for inspection
                    )
            except Exception as e:
                logger.warning(f"Failed to generate screenshot presigned URL for issue {issue_id}: {e}")

        # Flag for whether a YAML report is available — lets E2E tests poll
        # for eventual upload completion without needing to parse full_report.
        has_yaml_report = bool(issue.get("encrypted_issue_report_yaml_s3_key"))

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
            is_from_admin=issue.get("is_from_admin", False) or False,
            reported_by_user_id=issue.get("reported_by_user_id"),
            linear_issue_identifier=issue.get("linear_issue_identifier"),
            full_report=full_report,
            has_screenshot=has_screenshot,
            screenshot_presigned_url=screenshot_presigned_url,
            has_yaml_report=has_yaml_report,
        )
        
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error fetching issue {issue_id}: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=f"Failed to fetch issue: {str(e)}")


@router.get("/issues/{issue_id}/timeline", response_model=IssueTimelineResponse)
@limiter.limit("30/minute")
async def get_issue_timeline(
    request: Request,
    issue_id: str,
    before_minutes: int = 10,
    after_minutes: int = 5,
    admin_user: User = Depends(require_admin_api_key),
    directus_service: DirectusService = Depends(get_directus_service),
) -> IssueTimelineResponse:
    """
    Unified browser + backend log timeline for an issue, queried live from OpenObserve.

    Anchors the time window to the issue's created_at timestamp and runs three parallel
    OpenObserve SQL queries:
      1. Browser console snapshot: job=client-issue-report AND issue_id=<id>
      2. Backend container logs: container-logs mentioning issue_id or user_id
      3. API application logs: api-logs mentioning issue_id or user_id

    Returns all events merged and sorted chronologically so the CLI can render a
    unified timeline without needing to decrypt the S3 YAML.

    Args:
        issue_id: UUID of the issue
        before_minutes: Minutes before created_at to include (default: 10)
        after_minutes: Minutes after created_at to include (default: 5)
    """
    logger.info(
        f"Admin {admin_user.id} fetching timeline for issue {issue_id} "
        f"(−{before_minutes}min/+{after_minutes}min)"
    )

    # 1. Fetch the issue metadata (to get created_at and reported_by_user_id)
    try:
        params = {"filter[id][_eq]": issue_id, "fields": "*", "limit": 1}
        issues = await directus_service.get_items("issues", params, no_cache=True)
        if not issues:
            raise HTTPException(status_code=404, detail=f"Issue not found: {issue_id}")
        issue = issues[0]
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error fetching issue {issue_id} for timeline: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=f"Failed to fetch issue: {str(e)}")

    user_id  = issue.get("reported_by_user_id") or ""

    # 2. Determine anchor timestamp from created_at
    created_at_str = issue.get("created_at") or issue.get("timestamp") or ""
    try:
        anchor_dt = datetime.fromisoformat(created_at_str.replace("Z", "+00:00"))
        anchor_us = int(anchor_dt.timestamp() * 1_000_000)
    except Exception:
        anchor_us = int(time.time() * 1_000_000)

    start_us = anchor_us - before_minutes * 60 * 1_000_000
    end_us   = anchor_us + after_minutes  * 60 * 1_000_000
    now_us   = int(time.time() * 1_000_000)
    if end_us > now_us:
        end_us = now_us

    # 3. Run parallel OpenObserve SQL queries
    def _sql_esc(s: str) -> str:
        return s.replace("'", "''")

    issue_id_esc = _sql_esc(issue_id)
    search_terms = [issue_id_esc]
    if user_id:
        search_terms.append(_sql_esc(user_id))

    like_clauses = " OR ".join(
        f"log LIKE '%{t}%' OR message LIKE '%{t}%'" for t in search_terms
    )

    async def _query(sql: str) -> List[Dict[str, Any]]:
        """Execute one SQL query against the local OpenObserve instance."""
        sql_body = sql.strip().rstrip(";")
        if " limit " not in sql_body.lower():
            sql_body = f"{sql_body} LIMIT 2000"
        body = {"query": {"sql": sql_body, "start_time": start_us, "end_time": end_us}}
        email    = os.getenv("OPENOBSERVE_ROOT_EMAIL", "")
        password = os.getenv("OPENOBSERVE_ROOT_PASSWORD", "")
        import aiohttp
        url = "http://openobserve:5080/api/default/_search"
        auth = aiohttp.BasicAuth(email, password)
        timeout = aiohttp.ClientTimeout(total=30)
        try:
            async with aiohttp.ClientSession(timeout=timeout) as session:
                async with session.post(url, json=body, auth=auth) as resp:
                    if resp.status == 200:
                        data = await resp.json()
                        return data.get("hits", [])
                    logger.warning(
                        f"OpenObserve timeline query failed ({resp.status}): "
                        f"{(await resp.text())[:200]}"
                    )
                    return []
        except Exception as exc:
            logger.warning(f"OpenObserve timeline query error: {exc}")
            return []

    browser_sql = (
        f"SELECT _timestamp, message, level "
        f'FROM "default" '
        f"WHERE job = 'client-issue-report' AND issue_id = '{issue_id_esc}' "
        f"ORDER BY _timestamp ASC"
    )
    container_sql = (
        f"SELECT _timestamp, container, service, log, message, level "
        f'FROM "default" '
        f"WHERE job = 'container-logs' AND ({like_clauses}) "
        f"ORDER BY _timestamp ASC"
    )
    api_sql = (
        f"SELECT _timestamp, container, service, log, message, level "
        f'FROM "default" '
        f"WHERE job = 'api-logs' AND ({like_clauses}) "
        f"ORDER BY _timestamp ASC"
    )

    browser_hits, container_hits, api_hits = await asyncio.gather(
        _query(browser_sql),
        _query(container_sql),
        _query(api_sql),
    )

    # 4. Normalise hits into IssueTimelineEvent objects
    raw_events: List[Dict[str, Any]] = []

    for hit in browser_hits:
        raw_events.append({
            "ts_us":   int(hit.get("_timestamp", 0)),
            "level":   (hit.get("level") or "info").lower(),
            "source":  "browser",
            "message": (hit.get("message") or "").strip()[:200],
        })

    for hit in container_hits + api_hits:
        raw_events.append({
            "ts_us":   int(hit.get("_timestamp", 0)),
            "level":   (hit.get("level") or "info").lower(),
            "source":  (hit.get("container") or hit.get("service") or "unknown"),
            "message": (hit.get("message") or hit.get("log") or "").strip()[:200],
        })

    # Deduplicate and sort
    seen: set = set()
    unique: List[Dict[str, Any]] = []
    for evt in sorted(raw_events, key=lambda e: e["ts_us"]):
        key = (evt["ts_us"], evt["message"][:100])
        if key not in seen:
            seen.add(key)
            unique.append(evt)

    events = [IssueTimelineEvent(**e) for e in unique]

    # 5. Build minimal issue dict (no encrypted fields)
    issue_summary = {
        "id":                  issue.get("id"),
        "title":               issue.get("title", ""),
        "created_at":          issue.get("created_at", ""),
        "timestamp":           issue.get("timestamp", ""),
        "reported_by_user_id": user_id or None,
    }

    return IssueTimelineResponse(
        issue=issue_summary,
        events=events,
        start_us=start_us,
        end_us=end_us,
        before_minutes=before_minutes,
        after_minutes=after_minutes,
        generated_at=datetime.now(timezone.utc).isoformat(),
    )


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
    - Deletes the screenshot PNG from S3 (if exists)
    - Deletes the issue record from Directus
    
    Args:
        issue_id: UUID of the issue to delete
        
    Returns:
        Confirmation of deletion
    """
    logger.info(f"Admin {admin_user.id} deleting issue: {issue_id}")
    
    try:
        # Fetch issue to get S3 keys
        params = {
            "filter[id][_eq]": issue_id,
            "limit": 1,
        }
        issues = await directus_service.get_items("issues", params, no_cache=True, admin_required=True)
        
        if not issues:
            raise HTTPException(status_code=404, detail="Issue not found")
        
        issue = issues[0]
        deleted_from_s3 = False
        s3_service = get_s3_service(request)

        # Delete YAML report from S3 if exists
        if issue.get("encrypted_issue_report_yaml_s3_key"):
            try:
                # Decrypt S3 key
                s3_object_key = await encryption_service.decrypt_issue_report_data(
                    issue["encrypted_issue_report_yaml_s3_key"]
                )
                
                if s3_object_key:
                    await s3_service.delete_file(
                        bucket_key='issue_logs',
                        file_key=s3_object_key
                    )
                    deleted_from_s3 = True
                    logger.info(f"Deleted S3 YAML file for issue {issue_id}: {s3_object_key}")
            except Exception as e:
                logger.warning(f"Failed to delete S3 YAML file for issue {issue_id}: {e}")

        # Delete screenshot PNG from S3 if exists
        if issue.get("encrypted_screenshot_s3_key"):
            try:
                screenshot_s3_key = await encryption_service.decrypt_issue_report_data(
                    issue["encrypted_screenshot_s3_key"]
                )
                if screenshot_s3_key:
                    await s3_service.delete_file(
                        bucket_key='issue_logs',
                        file_key=screenshot_s3_key
                    )
                    logger.info(f"Deleted S3 screenshot for issue {issue_id}: {screenshot_s3_key}")
            except Exception as e:
                logger.warning(f"Failed to delete S3 screenshot for issue {issue_id}: {e}")
        
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
# ERROR FINGERPRINT ENDPOINT
# ============================================================================
# Returns the top-N recurring error fingerprints from the Redis sorted set
# maintained by LoggingMiddleware. Each fingerprint encodes
# exc_type:filename:function:lineno and its occurrence count.
# See backend/core/api/app/middleware/logging_middleware.py for fingerprinting logic.
# ============================================================================

class ErrorFingerprintEntry(BaseModel):
    """A single error fingerprint with its occurrence count."""
    fingerprint: str  # 12-char hex prefix of SHA-256
    canonical_key: str  # exc_type:filename:function:lineno
    count: int  # Total occurrence count


class ErrorsResponse(BaseModel):
    success: bool
    total_unique_errors: int
    top_errors: List[ErrorFingerprintEntry]
    generated_at: str


@router.get("/errors", response_model=ErrorsResponse, include_in_schema=False)
@limiter.limit("30/minute")
async def list_error_fingerprints(
    request: Request,
    top: int = 20,
    admin_user: User = Depends(require_admin_api_key),
    cache_service: CacheService = Depends(get_cache_service),
) -> ErrorsResponse:
    """
    Return the top-N error fingerprints by occurrence count.

    Error fingerprints are computed by LoggingMiddleware for every unhandled
    exception (5xx). Each fingerprint is a short hash of
    (exc_type, file, function, line) so that distinct error messages for the
    same code location are grouped together.

    Query params:
        top: How many fingerprints to return (default 20, max 200).

    Equivalent to running: docker exec api python /app/backend/scripts/debug.py errors
    """
    top = min(max(1, top), 200)  # Clamp to [1, 200]
    logger.info(f"Admin {admin_user.id} querying error fingerprints (top={top})")

    try:
        client = await cache_service.client
        from backend.core.api.app.middleware.logging_middleware import REDIS_ERROR_FINGERPRINTS_KEY
        total = await client.zcard(REDIS_ERROR_FINGERPRINTS_KEY)

        # Fetch top-N by score descending (highest occurrence count first)
        raw_entries = await client.zrevrangebyscore(
            REDIS_ERROR_FINGERPRINTS_KEY,
            "+inf",
            "-inf",
            withscores=True,
            start=0,
            num=top,
        )

        top_errors: List[ErrorFingerprintEntry] = []
        for member, score in raw_entries:
            member_str = member.decode("utf-8") if isinstance(member, bytes) else member
            # member format: "<fingerprint>|<canonical_key>"
            if "|" in member_str:
                fingerprint, canonical_key = member_str.split("|", 1)
            else:
                fingerprint = member_str
                canonical_key = member_str
            top_errors.append(
                ErrorFingerprintEntry(
                    fingerprint=fingerprint,
                    canonical_key=canonical_key,
                    count=int(score),
                )
            )

        return ErrorsResponse(
            success=True,
            total_unique_errors=total,
            top_errors=top_errors,
            generated_at=datetime.now(timezone.utc).isoformat(),
        )

    except Exception as e:
        logger.error(f"Error fetching error fingerprints: {e}", exc_info=True)
        raise HTTPException(
            status_code=500,
            detail=f"Failed to fetch error fingerprints: {str(e)}",
        )


# ============================================================================
# ERROR LOG QUERY ENDPOINT (OpenObserve)
# ============================================================================


class ErrorLogEntry(BaseModel):
    """A single error log entry grouped by message, service, and level."""
    message: str
    service: str
    level: str
    count: int


class ErrorLogsResponse(BaseModel):
    """Response for the /errors/logs endpoint."""
    success: bool
    hits: List[ErrorLogEntry]
    total: int
    since_minutes: int
    generated_at: str


@router.get("/errors/logs", response_model=ErrorLogsResponse, include_in_schema=False)
@limiter.limit("30/minute")
async def list_error_logs(
    request: Request,
    since_minutes: int = 1440,
    top: int = 15,
    compose_project: str = "openmates-core",
    admin_user: User = Depends(require_admin_api_key),
) -> ErrorLogsResponse:
    """
    Query OpenObserve for ERROR/CRITICAL log entries grouped by message, service, and level.

    This endpoint allows remote servers (e.g. dev querying prod) to fetch error
    summaries without direct OpenObserve access. Returns the same data as the
    equivalent --query-json invocation against /v1/admin/debug/logs/query with
    mode=count_by + group_by=[message, service, level] filtered by compose_project
    and level IN (ERROR, CRITICAL).

    Query params:
        since_minutes: Time window in minutes (default 1440 = 24h, max 10080 = 7d)
        top: Max error groups to return (default 15, max 100)
        compose_project: Docker Compose project name filter (default 'openmates-core')

    Security:
        - Requires admin API key
        - Only returns aggregated error counts, not raw log content
    """
    since_minutes = min(max(1, since_minutes), 10080)
    top = min(max(1, top), 100)

    # Sanitize compose_project to prevent SQL injection
    if not re.match(r'^[a-zA-Z0-9_-]+$', compose_project):
        raise HTTPException(status_code=400, detail="Invalid compose_project name")

    logger.info(
        f"Admin {admin_user.id} querying error logs "
        f"(since={since_minutes}m, top={top}, project={compose_project})"
    )

    sql = (
        f"SELECT message, service, level, COUNT(*) as count "
        f"FROM \"default\" "
        f"WHERE compose_project = '{compose_project}' "
        f"AND (level = 'ERROR' OR level = 'CRITICAL' "
        f"OR LOWER(message) LIKE '%traceback%') "
        f"GROUP BY message, service, level "
        f"ORDER BY count DESC "
        f"LIMIT {top}"
    )

    try:
        start_time = datetime.now(timezone.utc) - timedelta(minutes=since_minutes)
        hits = await openobserve_log_collector._search("default", sql, start_time=start_time)

        entries = []
        if hits:
            for hit in hits:
                entries.append(ErrorLogEntry(
                    message=str(hit.get("message", ""))[:500],
                    service=str(hit.get("service", "unknown")),
                    level=str(hit.get("level", "ERROR")),
                    count=int(hit.get("count", 1)),
                ))

        return ErrorLogsResponse(
            success=True,
            hits=entries,
            total=len(entries),
            since_minutes=since_minutes,
            generated_at=datetime.now(timezone.utc).isoformat(),
        )

    except Exception as e:
        logger.error(f"Error querying OpenObserve error logs: {e}", exc_info=True)
        raise HTTPException(
            status_code=500,
            detail=f"Failed to query error logs: {str(e)}",
        )


# ============================================================================
# STRUCTURED LOG QUERY (safe ad-hoc filtering)
# ============================================================================
#
# Endpoint: POST /v1/admin/debug/logs/query
#
# Purpose
# -------
# Ad-hoc log debugging against OpenObserve without letting callers submit raw SQL.
# Replaces the broken path where debug_logs.py --prod --sql was silently routed
# to a canned top-errors endpoint (ignoring the SQL string entirely).
#
# Security model
# --------------
# 1. Admin-only (require_admin_api_key) + 30/minute rate limit — same as the rest of admin_debug.
# 2. No user-provided SQL. The backend composes SQL server-side from a strict
#    Pydantic schema using only whitelisted identifiers (stream name, column names,
#    operators). User input only reaches SQL as escaped quoted literals or as
#    parseable numeric/timestamp values.
# 3. Stream whitelist: {default, client_console}. Audit/compliance streams are NOT
#    reachable from this endpoint.
# 4. Field whitelist per stream — attempts to query unknown fields fail validation.
# 5. Operator whitelist — only eq, neq, like, not_like, in, gt, gte, lt, lte. No
#    raw boolean logic, no subqueries, no CTEs, no UNION.
# 6. Value sanitization — strings reject control chars / backslashes / NUL; the
#    only quote handling is SQL-standard single-quote doubling. LIKE values may
#    contain % and _ as SQL wildcards (that's their purpose).
# 7. Forced LIMIT (cap 1000), forced time window (cap 7d = 10080 min), forced
#    ORDER BY safety, 30s backend timeout.
# 8. Every call is audit-logged at WARNING level with a distinctive
#    [ADMIN_LOG_QUERY] prefix: admin user id, stream, filter repr, row count,
#    duration. The log line can be grep-excluded from its own results.
#
# Not in scope / deliberately unsupported
# ---------------------------------------
# - JOINs, subqueries, CTEs, UNIONs (no real need for log debugging)
# - Arbitrary aggregate functions — only COUNT(*) via mode="count_by"
# - Writing logs — OpenObserve's _search endpoint is read-only anyway; defense
#   in depth comes from composing only SELECT ... FROM statements.
# ============================================================================


# --- Stream + field whitelists ------------------------------------------------
# Extend these carefully and only after reviewing what data the stream exposes.
# Fields listed here become queryable in both WHERE and SELECT/GROUP BY.
_LOG_QUERY_STREAM_FIELDS: Dict[str, frozenset[str]] = {
    "default": frozenset({
        "_timestamp", "message", "level", "service", "container",
        "compose_project", "job",
    }),
    "client_console": frozenset({
        "_timestamp", "message", "level", "device_type", "user_id",
        "user_email", "debugging_id", "page_url",
    }),
}

_LOG_QUERY_ALLOWED_OPS = frozenset({
    "eq", "neq", "like", "not_like", "in", "gt", "gte", "lt", "lte",
})

_LOG_QUERY_OP_TO_SQL = {
    "eq": "=", "neq": "!=",
    "like": "LIKE", "not_like": "NOT LIKE",
    "gt": ">", "gte": ">=", "lt": "<", "lte": "<=",
    # "in" is handled specially
}

# Absolute limits — never exceeded regardless of request values.
_LOG_QUERY_MAX_ROWS = 1000
_LOG_QUERY_MAX_SINCE_MINUTES = 10080  # 7 days
_LOG_QUERY_MAX_FILTERS = 15
_LOG_QUERY_MAX_VALUE_LEN = 500
_LOG_QUERY_MAX_IN_VALUES = 50


def _validate_log_query_value(value: Any, *, op: str) -> Union[str, int, float]:
    """Validate a single scalar value for use in a composed SQL literal.

    Rejects:
      - strings containing NUL, backslash, or control characters (other than tab/space)
      - strings longer than _LOG_QUERY_MAX_VALUE_LEN
      - non-scalar types other than str/int/float/bool (booleans are coerced to int)
      - NaN / Inf floats
    Returns the validated value unchanged (strings are returned raw; caller is
    responsible for SQL-escaping via _sql_escape_string when composing the SQL).
    """
    if isinstance(value, bool):
        # bool is a subclass of int in Python — normalize to int for consistent SQL
        return 1 if value else 0
    if isinstance(value, int):
        return value
    if isinstance(value, float):
        import math
        if math.isnan(value) or math.isinf(value):
            raise ValueError("numeric value must be finite")
        return value
    if isinstance(value, str):
        if len(value) > _LOG_QUERY_MAX_VALUE_LEN:
            raise ValueError(f"string value exceeds {_LOG_QUERY_MAX_VALUE_LEN} chars")
        if "\x00" in value:
            raise ValueError("string value contains NUL byte")
        if "\\" in value:
            raise ValueError("string value contains backslash (not allowed)")
        # Reject control characters except tab and newline (newline is legit in logs)
        for ch in value:
            if ord(ch) < 0x20 and ch not in ("\t", "\n"):
                raise ValueError(f"string value contains control char U+{ord(ch):04X}")
        return value
    raise ValueError(f"unsupported value type for op={op}: {type(value).__name__}")


def _sql_escape_string(value: str) -> str:
    """Escape a string for inclusion as a SQL quoted literal.

    Uses standard SQL single-quote doubling. Assumes the input has already been
    validated by _validate_log_query_value (no backslashes, no control chars, no NUL).
    The caller wraps the result in single quotes.
    """
    return value.replace("'", "''")


def _compose_log_query_sql(req: "LogQueryRequest") -> str:
    """Compose a fully-safe SELECT statement from a validated LogQueryRequest.

    All identifiers come from whitelists (stream, fields, operators). Values are
    interpolated either as numeric literals (int/float) or as SQL-escaped quoted
    strings. No user input ever becomes an identifier or an operator.
    """
    allowed_fields = _LOG_QUERY_STREAM_FIELDS[req.stream]

    # Build WHERE clause from structured filters
    where_clauses: List[str] = []
    for f in req.filters:
        if f.field not in allowed_fields:
            raise HTTPException(
                status_code=400,
                detail=f"field '{f.field}' not queryable on stream '{req.stream}'",
            )
        if f.op not in _LOG_QUERY_ALLOWED_OPS:
            raise HTTPException(status_code=400, detail=f"unsupported operator: {f.op}")

        if f.op == "in":
            if not isinstance(f.value, list):
                raise HTTPException(
                    status_code=400,
                    detail=f"op=in requires a list value on field '{f.field}'",
                )
            if len(f.value) == 0:
                raise HTTPException(
                    status_code=400,
                    detail=f"op=in requires at least one value on field '{f.field}'",
                )
            if len(f.value) > _LOG_QUERY_MAX_IN_VALUES:
                raise HTTPException(
                    status_code=400,
                    detail=f"op=in has too many values (max {_LOG_QUERY_MAX_IN_VALUES})",
                )
            rendered: List[str] = []
            for item in f.value:
                try:
                    v = _validate_log_query_value(item, op=f.op)
                except ValueError as e:
                    raise HTTPException(status_code=400, detail=f"field '{f.field}': {e}")
                if isinstance(v, str):
                    rendered.append(f"'{_sql_escape_string(v)}'")
                else:
                    rendered.append(str(v))
            where_clauses.append(f'"{f.field}" IN ({", ".join(rendered)})')
            continue

        # Scalar ops
        if isinstance(f.value, list):
            raise HTTPException(
                status_code=400,
                detail=f"op={f.op} requires a scalar value on field '{f.field}'",
            )
        try:
            v = _validate_log_query_value(f.value, op=f.op)
        except ValueError as e:
            raise HTTPException(status_code=400, detail=f"field '{f.field}': {e}")

        sql_op = _LOG_QUERY_OP_TO_SQL[f.op]
        if isinstance(v, str):
            where_clauses.append(f'"{f.field}" {sql_op} \'{_sql_escape_string(v)}\'')
        else:
            where_clauses.append(f'"{f.field}" {sql_op} {v}')

    # SELECT / GROUP BY / ORDER BY
    if req.mode == "select":
        # Per-stream defaults so callers don't have to specify select explicitly.
        # Kept minimal (3-4 fields) — callers needing more should pass select=[...].
        if req.select:
            select_cols = req.select
        elif req.stream == "default":
            select_cols = ["_timestamp", "message", "level", "service"]
        elif req.stream == "client_console":
            select_cols = ["_timestamp", "message", "level", "device_type"]
        else:
            # Defensive: should be unreachable thanks to the Literal stream type
            select_cols = ["_timestamp", "message", "level"]
        for col in select_cols:
            if col not in allowed_fields:
                raise HTTPException(
                    status_code=400,
                    detail=f"select column '{col}' not available on stream '{req.stream}'",
                )
        select_sql = ", ".join(f'"{c}"' for c in select_cols)

        order_col = req.order_by or "_timestamp"
        if order_col not in allowed_fields:
            raise HTTPException(
                status_code=400,
                detail=f"order_by column '{order_col}' not available on stream '{req.stream}'",
            )
        order_dir = "DESC" if req.order_dir == "desc" else "ASC"

        sql = f'SELECT {select_sql} FROM "{req.stream}"'
        if where_clauses:
            sql += " WHERE " + " AND ".join(where_clauses)
        sql += f' ORDER BY "{order_col}" {order_dir} LIMIT {req.limit}'
        return sql

    # mode == "count_by"
    if not req.group_by:
        raise HTTPException(
            status_code=400,
            detail="mode=count_by requires a non-empty group_by list",
        )
    for col in req.group_by:
        if col not in allowed_fields:
            raise HTTPException(
                status_code=400,
                detail=f"group_by column '{col}' not available on stream '{req.stream}'",
            )
    group_sql = ", ".join(f'"{c}"' for c in req.group_by)
    sql = (
        f'SELECT {group_sql}, COUNT(*) as count '
        f'FROM "{req.stream}"'
    )
    if where_clauses:
        sql += " WHERE " + " AND ".join(where_clauses)
    sql += f" GROUP BY {group_sql} ORDER BY count DESC LIMIT {req.limit}"
    return sql


class LogQueryFilter(BaseModel):
    """A single WHERE clause condition. All fields are whitelisted server-side."""
    field: str
    op: Literal["eq", "neq", "like", "not_like", "in", "gt", "gte", "lt", "lte"]
    # Accepts scalars for most ops and a list for op=in. Composition code
    # dispatches on op + isinstance.
    value: Union[str, int, float, bool, List[Union[str, int, float, bool]]]


class LogQueryRequest(BaseModel):
    """Structured log query — the ONLY way callers can run ad-hoc queries.

    No raw SQL fragment is ever accepted.  See the module-level section
    ``STRUCTURED LOG QUERY`` for the security rationale.
    """
    stream: Literal["default", "client_console"]
    mode: Literal["select", "count_by"] = "select"

    # mode="select" fields
    select: Optional[List[str]] = None
    order_by: Optional[str] = None
    order_dir: Literal["asc", "desc"] = "desc"

    # mode="count_by" fields
    group_by: Optional[List[str]] = None

    # Shared
    filters: List[LogQueryFilter] = []
    since_minutes: int = 60
    limit: int = 100


class LogQueryHit(BaseModel):
    """A single log query result row. Arbitrary columns depending on the query."""
    data: Dict[str, Any]


class LogQueryResponse(BaseModel):
    success: bool
    stream: str
    mode: str
    rows: List[Dict[str, Any]]
    total: int
    sql: str  # Returned for transparency — admins can see what was executed
    since_minutes: int
    duration_ms: int
    generated_at: str


@router.post("/logs/query", response_model=LogQueryResponse, include_in_schema=False)
@limiter.limit("30/minute")
async def structured_log_query(
    request: Request,
    body: LogQueryRequest,
    admin_user: User = Depends(require_admin_api_key),
) -> LogQueryResponse:
    """Run a structured, whitelisted log query against OpenObserve.

    The request body is fully schema-validated; SQL is composed server-side
    from whitelisted identifiers. See the STRUCTURED LOG QUERY section at the
    top of this file for the full security model and threat analysis.
    """
    # Clamp input ranges
    if body.limit < 1 or body.limit > _LOG_QUERY_MAX_ROWS:
        raise HTTPException(
            status_code=400,
            detail=f"limit must be between 1 and {_LOG_QUERY_MAX_ROWS}",
        )
    if body.since_minutes < 1 or body.since_minutes > _LOG_QUERY_MAX_SINCE_MINUTES:
        raise HTTPException(
            status_code=400,
            detail=f"since_minutes must be between 1 and {_LOG_QUERY_MAX_SINCE_MINUTES}",
        )
    if len(body.filters) > _LOG_QUERY_MAX_FILTERS:
        raise HTTPException(
            status_code=400,
            detail=f"too many filters (max {_LOG_QUERY_MAX_FILTERS})",
        )

    sql = _compose_log_query_sql(body)

    # Compact filter repr for the audit log (never includes raw user SQL; values
    # are logged so an auditor can reconstruct what was executed)
    filter_repr = "; ".join(
        f"{f.field} {f.op} {f.value!r}"[:160] for f in body.filters
    ) or "-"

    start_time = datetime.now(timezone.utc) - timedelta(minutes=body.since_minutes)
    t0 = time.time()
    try:
        hits = await openobserve_log_collector._search(
            body.stream, sql, start_time=start_time,
        )
    except Exception as e:
        duration_ms = int((time.time() - t0) * 1000)
        logger.warning(
            f"[ADMIN_LOG_QUERY] user={admin_user.id} stream={body.stream} "
            f"mode={body.mode} filters=[{filter_repr}] "
            f"rows=ERROR duration_ms={duration_ms} error={e!r}"
        )
        raise HTTPException(status_code=500, detail=f"OpenObserve query failed: {e}")

    duration_ms = int((time.time() - t0) * 1000)
    rows = hits or []

    # Audit log (WARNING level so it's visible in top-warnings-errors; the
    # [ADMIN_LOG_QUERY] prefix lets callers grep-exclude it from their own results)
    logger.warning(
        f"[ADMIN_LOG_QUERY] user={admin_user.id} stream={body.stream} "
        f"mode={body.mode} filters=[{filter_repr}] "
        f"rows={len(rows)} duration_ms={duration_ms}"
    )

    return LogQueryResponse(
        success=True,
        stream=body.stream,
        mode=body.mode,
        rows=rows,
        total=len(rows),
        sql=sql,
        since_minutes=body.since_minutes,
        duration_ms=duration_ms,
        generated_at=datetime.now(timezone.utc).isoformat(),
    )


# ============================================================================
# OPENOBSERVE DIAGNOSTICS
# ============================================================================


@router.get("/errors/health", include_in_schema=False)
@limiter.limit("30/minute")
async def openobserve_health(
    request: Request,
    admin_user: User = Depends(require_admin_api_key),
) -> Dict[str, Any]:
    """
    Diagnostic endpoint to check OpenObserve connectivity and data ingestion.

    Use this to remotely diagnose why error queries return empty on production
    without SSH access.  Returns whether OpenObserve is reachable, total record
    count (no filter), and the distinct compose_project values actually present.
    """
    logger.info(f"Admin {admin_user.id} running OpenObserve health check")

    result: Dict[str, Any] = {
        "reachable": False,
        "total_records": 0,
        "sample_compose_projects": [],
    }

    try:
        start_time = datetime.now(timezone.utc) - timedelta(hours=24)

        # Total records (no filter) to confirm data is being ingested
        count_sql = 'SELECT COUNT(*) as total FROM "default"'
        count_hits = await openobserve_log_collector._search(
            "default", count_sql, start_time=start_time,
        )
        result["reachable"] = True
        if count_hits:
            result["total_records"] = int(count_hits[0].get("total", 0))

        # Distinct compose_project values — reveals the actual project name on prod
        projects_sql = (
            'SELECT compose_project, COUNT(*) as count FROM "default" '
            'GROUP BY compose_project ORDER BY count DESC LIMIT 10'
        )
        proj_hits = await openobserve_log_collector._search(
            "default", projects_sql, start_time=start_time,
        )
        if proj_hits:
            result["sample_compose_projects"] = [
                {"name": h.get("compose_project", "?"), "count": int(h.get("count", 0))}
                for h in proj_hits
            ]

    except Exception as e:
        logger.error(f"OpenObserve health check failed: {e}", exc_info=True)
        result["error"] = str(e)

    result["generated_at"] = datetime.now(timezone.utc).isoformat()
    return result


# ============================================================================
# SERVER STATS (OPE-296)
# ============================================================================


def _safe_int(value: Any, default: int = 0) -> int:
    """Safely convert a Directus value (may be str, None, or int) to int."""
    if value is None:
        return default
    try:
        return int(value)
    except (ValueError, TypeError):
        return default


@router.get("/server-stats", include_in_schema=False)
@limiter.limit("30/minute")
async def get_server_stats(
    request: Request,
    admin_user: User = Depends(require_admin_api_key),
    directus_service: DirectusService = Depends(get_directus_service),
) -> Dict[str, Any]:
    """
    Query server stats from Directus for the daily meeting dashboard.

    Returns:
      - User growth (yesterday snapshot)
      - Engagement: 14-day daily trend (messages, embeds, chats) + all-time totals
      - Revenue: 14-day daily trend (income, purchases) + per-day unique buyers
        from invoices aggregation + lifetime unique buyers
      - AI usage (yesterday snapshot)
      - Web analytics, newsletter, data health
    """
    import json as _json

    today = datetime.now(timezone.utc)
    today_str = today.strftime("%Y-%m-%d")
    yesterday_str = (today - timedelta(days=1)).strftime("%Y-%m-%d")
    cutoff_14d = (today - timedelta(days=14)).strftime("%Y-%m-%d")

    logger.info(f"Admin {admin_user.id} querying server stats (14d trend ending {yesterday_str})")

    result: Dict[str, Any] = {"success": True, "date": yesterday_str, "sections": {}}

    # ── Authoritative Stripe Revenue ────────────────────────────────────
    # Directus server_stats_global_daily only contains app-side incremental
    # counters and may miss historical or previously-untracked payment paths.
    # Stripe balance transactions are the source of truth for gross EUR revenue.
    try:
        payment_service = getattr(request.app.state, "payment_service", None)
        stripe_provider = getattr(payment_service, "provider", None) if payment_service else None
        if stripe_provider:
            stripe_summary = await stripe_provider.get_stripe_revenue_summary_eur()
            result["sections"]["stripe_revenue"] = {
                "ytd_eur": stripe_summary.get("ytd_eur", 0.0),
                "all_time_eur": stripe_summary.get("all_time_eur", 0.0),
                "transactions": stripe_summary.get("transactions", 0),
                "monthly": stripe_summary.get("monthly", []),
                "source": "stripe_balance_transactions",
            }
        else:
            result["sections"]["stripe_revenue"] = {"error": "PaymentService unavailable"}
    except Exception as e:
        logger.error(f"Stripe revenue query failed: {e}", exc_info=True)
        result["sections"]["stripe_revenue"] = {"error": str(e)}

    # ── Server Stats — 14 day trend + yesterday snapshot ─────────────────
    try:
        trend_items = await directus_service.get_items(
            "server_stats_global_daily",
            {"sort": ["-date"], "limit": 14},
            admin_required=True,
        )
        # Oldest → newest for rendering
        trend_items = list(reversed(trend_items or []))
        stats = trend_items[-1] if trend_items else None

        if stats:
            result["sections"]["user_growth"] = {
                "total_users": stats.get("total_regular_users"),
                "new_registrations": _safe_int(stats.get("new_users_registered")),
                "completed_signups": _safe_int(stats.get("new_users_finished_signup")),
            }

            # 14-day engagement trend
            trend = [
                {
                    "date": it.get("date"),
                    "messages": _safe_int(it.get("messages_sent")),
                    "embeds": _safe_int(it.get("embeds_created")),
                    "chats": _safe_int(it.get("chats_created")),
                    "income_eur": _safe_int(it.get("income_eur_cents")) / 100.0,
                    "purchases": _safe_int(it.get("purchase_count")),
                    "credits_sold": _safe_int(it.get("credits_sold")),
                    "credits_used": _safe_int(it.get("credits_used")),
                }
                for it in trend_items
            ]

            result["sections"]["engagement"] = {
                "messages_sent": _safe_int(stats.get("messages_sent")),
                "chats_created": _safe_int(stats.get("chats_created")),
                "embeds_created": _safe_int(stats.get("embeds_created")),
                "trend_14d": trend,
            }
            income_cents = _safe_int(stats.get("income_eur_cents"))
            result["sections"]["revenue"] = {
                "income_eur": income_cents / 100.0,
                "credits_sold": _safe_int(stats.get("credits_sold")),
                "credits_used": _safe_int(stats.get("credits_used")),
                "purchases": _safe_int(stats.get("purchase_count")),
                "active_subscriptions": stats.get("active_subscriptions"),
                "subscription_creations": _safe_int(stats.get("subscription_creations")),
                "subscription_cancellations": _safe_int(stats.get("subscription_cancellations")),
                "credit_liability": stats.get("liability_total"),
                "trend_14d": trend,
            }
            result["sections"]["ai_usage"] = {
                "input_tokens": _safe_int(stats.get("total_input_tokens")),
                "output_tokens": _safe_int(stats.get("total_output_tokens")),
            }
        else:
            result["sections"]["server_stats"] = {"error": f"No data for {yesterday_str}"}
    except Exception as e:
        logger.error(f"Server stats query failed: {e}", exc_info=True)
        result["sections"]["server_stats"] = {"error": str(e)}

    # ── All-time totals (messages / chats / embeds) ──────────────────────
    totals: Dict[str, Any] = {}
    for coll in ("messages", "chats", "embeds"):
        try:
            url = f"{directus_service.base_url}/items/{coll}"
            resp = await directus_service._make_api_request(
                "GET", url, params={"limit": 1, "meta": "filter_count"}
            )
            if resp.status_code == 200:
                totals[coll] = _safe_int(resp.json().get("meta", {}).get("filter_count"))
            else:
                totals[coll] = None
        except Exception as e:
            logger.error(f"filter_count for {coll} failed: {e}")
            totals[coll] = None
    result["sections"]["totals"] = totals

    # ── Invoices: per-day unique buyers + lifetime buyers ────────────────
    # Directus aggregation — no user-supplied SQL, fully predefined.
    try:
        invoices_url = f"{directus_service.base_url}/items/invoices"

        # Per-day unique buyers (last 14 days, skip gift card redemptions)
        daily_params = [
            ("aggregate[countDistinct]", "user_id_hash"),
            ("aggregate[count]", "id"),
            ("groupBy[]", "year(date)"),
            ("groupBy[]", "month(date)"),
            ("groupBy[]", "day(date)"),
            ("filter[date][_gte]", cutoff_14d),
            ("filter[is_gift_card][_eq]", "false"),
            ("sort[]", "year(date)"),
            ("sort[]", "month(date)"),
            ("sort[]", "day(date)"),
            ("limit", "-1"),
        ]
        daily_resp = await directus_service._make_api_request(
            "GET", invoices_url, params=daily_params
        )
        buyers_by_day: Dict[str, Dict[str, int]] = {}
        if daily_resp.status_code == 200:
            for row in daily_resp.json().get("data", []) or []:
                y = row.get("date_year")
                m = row.get("date_month")
                d = row.get("date_day")
                if y is None or m is None or d is None:
                    continue
                key = f"{int(y):04d}-{int(m):02d}-{int(d):02d}"
                distinct = row.get("countDistinct") or {}
                count = row.get("count") or {}
                buyers_by_day[key] = {
                    "unique_buyers": _safe_int(distinct.get("user_id_hash")),
                    "invoices": _safe_int(count.get("id")),
                }

        # Lifetime unique buyers
        lifetime_params = [
            ("aggregate[countDistinct]", "user_id_hash"),
            ("filter[is_gift_card][_eq]", "false"),
        ]
        lifetime_resp = await directus_service._make_api_request(
            "GET", invoices_url, params=lifetime_params
        )
        lifetime_buyers = 0
        if lifetime_resp.status_code == 200:
            rows = lifetime_resp.json().get("data", []) or []
            if rows:
                lifetime_buyers = _safe_int((rows[0].get("countDistinct") or {}).get("user_id_hash"))

        # Total invoices + refund split
        total_invoices = 0
        paid_invoices = 0
        try:
            r = await directus_service._make_api_request(
                "GET", invoices_url,
                params={"limit": 1, "meta": "filter_count", "filter[is_gift_card][_eq]": "false"},
            )
            if r.status_code == 200:
                total_invoices = _safe_int(r.json().get("meta", {}).get("filter_count"))
            r2 = await directus_service._make_api_request(
                "GET", invoices_url,
                params={
                    "limit": 1, "meta": "filter_count",
                    "filter[is_gift_card][_eq]": "false",
                    "filter[refund_status][_eq]": "none",
                    "filter[has_chargeback][_eq]": "false",
                },
            )
            if r2.status_code == 200:
                paid_invoices = _safe_int(r2.json().get("meta", {}).get("filter_count"))
        except Exception as e:
            logger.error(f"invoices total/paid query failed: {e}")

        # Merge per-day buyers into the revenue trend
        if "revenue" in result["sections"] and isinstance(result["sections"]["revenue"].get("trend_14d"), list):
            for entry in result["sections"]["revenue"]["trend_14d"]:
                d = entry.get("date")
                bd = buyers_by_day.get(d, {})
                entry["unique_buyers"] = bd.get("unique_buyers", 0)
                entry["invoice_count"] = bd.get("invoices", 0)

        result["sections"]["invoices"] = {
            "lifetime_unique_buyers": lifetime_buyers,
            "total_invoices": total_invoices,
            "paid_invoices": paid_invoices,
            "refunded_or_chargeback": max(0, total_invoices - paid_invoices),
        }
    except Exception as e:
        logger.error(f"Invoices aggregation failed: {e}", exc_info=True)
        result["sections"]["invoices"] = {"error": str(e)}

    # ── Lifetime Revenue + Monthly Cohort ──────────────────────────────
    try:
        # Sum all daily income_eur_cents for lifetime total
        all_daily = await directus_service.get_items(
            "server_stats_global_daily",
            {
                "fields": ["income_eur_cents", "purchase_count", "new_users_finished_signup"],
                "limit": -1,
            },
            admin_required=True,
        )
        lifetime_income_cents = sum(_safe_int(d.get("income_eur_cents")) for d in (all_daily or []))
        lifetime_purchases = sum(_safe_int(d.get("purchase_count")) for d in (all_daily or []))

        # Monthly breakdown from server_stats_global_monthly
        monthly_items = await directus_service.get_items(
            "server_stats_global_monthly",
            {
                "fields": [
                    "year_month", "income_eur_cents", "purchase_count",
                    "new_users_finished_signup", "credits_sold", "credits_used",
                    "total_regular_users",
                ],
                "sort": ["year_month"],
                "limit": -1,
            },
            admin_required=True,
        )
        monthly_trend = [
            {
                "month": m.get("year_month"),
                "income_eur": _safe_int(m.get("income_eur_cents")) / 100.0,
                "purchases": _safe_int(m.get("purchase_count")),
                "new_paying_users": _safe_int(m.get("new_users_finished_signup")),
                "credits_sold": _safe_int(m.get("credits_sold")),
                "credits_used": _safe_int(m.get("credits_used")),
                "total_users": _safe_int(m.get("total_regular_users")),
            }
            for m in (monthly_items or [])
        ]

        result["sections"]["lifetime_revenue"] = {
            "total_eur": lifetime_income_cents / 100.0,
            "total_purchases": lifetime_purchases,
            "monthly_trend": monthly_trend,
        }
    except Exception as e:
        logger.error(f"Lifetime revenue query failed: {e}", exc_info=True)
        result["sections"]["lifetime_revenue"] = {"error": str(e)}

    # ── Web Analytics (yesterday) ────────────────────────────────────────
    try:
        wa_items = await directus_service.get_items(
            "web_analytics_daily",
            {"filter": {"date": {"_eq": yesterday_str}}, "limit": 1},
            admin_required=True,
        )
        wa = wa_items[0] if wa_items else None
        if wa:
            countries_raw = wa.get("countries")
            if isinstance(countries_raw, str):
                try:
                    countries_raw = _json.loads(countries_raw)
                except Exception:
                    countries_raw = {}
            devices_raw = wa.get("devices")
            if isinstance(devices_raw, str):
                try:
                    devices_raw = _json.loads(devices_raw)
                except Exception:
                    devices_raw = {}
            result["sections"]["web_analytics"] = {
                "page_loads": wa.get("page_loads", 0),
                "unique_visits": wa.get("unique_visits_approx", 0),
                "countries": countries_raw or {},
                "devices": devices_raw or {},
            }
    except Exception as e:
        logger.error(f"Web analytics query failed: {e}", exc_info=True)
        result["sections"]["web_analytics"] = {"error": str(e)}

    # ── Data Health ──────────────────────────────────────────────────────
    try:
        today_items = await directus_service.get_items(
            "daily_inspiration_defaults",
            {"filter": {"date": {"_eq": today_str}}, "fields": ["id"], "limit": 100},
            admin_required=True,
        )
        all_items = await directus_service.get_items(
            "daily_inspiration_defaults",
            {"fields": ["id"], "limit": 500},
            admin_required=True,
        )
        result["sections"]["data_health"] = {
            "daily_inspiration_today": len(today_items) if today_items else 0,
            "daily_inspiration_total": len(all_items) if all_items else 0,
        }
    except Exception as e:
        logger.error(f"Data health query failed: {e}", exc_info=True)
        result["sections"]["data_health"] = {"error": str(e)}

    # ── Newsletter Subscribers ──────────────────────────────────────────
    try:
        from backend.core.api.app.routes.newsletter import get_newsletter_subscriber_breakdown

        result["sections"]["newsletter"] = await get_newsletter_subscriber_breakdown(directus_service)
    except Exception as e:
        logger.error(f"Newsletter stats query failed: {e}", exc_info=True)
        result["sections"]["newsletter"] = {"error": str(e)}

    result["generated_at"] = datetime.now(timezone.utc).isoformat()
    return result


# ============================================================================
# DAILY INSPIRATION AUDIT
# ============================================================================


@router.get("/inspiration-audit", include_in_schema=False)
@limiter.limit("30/minute")
async def get_inspiration_audit(
    request: Request,
    include_defaults: bool = True,
    admin_user: User = Depends(require_admin_api_key),
    directus_service: DirectusService = Depends(get_directus_service),
) -> Dict[str, Any]:
    """
    Run the daily inspiration keyword audit against this server's Directus.

    Returns pool + defaults entries with pass/reject verdicts so the
    daily-meeting script can audit prod inspirations remotely (mirrors
    audit_inspiration_pool.py running locally).
    """
    from backend.apps.ai.daily_inspiration.content_filter import check_entry

    logger.info(f"Admin {admin_user.id} running inspiration audit (include_defaults={include_defaults})")

    async def audit_collection(collection: str) -> List[Dict[str, Any]]:
        sort_key = "-generated_at" if collection == "daily_inspiration_pool" else "-date"
        items = await directus_service.get_items(
            collection,
            {"sort": [sort_key], "limit": 200},
            admin_required=True,
        )
        if not items:
            return []
        return [check_entry(entry) for entry in items]

    result: Dict[str, Any] = {"success": True, "sections": {}}
    try:
        pool_results = await audit_collection("daily_inspiration_pool")
        result["sections"]["pool"] = {
            "total": len(pool_results),
            "pass": len([r for r in pool_results if r["verdict"] == "PASS"]),
            "reject": len([r for r in pool_results if r["verdict"] == "REJECT"]),
            "results": pool_results,
        }
    except Exception as e:
        logger.error(f"Pool audit failed: {e}", exc_info=True)
        result["sections"]["pool"] = {"error": str(e)}

    if include_defaults:
        try:
            defaults_results = await audit_collection("daily_inspiration_defaults")
            result["sections"]["defaults"] = {
                "total": len(defaults_results),
                "pass": len([r for r in defaults_results if r["verdict"] == "PASS"]),
                "reject": len([r for r in defaults_results if r["verdict"] == "REJECT"]),
                "results": defaults_results,
            }
        except Exception as e:
            logger.error(f"Defaults audit failed: {e}", exc_info=True)
            result["sections"]["defaults"] = {"error": str(e)}

    result["generated_at"] = datetime.now(timezone.utc).isoformat()
    return result


# ============================================================================
# OPENOBSERVE PROXY ENDPOINTS
# ============================================================================
# These endpoints proxy raw SQL and trace queries to the local OpenObserve
# instance, allowing remote debug scripts to query O2 without needing direct
# credentials. This eliminates the need for OPENOBSERVE_PROD_* env vars.


class O2SearchResponse(BaseModel):
    """Response from OpenObserve SQL search proxy."""
    success: bool
    hits: List[Dict[str, Any]]
    total: int
    took_ms: int
    generated_at: str


@router.get("/o2/search", response_model=O2SearchResponse, include_in_schema=False)
@limiter.limit("300/minute")
async def o2_search(
    request: Request,
    sql: str,
    since_minutes: int = 60,
    stream_type: str = "logs",
    admin_user: User = Depends(require_admin_api_key),
) -> O2SearchResponse:
    """
    Proxy SQL queries to the local OpenObserve instance.

    Args:
        sql: SQL query (must include FROM clause referencing the stream)
        since_minutes: Time window in minutes (1-10080, default 60)
        stream_type: "logs" or "traces" (maps to ?type= query param)
    """
    import aiohttp

    since_minutes = max(1, min(since_minutes, 10080))
    if stream_type not in ("logs", "traces"):
        raise HTTPException(status_code=400, detail="stream_type must be 'logs' or 'traces'")

    # Sanitize: no semicolons, no destructive statements
    sql_clean = sql.strip().rstrip(";")
    sql_upper = sql_clean.upper()
    for forbidden in ("DROP ", "DELETE ", "INSERT ", "UPDATE ", "ALTER ", "CREATE "):
        if forbidden in sql_upper:
            raise HTTPException(status_code=400, detail=f"Forbidden SQL operation: {forbidden.strip()}")

    if " LIMIT " not in sql_upper:
        sql_clean = f"{sql_clean} LIMIT 2000"

    start_time = datetime.now(timezone.utc) - timedelta(minutes=since_minutes)
    end_time = datetime.now(timezone.utc)
    start_us = int(start_time.timestamp() * 1_000_000)
    end_us = int(end_time.timestamp() * 1_000_000)

    email = os.getenv("OPENOBSERVE_ROOT_EMAIL", "")
    password = os.getenv("OPENOBSERVE_ROOT_PASSWORD", "")
    url = "http://openobserve:5080/api/default/_search"
    if stream_type == "traces":
        url += "?type=traces"

    body = {"query": {"sql": sql_clean, "start_time": start_us, "end_time": end_us}}

    try:
        timeout = aiohttp.ClientTimeout(total=30)
        async with aiohttp.ClientSession(timeout=timeout) as session:
            async with session.post(url, json=body, auth=aiohttp.BasicAuth(email, password)) as resp:
                if resp.status == 200:
                    data = await resp.json()
                    return O2SearchResponse(
                        success=True,
                        hits=data.get("hits", []),
                        total=data.get("total", 0),
                        took_ms=data.get("took", 0),
                        generated_at=datetime.now(timezone.utc).isoformat(),
                    )
                error_text = await resp.text()
                logger.warning(f"O2 search proxy failed ({resp.status}): {error_text[:300]}")
                raise HTTPException(status_code=502, detail=f"OpenObserve returned {resp.status}: {error_text[:200]}")
    except aiohttp.ClientError as exc:
        logger.error(f"O2 search proxy connection error: {exc}")
        raise HTTPException(status_code=502, detail=f"Cannot connect to OpenObserve: {exc}")


class O2TracesLatestResponse(BaseModel):
    """Response from OpenObserve traces/latest proxy."""
    success: bool
    hits: List[Dict[str, Any]]
    total: int
    generated_at: str


@router.get("/o2/traces/latest", response_model=O2TracesLatestResponse, include_in_schema=False)
@limiter.limit("30/minute")
async def o2_traces_latest(
    request: Request,
    since_minutes: int = 60,
    size: int = 50,
    filter: str = "",
    admin_user: User = Depends(require_admin_api_key),
) -> O2TracesLatestResponse:
    """
    Proxy trace summary queries to the local OpenObserve instance.

    Returns trace-level summaries (not individual spans). Use /o2/search
    with stream_type=traces for detailed span queries.
    """
    import aiohttp
    from urllib.parse import quote

    since_minutes = max(1, min(since_minutes, 10080))
    size = max(1, min(size, 500))

    start_time = datetime.now(timezone.utc) - timedelta(minutes=since_minutes)
    end_time = datetime.now(timezone.utc)
    start_us = int(start_time.timestamp() * 1_000_000)
    end_us = int(end_time.timestamp() * 1_000_000)

    email = os.getenv("OPENOBSERVE_ROOT_EMAIL", "")
    password = os.getenv("OPENOBSERVE_ROOT_PASSWORD", "")
    url = (
        f"http://openobserve:5080/api/default/default/traces/latest"
        f"?start_time={start_us}&end_time={end_us}"
        f"&from=0&size={size}&filter={quote(filter)}"
    )

    try:
        timeout = aiohttp.ClientTimeout(total=30)
        async with aiohttp.ClientSession(timeout=timeout) as session:
            async with session.get(url, auth=aiohttp.BasicAuth(email, password)) as resp:
                if resp.status == 200:
                    data = await resp.json()
                    return O2TracesLatestResponse(
                        success=True,
                        hits=data.get("hits", []),
                        total=data.get("total", 0),
                        generated_at=datetime.now(timezone.utc).isoformat(),
                    )
                error_text = await resp.text()
                logger.warning(f"O2 traces/latest proxy failed ({resp.status}): {error_text[:300]}")
                raise HTTPException(status_code=502, detail=f"OpenObserve returned {resp.status}: {error_text[:200]}")
    except aiohttp.ClientError as exc:
        logger.error(f"O2 traces/latest proxy connection error: {exc}")
        raise HTTPException(status_code=502, detail=f"Cannot connect to OpenObserve: {exc}")


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
            "fields": "id,encrypted_email_address,hashed_email,confirmed_at,subscribed_at,language,darkmode,unsubscribe_token,user_registration_status",
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

        # 2. Language, darkmode, and registration status breakdown
        lang_breakdown: Dict[str, int] = defaultdict(int)
        darkmode_count = 0
        reg_status_counts: Dict[str, int] = {
            "not_signed_up": 0,
            "signup_incomplete": 0,
            "signup_complete": 0,
            "unknown": 0,
        }
        for sub in subscribers:
            lang = sub.get("language", "unknown")
            lang_breakdown[lang] += 1
            if sub.get("darkmode"):
                darkmode_count += 1
            # Tally registration status
            reg_status = sub.get("user_registration_status")
            if reg_status in reg_status_counts:
                reg_status_counts[reg_status] += 1
            else:
                reg_status_counts["unknown"] += 1

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
            "registration_status": reg_status_counts,
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
                    "user_registration_status": sub.get("user_registration_status"),
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
