# backend/core/api/app/routes/connected_account_setup.py
#
# Public connected-account setup metadata for first-party clients.
# Revolut Business requires users to whitelist the OpenMates server egress IP
# before account reads work. This route exposes only that public IP metadata;
# it does not expose tokens, account data, or encrypted connected-account rows.
#
# Spec: docs/specs/finance-check-accounts-v1/spec.yml

from __future__ import annotations

import ipaddress
import os

import httpx
from fastapi import APIRouter, HTTPException, Request
from pydantic import BaseModel, Field

from backend.core.api.app.services.limiter import limiter


router = APIRouter(prefix="/v1/connected-accounts/setup", tags=["Connected Account Setup"])

REVOLUT_BUSINESS_EGRESS_IP_ENV = "REVOLUT_BUSINESS_SERVER_EGRESS_IPS"
PUBLIC_IP_DETECTION_URL = "https://api.ipify.org?format=json"
PUBLIC_IP_DETECTION_TIMEOUT_SECONDS = 4.0


class ServerEgressIpResponse(BaseModel):
    provider_id: str = Field(default="revolut_business")
    ip_addresses: list[str]
    source: str
    revolut_field: str = Field(default="Production IP whitelist")
    instructions: str


@router.get("/revolut-business/server-egress-ip", response_model=ServerEgressIpResponse)
@limiter.limit("20/minute")
async def get_revolut_business_server_egress_ip(request: Request) -> ServerEgressIpResponse:
    """Return the public OpenMates server IP(s) Revolut Business must whitelist."""

    configured_ips = _parse_public_ip_list(os.getenv(REVOLUT_BUSINESS_EGRESS_IP_ENV, ""))
    if configured_ips:
        return _response(ip_addresses=configured_ips, source="configured")

    detected_ip = await _detect_public_egress_ip()
    return _response(ip_addresses=[detected_ip], source="detected")


def _response(*, ip_addresses: list[str], source: str) -> ServerEgressIpResponse:
    return ServerEgressIpResponse(
        ip_addresses=ip_addresses,
        source=source,
        instructions=(
            "Add these public OpenMates server egress IPs to the Revolut Business "
            "API certificate Production IP whitelist. Revolut will reject account "
            "reads with 403 until the server IP is whitelisted."
        ),
    )


def _parse_public_ip_list(raw_value: str) -> list[str]:
    ips: list[str] = []
    for part in raw_value.replace(";", ",").split(","):
        value = part.strip()
        if not value:
            continue
        if _is_public_ip(value):
            ips.append(value)
    return sorted(set(ips))


async def _detect_public_egress_ip() -> str:
    try:
        async with httpx.AsyncClient(timeout=PUBLIC_IP_DETECTION_TIMEOUT_SECONDS) as client:
            response = await client.get(PUBLIC_IP_DETECTION_URL)
            response.raise_for_status()
            payload = response.json()
    except (httpx.HTTPError, ValueError) as exc:
        raise HTTPException(status_code=503, detail="Unable to detect server egress IP") from exc

    ip_value = str(payload.get("ip") or "").strip()
    if not _is_public_ip(ip_value):
        raise HTTPException(status_code=503, detail="Detected server egress IP is not public")
    return ip_value


def _is_public_ip(value: str) -> bool:
    try:
        ip = ipaddress.ip_address(value)
    except ValueError:
        return False
    return bool(ip.is_global)
