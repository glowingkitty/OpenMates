"""API key scope, budget, and device authorization contracts.

Purpose: lock the SDK V1 permission model before backend implementation.
Architecture: docs/specs/sdk-packages-v1/spec.yml and developer settings.
Security: tests assert deny-by-scope and deny-by-budget behavior server-side.
Run: python3 -m pytest backend/tests/test_api_key_scopes.py
"""

import pytest

from backend.core.api.app.services.api_key_authorization import (
    ApiKeyBudgetError,
    ApiKeyScopeError,
    ApiKeyAuthorizationService,
)


def test_full_access_default_allows_chat_and_any_skill():
    service = ApiKeyAuthorizationService()
    metadata = service.normalize_metadata({})

    service.require_chat_scope(metadata, "chat:read_existing")
    service.require_chat_scope(metadata, "chat:create_incognito")
    service.require_app_skill_scope(metadata, "web", "search")
    service.require_app_skill_scope(metadata, "images", "generate")


def test_app_skill_scope_can_allow_one_skill_only():
    service = ApiKeyAuthorizationService()
    metadata = service.normalize_metadata(
        {
            "full_access": False,
            "scopes": {
                "apps": {
                    "mode": "selected",
                    "allowed_skills": ["web:search"],
                }
            },
        }
    )

    service.require_app_skill_scope(metadata, "web", "search")
    with pytest.raises(ApiKeyScopeError) as exc:
        service.require_app_skill_scope(metadata, "web", "browse")
    assert exc.value.missing_scope == "skill:web:browse"


def test_chat_scopes_are_enforced_independently():
    service = ApiKeyAuthorizationService()
    metadata = service.normalize_metadata(
        {
            "full_access": False,
            "scopes": {
                "chat": ["chat:create_incognito", "chat:create_saved"],
            },
        }
    )

    service.require_chat_scope(metadata, "chat:create_incognito")
    service.require_chat_scope(metadata, "chat:create_saved")
    with pytest.raises(ApiKeyScopeError) as exc:
        service.require_chat_scope(metadata, "chat:read_existing")
    assert exc.value.missing_scope == "chat:read_existing"


@pytest.mark.parametrize(
    "limit",
    [
        {"period": "daily", "credits": 100},
        {"period": "weekly", "credits": 100},
        {"period": "monthly", "credits": 100},
        {"period": "lifetime", "credits": 100},
    ],
)
def test_one_period_credit_budget_blocks_when_request_would_exceed_limit(limit):
    service = ApiKeyAuthorizationService()
    metadata = service.normalize_metadata({"credit_limit": limit})

    service.require_budget(metadata, already_spent=90, requested_credits=10)
    with pytest.raises(ApiKeyBudgetError) as exc:
        service.require_budget(metadata, already_spent=95, requested_credits=10)

    assert exc.value.period == limit["period"]
    assert exc.value.remaining_credits == 5


def test_multiple_credit_periods_are_rejected():
    service = ApiKeyAuthorizationService()

    with pytest.raises(ValueError, match="exactly one credit limit period"):
        service.normalize_metadata(
            {
                "credit_limit": {
                    "daily": 100,
                    "monthly": 500,
                }
            }
        )
