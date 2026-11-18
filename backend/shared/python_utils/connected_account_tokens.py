# backend/shared/python_utils/connected_account_tokens.py
#
# Generic helpers for skills that run with broker-issued connected-account
# access tokens, independent of any one provider.
#
# Spec: specifications/features/app-skills/design-figma/specification.yml

from __future__ import annotations

from typing import Any


def access_token_for_handle(
    access_token_handle: str, connected_account_access_tokens: dict[str, str] | None,
) -> str:
    """The skill only runs with a token the broker issued for this exact call."""

    if not connected_account_access_tokens:
        raise PermissionError("connected account access token context is required")
    access_token = connected_account_access_tokens.get(access_token_handle)
    if not access_token:
        raise PermissionError("access_token_handle is not authorized for this skill call")
    return access_token


def summarize_errors(results: list[dict[str, Any]]) -> str | None:
    """Top-level error only when every request failed, naming the first code."""

    if results and all(result.get("error") for result in results):
        return str(results[0]["error"])
    return None
