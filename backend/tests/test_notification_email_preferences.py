"""Notification email preferences preserve legacy opt-outs and verified routing."""

from unittest.mock import AsyncMock
from types import SimpleNamespace
from types import MethodType

import pytest

from backend.core.api.app.services.notification_email_preferences import (
    DEFAULT_NOTIFICATION_PREFERENCES,
    load_notification_user,
    notification_category_enabled,
    preview_enabled,
    resolve_notification_email,
)
from backend.core.api.app.services.directus.user.user_creation import create_user
from backend.core.api.app.services.directus.user.user_lookup import get_user_fields_direct
from backend.core.api.app.routes.auth_routes.auth_utils import store_account_lifecycle_contact_email


# contract-test: supporting surface=rest_api assertions=notifications.delivery.email-enabled
def test_new_account_categories_are_independent_and_previews_require_opt_in() -> None:
    user = {"email_notifications_enabled": True,
            "email_notification_preferences": dict(DEFAULT_NOTIFICATION_PREFERENCES)}
    assert notification_category_enabled(user, "aiResponses")
    assert notification_category_enabled(user, "workflowRuns")
    assert not preview_enabled(user)
    user["email_notification_preferences"]["aiResponses"] = False
    assert not notification_category_enabled(user, "aiResponses")
    assert notification_category_enabled(user, "workflowRuns")
    user["email_notification_preferences"]["includeContent"] = True
    user["email_notification_preference_choices"] = {
        "includeContent": {"value": True, "source": "user", "updated_at": "2026-10-01T00:00:00Z"}
    }
    assert preview_enabled(user)
    user["email_notifications_enabled"] = False
    assert not notification_category_enabled(user, "workflowRuns")
    assert not preview_enabled(user)


# contract-test: supporting surface=rest_api assertions=notifications.delivery.email-enabled,notifications.content.privacy-boundary
def test_legacy_disabled_account_stays_disabled_and_new_category_is_not_inferred() -> None:
    legacy = {"email_notifications_enabled": False,
              "email_notification_preferences": {"aiResponses": True}}
    assert not notification_category_enabled(legacy, "aiResponses")
    assert not notification_category_enabled(legacy, "workflowRuns")
    legacy["email_notifications_enabled"] = True
    assert notification_category_enabled(legacy, "aiResponses")
    assert not notification_category_enabled(legacy, "workflowRuns")


# contract-test: supporting surface=rest_api assertions=notifications.delivery.email-enabled,notifications.content.privacy-boundary
def test_content_flag_without_explicit_user_choice_cannot_enable_preview() -> None:
    user = {"email_notifications_enabled": True,
            "email_notification_preferences": {"includeContent": True}}
    assert not preview_enabled(user)
    user["email_notification_preference_choices"] = {
        "includeContent": {"value": True, "source": "migration", "updated_at": "2026-10-01T00:00:00Z"}
    }
    assert not preview_enabled(user)


# contract-test: supporting surface=rest_api assertions=notifications.delivery.email-enabled,notifications.content.privacy-boundary
def test_recorded_user_opt_out_overrides_legacy_true_value() -> None:
    user = {
        "email_notifications_enabled": True,
        "email_notification_preferences": {"aiResponses": True, "workflowRuns": True},
        "email_notification_preference_choices": {
            "aiResponses": {"value": False, "source": "user", "updated_at": "2026-10-01T00:00:00Z"},
        },
    }
    assert not notification_category_enabled(user, "aiResponses")
    assert notification_category_enabled(user, "workflowRuns")
    user["email_notification_preference_choices"]["enabled"] = {
        "value": False, "source": "user", "updated_at": "2026-10-01T00:00:00Z"
    }
    assert not notification_category_enabled(user, "workflowRuns")


@pytest.mark.asyncio
# contract-test: supporting surface=rest_api assertions=notifications.delivery.email-enabled,notifications.content.privacy-boundary
async def test_signup_writes_explicit_safe_notification_defaults() -> None:
    directus = SimpleNamespace()
    directus.base_url = "https://directus.example.test"
    directus.encryption_service = AsyncMock()
    directus.encryption_service.create_user_key.return_value = "vault-key"
    directus.encryption_service.hash_email.return_value = "hashed-directus-email"
    directus.encryption_service.encrypt_with_user_key.return_value = ("ciphertext", "v1")
    directus.get_items = AsyncMock(return_value=[])
    response = SimpleNamespace(status_code=200, json=lambda: {"data": {"id": "user-1"}})
    directus._make_api_request = AsyncMock(return_value=response)
    success, _, _ = await create_user(
        directus, username="example-user", encrypted_email="signup-ciphertext",
        hashed_email="hash-1", login_method="password_v2",
    )
    assert success
    payload = directus._make_api_request.await_args.kwargs["json"]
    assert payload["email_notifications_enabled"] is True
    assert payload["email_notification_preferences"] == DEFAULT_NOTIFICATION_PREFERENCES
    assert payload["email_notification_preference_choices"] == {}
    assert "encrypted_notification_email" not in payload


