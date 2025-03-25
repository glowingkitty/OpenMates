from fastapi import APIRouter
import logging
from app.routes.auth_routes.auth_invite import router as invite_router
from app.routes.auth_routes.auth_email import router as email_router
from app.routes.auth_routes.auth_login import router as login_router
from app.routes.auth_routes.auth_logout import router as logout_router
from app.routes.auth_routes.auth_session import router as session_router
from app.routes.auth_routes.auth_2fa import router as twofa_router

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

# Ensure the logger is configured to show INFO logs
logger.setLevel(logging.INFO)

# Include all auth-related routers
router.include_router(invite_router)
router.include_router(email_router)
router.include_router(login_router)
router.include_router(logout_router)
router.include_router(session_router)
router.include_router(twofa_router)