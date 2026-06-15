# backend/shared/providers/google_calendar/oauth.py
#
# Google OAuth token exchange helper for connected Calendar accounts.
# This module exchanges refresh tokens only when the permission/token brokers have
# authorized an exact active-turn account/action scope.
#
# Spec: docs/specs/calendar-permission-management/spec.yml

from __future__ import annotations

import os
from typing import Any

import httpx

GOOGLE_OAUTH_TOKEN_URL = "https://oauth2.googleapis.com/token"
TOKEN_EXCHANGE_TIMEOUT_SECONDS = 15.0


async def exchange_google_refresh_token(
    refresh_token: str,
    scope_context: dict[str, Any],
) -> dict[str, Any]:
    """Exchange a Google refresh token for a short-lived access token."""

    client_id = os.getenv("GOOGLE_CALENDAR_CLIENT_ID") or os.getenv("GOOGLE_OAUTH_CLIENT_ID")
    client_secret = os.getenv("GOOGLE_CALENDAR_CLIENT_SECRET") or os.getenv("GOOGLE_OAUTH_CLIENT_SECRET")
    if not client_id or not client_secret:
        raise RuntimeError("Google OAuth client credentials are not configured")

    async with httpx.AsyncClient(timeout=TOKEN_EXCHANGE_TIMEOUT_SECONDS) as client:
        response = await client.post(
            GOOGLE_OAUTH_TOKEN_URL,
            data={
                "client_id": client_id,
                "client_secret": client_secret,
                "refresh_token": refresh_token,
                "grant_type": "refresh_token",
            },
        )
        response.raise_for_status()
        payload = response.json()

    result: dict[str, Any] = {"access_token": payload.get("access_token")}
    if payload.get("expires_in") is not None:
        result["expires_in"] = payload["expires_in"]
    if payload.get("refresh_token"):
        result["rotated_refresh_token_bundle"] = {
            "provider": "google",
            "refresh_token": payload["refresh_token"],
            "scope_context": scope_context,
        }
    return result