@pytest.mark.asyncio
# contract-test: supporting surface=rest_api assertions=notifications.delivery.email-enabled,notifications.content.privacy-boundary
async def test_notification_user_bypasses_cache_and_requires_matching_id() -> None:
    directus = AsyncMock()
    directus.get_user_fields_direct.return_value = {"id": "user-1", "email_notifications_enabled": True}
    assert await load_notification_user(directus, "user-1") == {
        "id": "user-1", "email_notifications_enabled": True,
    }
    directus.get_user_fields_direct.assert_awaited_once()
    directus.get_user_fields_direct.return_value = {"id": "another-user"}
    assert await load_notification_user(directus, "user-1") is None


@pytest.mark.asyncio
# contract-test: supporting surface=rest_api assertions=notifications.delivery.email-enabled,notifications.settings.ack-persisted
async def test_notification_lookup_observes_opt_out_despite_cached_cms_response() -> None:
    cached = {"id": "user-1", "email_notifications_enabled": True,
              "email_notification_preferences": {"aiResponses": True}}
    current = {**cached, "email_notification_preferences": {"aiResponses": False}}

    async def request(method, url, **options):
        bypass = options.get("headers", {}).get("Cache-Control") == "no-store" and "&_ts=" in url
        return SimpleNamespace(status_code=200, json=lambda: {"data": current if bypass else cached})

    directus = SimpleNamespace(base_url="http://cms:8055", _make_api_request=request)
    directus.get_user_fields_direct = MethodType(get_user_fields_direct, directus)
    user = await load_notification_user(directus, "user-1")
    assert user is not None
    assert not notification_category_enabled(user, "aiResponses")


@pytest.mark.asyncio
# contract-test: supporting surface=rest_api assertions=notifications.delivery.email-enabled,notifications.content.privacy-boundary
async def test_resolve_requires_verified_matching_contact_record() -> None:
    directus = AsyncMock()
    encryption = AsyncMock()
    user = {"id": "user-1", "hashed_email": "hash-1"}
    contact = [{
        "user_id": "user-1", "hashed_email": "hash-1", "purpose": "account_lifecycle",
        "verified_at": "2026-09-01T00:00:00Z", "encrypted_email_address": "ciphertext",
    }]
    directus.get_items.side_effect = [contact, [], contact, [], contact, []]
    encryption.decrypt_account_contact_email.return_value = "verified@example.test"
    assert await resolve_notification_email(directus, encryption, user) == "verified@example.test"
    contact[0]["verified_at"] = None
    assert await resolve_notification_email(directus, encryption, user) is None
    contact[0]["verified_at"] = "2026-09-01T00:00:00Z"
    contact[0]["hashed_email"] = "other-hash"
    assert await resolve_notification_email(directus, encryption, user) is None


@pytest.mark.asyncio
# contract-test: supporting surface=rest_api assertions=notifications.delivery.email-enabled,notifications.content.privacy-boundary
async def test_global_block_suppresses_verified_notification_address() -> None:
    directus = AsyncMock()
    encryption = AsyncMock()
    directus.get_items.side_effect = [[{
        "user_id": "user-1", "hashed_email": "account-hash", "purpose": "account_lifecycle",
        "verified_at": "2026-09-01T00:00:00Z", "encrypted_email_address": "ciphertext",
    }], [{"id": "blocked"}]]
    encryption.decrypt_account_contact_email.return_value = "User@Example.test"
    assert await resolve_notification_email(
        directus, encryption, {"id": "user-1", "hashed_email": "account-hash"}
    ) is None
    assert directus.get_items.await_args.args[0] == "ignored_emails"


@pytest.mark.asyncio
# contract-test: supporting surface=rest_api assertions=notifications.delivery.email-enabled,notifications.content.privacy-boundary
async def test_verified_signup_contact_provisions_notification_routing_ciphertext() -> None:
    directus = AsyncMock()
    encryption = AsyncMock()
    directus.get_items.return_value = []
    directus.create_item.return_value = (True, {"id": "contact-1"})
    directus.get_user_fields_direct.return_value = {"vault_key_id": "user-vault-key"}
    directus.update_user.return_value = True
    encryption.encrypt_account_contact_email.return_value = "contact-ciphertext"
    encryption.encrypt_with_user_key.return_value = ("user-ciphertext", "v1")

    saved = await store_account_lifecycle_contact_email(
        directus, encryption, user_id="user-1", hashed_email="hash-1",
        email="verified@example.test", verified_at="2026-10-01T00:00:00Z",
    )

    assert saved
    assert directus.create_item.await_args.kwargs["admin_required"] is True
    assert directus.create_item.await_args.args[1]["verified_at"]
    directus.update_user.assert_awaited_once_with(
        "user-1", {"encrypted_notification_email": "user-ciphertext"}
    )


@pytest.mark.asyncio
# contract-test: supporting surface=rest_api assertions=notifications.delivery.email-enabled,notifications.content.privacy-boundary
async def test_contact_without_verification_proof_is_not_provisioned() -> None:
    directus = AsyncMock()
    encryption = AsyncMock()
    assert not await store_account_lifecycle_contact_email(
        directus, encryption, user_id="user-1", hashed_email="hash-1",
        email="unverified@example.test", verified_at=None,
    )
    directus.create_item.assert_not_awaited()
    directus.update_user.assert_not_awaited()
