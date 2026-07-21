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
from fastapi import APIRouter, Depends, HTTPException, Request, Response
from pydantic import BaseModel, Field

from backend.core.api.app.models.user import User
from backend.core.api.app.routes.auth_routes.auth_dependencies import get_current_user as get_authenticated_user
from backend.core.api.app.services.limiter import limiter
from backend.shared.providers.revolut_business.client import (
    REVOLUT_BUSINESS_API_BASE_URL,
    REVOLUT_BUSINESS_SANDBOX_API_BASE_URL,
    RevolutBusinessClient,
)
from backend.shared.providers.revolut_business.oauth import (
    RevolutBusinessTokenExchangeError,
    exchange_revolut_business_authorization_code,
)


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


class RevolutBusinessExchangeCodeRequest(BaseModel):
    client_id: str
    code: str
    private_key_pem: str
    environment: str = Field(default="sandbox", pattern="^(sandbox|production)$")
    redirect_uri: str | None = None


class RevolutBusinessExchangeCodeResponse(BaseModel):
    provider_id: str = "revolut_business"
    app_id: str = "finance"
    environment: str
    refresh_token_bundle: dict[str, object]
    account_hint: dict[str, object]


async def get_current_user(request: Request, response: Response) -> User:
    return await get_authenticated_user(
        directus_service=request.app.state.directus_service,
        cache_service=request.app.state.cache_service,
        refresh_token=request.cookies.get("auth_refresh_token"),
        response=response,
        request=request,
    )


@router.get("/revolut-business/server-egress-ip", response_model=ServerEgressIpResponse)
@limiter.limit("20/minute")
async def get_revolut_business_server_egress_ip(request: Request) -> ServerEgressIpResponse:
    """Return the public OpenMates server IP(s) Revolut Business must whitelist."""

    configured_ips = _parse_public_ip_list(os.getenv(REVOLUT_BUSINESS_EGRESS_IP_ENV, ""))
    if configured_ips:
        return _response(ip_addresses=configured_ips, source="configured")

    detected_ip = await _detect_public_egress_ip()
    return _response(ip_addresses=[detected_ip], source="detected")


@router.post("/revolut-business/exchange-code", response_model=RevolutBusinessExchangeCodeResponse)
@limiter.limit("10/minute")
async def exchange_revolut_business_setup_code(
    request: Request,
    body: RevolutBusinessExchangeCodeRequest,
    current_user: User = Depends(get_current_user),
) -> RevolutBusinessExchangeCodeResponse:
    """Exchange a Revolut setup code for a client-encryptable token bundle."""

    del current_user
    try:
        token = await exchange_revolut_business_authorization_code(
            client_id=body.client_id,
            code_or_redirect_url=body.code,
            private_key_pem=body.private_key_pem,
            environment=body.environment,
            redirect_uri=body.redirect_uri,
        )
        access_token = str(token.get("access_token") or "")
        if not access_token:
            raise RevolutBusinessTokenExchangeError("Revolut token response did not include an access token")
        client = RevolutBusinessClient(
            access_token=access_token,
            base_url=REVOLUT_BUSINESS_SANDBOX_API_BASE_URL if body.environment == "sandbox" else REVOLUT_BUSINESS_API_BASE_URL,
        )
        accounts = await client.list_accounts()
    except RevolutBusinessTokenExchangeError as exc:
        raise HTTPException(status_code=502, detail=str(exc)) from exc
    except Exception as exc:
        raise HTTPException(status_code=502, detail="Revolut Business account validation failed") from exc

    account = accounts[0] if accounts else None
    refresh_token_bundle: dict[str, object] = {
        "provider": "revolut_business",
        "environment": body.environment,
        "client_id": body.client_id,
        "redirect_uri": body.redirect_uri,
        "private_key_pem": body.private_key_pem,
        "refresh_token": token["refresh_token"],
        "scopes": ["read"],
    }
    account_hint: dict[str, object] = {
        "label": account.name if account else "Revolut Business",
        "account_ref": account.id if account else "revolut_business",
        "account_count": len(accounts),
    }
    return RevolutBusinessExchangeCodeResponse(
        environment=body.environment,
        refresh_token_bundle=refresh_token_bundle,
        account_hint=account_hint,
    )


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
