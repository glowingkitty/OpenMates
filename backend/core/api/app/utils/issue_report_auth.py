"""Authentication helpers for durable issue-report diagnostics."""

from typing import Any, Optional

from backend.core.api.app.services.cache_user_mixin import canonical_session_user_id
from backend.core.api.app.utils.ws_token import verify_ws_token


async def resolve_issue_report_user_id(
    current_user_id: Optional[str],
    ws_token: Optional[str],
    cache_service: Any,
) -> Optional[str]:
    """Resolve cookie auth or the short-lived Safari WebSocket token."""
    if current_user_id:
        return current_user_id

    token_hash = verify_ws_token(ws_token) if ws_token else None
    if not token_hash:
        return None

    session_data = await cache_service.get(
        f"{cache_service.SESSION_KEY_PREFIX}{token_hash}"
    )
    return canonical_session_user_id(session_data)
