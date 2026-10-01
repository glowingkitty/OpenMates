"""Read-only, authenticated runtime checks on the private service network."""

from fastapi import APIRouter, Request

from backend.core.api.app.services.limiter import limiter
from backend.core.api.app.utils.internal_auth import VerifiedInternalRequest


# Internal-only: shared service token; no owner data, paid work or credit usage.
# The public Caddy allowlist does not expose /internal. Normal internal-service
# request limit is 60/minute per service address; the check only reads memory.
router = APIRouter(prefix="/internal/health", dependencies=[VerifiedInternalRequest])


@router.get("/payments", include_in_schema=False)
@limiter.limit("60/minute")
async def payment_routes_health(request: Request) -> dict[str, bool]:
    registered = {
        (getattr(route, "path", None), method)
        for route in request.app.routes
        for method in getattr(route, "methods", ()) or ()
    }
    required = {("/v1/payments/webhook", "POST"), ("/v1/payments/subscription", "GET")}
    return {"routes_registered": required <= registered}
