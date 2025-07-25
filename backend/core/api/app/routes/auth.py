from fastapi import APIRouter
import logging
from backend.core.api.app.routes.auth_routes.auth_invite import router as invite_router
from backend.core.api.app.routes.auth_routes.auth_email import router as email_router
from backend.core.api.app.routes.auth_routes.auth_login import router as login_router
from backend.core.api.app.routes.auth_routes.auth_logout import router as logout_router
from backend.core.api.app.routes.auth_routes.auth_session import router as session_router
from backend.core.api.app.routes.auth_routes.auth_password import router as password_router
# Import new refactored 2FA routers
from backend.core.api.app.routes.auth_routes.auth_2fa_setup import router as twofa_setup_router
from backend.core.api.app.routes.auth_routes.auth_2fa_verify import router as twofa_verify_router
# Import gift router
from backend.core.api.app.routes.auth_routes.auth_gift import router as gift_router
# Import recovery key router
from backend.core.api.app.routes.auth_routes.auth_recoverykey import router as recoverykey_router

# IMPORTANT INSTRUCTION START (DO NOT DELETE/MODIFY)
#
# LOGGING PRIVACY RULES
# 1. NEVER LOG SENSITIVE USER DATA under normal circumstances:
#    - IP addresses
#    - User IDs
#    - Email addresses
#    - Names
#    - Usernames
#    - Passwords
#
# 2. COMPLIANCE EXCEPTION: For EU/Germany legal requirements, the following events:
#    - Successful/failed login
#    - Signup
#    - Consent to terms
#    - Password change
#    - Email address change
#    - 2FA change
#    - Account deletion
#
# 3. FOR COMPLIANCE LOGS ONLY, record:
#    - IP address
#    - User ID
#    - Action type
#    - Timestamp
#
# 4. RETENTION & STORAGE:
#    - PRIMARY STORAGE: Compliance logs remain in Grafana for 48 hours
#    - BACKUP PROCEDURE: After 48 hours, logs are automatically:
#        a) Encrypted and transferred to Hetzner S3
#        b) Deleted from Grafana
#    - LONG-TERM RETENTION: Encrypted logs in Hetzner S3 are permanently deleted after 1 year
#    - ACCESS CONTROLS: Only authorized security personnel may access archived logs
#    - DOCUMENTATION: All automatic transfers and deletions must be logged in a separate audit system
#
# IMPORTANT INSTRUCTION END (DO NOT DELETE/MODIFY)

router = APIRouter(
    prefix="/v1/auth",
    tags=["Authentication"]
)

logger = logging.getLogger(__name__)
event_logger = logging.getLogger("app.events")

# Include all auth-related routers
router.include_router(invite_router)
router.include_router(email_router)
router.include_router(password_router)
router.include_router(login_router)
router.include_router(logout_router)
router.include_router(session_router)
# Include new refactored 2FA routers
router.include_router(twofa_setup_router)
router.include_router(twofa_verify_router)
# Include gift router
router.include_router(gift_router)
# Include recovery key router
router.include_router(recoverykey_router)