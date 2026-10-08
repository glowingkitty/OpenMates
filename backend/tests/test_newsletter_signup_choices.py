"""Public newsletter signup choices and double opt-in regression tests.

The production route bodies are loaded without unrelated API bootstrap.
All addresses, tokens, Directus records, cache data, and Celery tasks are fake.
No email is queued and no external subscriber state is touched.
"""

import ast
import logging
import secrets
from datetime import datetime, timezone
from pathlib import Path
from types import SimpleNamespace
from typing import Dict, Optional
from unittest.mock import AsyncMock, Mock

import pytest
from pydantic import BaseModel, EmailStr, StrictBool, ValidationError, field_validator

from backend.core.api.app.utils.newsletter_utils import (
    NEWSLETTER_CATEGORIES,
    apply_newsletter_category_update,
    hash_email,
    normalize_newsletter_categories,
)


SOURCE = Path(__file__).resolve().parents[1] / "core/api/app/routes/newsletter.py"


def load_route_logic(namespace: dict) -> tuple[type, object, object]:
    tree = ast.parse(SOURCE.read_text())
    names = {"NewsletterSubscribeRequest", "newsletter_subscribe", "newsletter_confirm"}
    nodes = [node for node in tree.body if isinstance(node, (ast.ClassDef, ast.AsyncFunctionDef)) and node.name in names]
    assert {node.name for node in nodes} == names
    for node in nodes:
        if isinstance(node, ast.ClassDef):
            # This local runner lacks email-validator; category validation is
            # under test, while production retains its EmailStr annotation.
            for field in node.body:
                if isinstance(field, ast.AnnAssign) and isinstance(field.target, ast.Name) and field.target.id == "email":
                    field.annotation = ast.Name(id="str", ctx=ast.Load())
        if isinstance(node, ast.AsyncFunctionDef):
            node.decorator_list = []
            node.returns = None
            for argument in node.args.args:
                argument.annotation = None
            node.args.defaults = [ast.Constant(None) for _ in node.args.defaults]
    exec(compile(ast.fix_missing_locations(ast.Module(body=nodes, type_ignores=[])), str(SOURCE), "exec"), namespace)
    return namespace["NewsletterSubscribeRequest"], namespace["newsletter_subscribe"], namespace["newsletter_confirm"]


# contract-test: direct surface=rest_api assertions=newsletter.lifecycle.double-opt-in,newsletter.privacy.identity-and-token-boundary,newsletter.categories.default-and-migration
@pytest.mark.asyncio
async def test_selected_choices_are_pending_until_confirmation() -> None:
    pending: dict[str, dict] = {}
    created: list[dict] = []
    updated: list[dict] = []
    sent = Mock(return_value=SimpleNamespace(id="fake-task"))
    existing = {"value": False}

    async def api_request(method, _url, **kwargs):
        if method == "PATCH":
            updated.append(kwargs["json"])
        row = {"id": "already", "categories": {"openmates_events": False, "software_updates": True, "apple_beta_updates": False}}
        return SimpleNamespace(status_code=200, json=lambda: {"data": [row] if existing["value"] else []})

    async def cache_set(key, value, ttl):
        assert ttl == 1800
        pending[key] = value

    async def cache_get(key):
        return pending.get(key)

    async def cache_delete(key):
        pending.pop(key, None)

    async def create_item(_collection, payload):
        created.append(payload)
        return True, payload

    namespace = {
        "BaseModel": BaseModel, "EmailStr": EmailStr, "StrictBool": StrictBool,
        "field_validator": field_validator, "Optional": Optional, "Dict": Dict,
        "NEWSLETTER_CATEGORIES": NEWSLETTER_CATEGORIES,
        "normalize_newsletter_categories": normalize_newsletter_categories,
        "apply_newsletter_category_update": apply_newsletter_category_update,
        "hash_email": hash_email,
        "check_ignored_email": AsyncMock(return_value=False),
        "update_newsletter_registration_status": AsyncMock(return_value=True),
        "_get_registration_status_for_hashed_email": AsyncMock(return_value="not_signed_up"),
        "get_total_newsletter_subscribers_count": AsyncMock(return_value=1),
        "logger": logging.getLogger(__name__),
        "secrets": secrets, "datetime": datetime, "timezone": timezone,
        "celery_app": SimpleNamespace(send_task=sent),
        "NewsletterSubscribeResponse": lambda **kwargs: SimpleNamespace(**kwargs),
        "NewsletterConfirmResponse": lambda **kwargs: SimpleNamespace(**kwargs),
    }
    request_type, subscribe, confirm = load_route_logic(namespace)
    directus = SimpleNamespace(_make_api_request=api_request, base_url="https://directus.invalid", create_item=create_item)
    cache = SimpleNamespace(set=cache_set, get=cache_get, delete=cache_delete)
    encryption = SimpleNamespace(encrypt_newsletter_email=AsyncMock(return_value="encrypted-synthetic-email"))

    choices = {"openmates_events": True, "software_updates": False, "apple_beta_updates": True}
    payload = request_type(email="test@example.invalid", categories=choices)
    accepted = await subscribe(None, payload, directus, cache, encryption)
    assert accepted.success is True
    assert created == []
    assert len(pending) == 1
    cache_key = next(iter(pending))
    assert pending[cache_key]["categories"] == choices
    assert pending[cache_key]["categories_patch"] == choices
    assert sent.call_count == 1

    namespace["check_ignored_email"].return_value = True
    ignored = await subscribe(None, payload, directus, cache, encryption)
    namespace["check_ignored_email"].return_value = False
    existing["value"] = True
    already_subscribed = await subscribe(None, payload, directus, cache, encryption)
    existing_key = next(key for key in pending if key != cache_key)
    existing["value"] = False
    assert ignored.message == already_subscribed.message == accepted.message
    assert sent.call_count == 2
    assert created == []

    confirmed = await confirm(None, cache_key.removeprefix("newsletter_subscribe:"), directus, cache, encryption)
    assert confirmed.success is True
    assert created[0]["categories"] == choices
    assert created[0]["encrypted_email_address"] == "encrypted-synthetic-email"
    assert "email" not in created[0]
    assert list(pending) == [existing_key]

    existing["value"] = True
    reconfirmed = await confirm(None, existing_key.removeprefix("newsletter_subscribe:"), directus, cache, encryption)
    existing["value"] = False
    assert reconfirmed.success is True
    assert updated[0]["categories"] == choices
    assert pending == {}

    await subscribe(None, payload, directus, cache, encryption)
    ignored_key = next(iter(pending))
    namespace["check_ignored_email"].return_value = True
    rejected = await confirm(None, ignored_key.removeprefix("newsletter_subscribe:"), directus, cache, encryption)
    assert rejected.success is False
    assert len(created) == 1
    assert pending == {}


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "submitted,changed,legacy,expected",
    [
        (None, {"openmates_events": False, "software_updates": False, "apple_beta_updates": False}, None,
         {"openmates_events": False, "software_updates": False, "apple_beta_updates": False}),
        ({"apple_beta_updates": True}, {"openmates_events": False, "software_updates": False, "apple_beta_updates": False}, None,
         {"openmates_events": False, "software_updates": False, "apple_beta_updates": True}),
        ({"software_updates": False}, {"openmates_events": False, "software_updates": True, "apple_beta_updates": False}, None,
         {"openmates_events": False, "software_updates": False, "apple_beta_updates": False}),
        ({"apple_beta_updates": True}, {"openmates_events": False, "software_updates": False, "apple_beta_updates": False}, "raw",
         {"openmates_events": False, "software_updates": False, "apple_beta_updates": True}),
        (None, {"openmates_events": False, "software_updates": False, "apple_beta_updates": True}, "missing",
         {"openmates_events": False, "software_updates": False, "apple_beta_updates": True}),
    ],
)
# contract-test: direct surface=rest_api assertions=newsletter.lifecycle.double-opt-in,newsletter.categories.default-and-migration,newsletter.privacy.identity-and-token-boundary
async def test_existing_subscriber_changes_only_confirmed_supplied_choices(
    submitted: dict | None, changed: dict, legacy: str | None, expected: dict,
) -> None:
    pending: dict[str, dict] = {}
    patches: list[dict] = []
    row = {
        "id": "confirmed-row",
        "unsubscribe_token": "existing-unsubscribe-token",
        "categories": {"openmates_events": True, "software_updates": True, "apple_beta_updates": False},
    }
    sent = Mock(return_value=SimpleNamespace(id="fake-task"))

    async def api_request(method, _url, **kwargs):
        if method == "PATCH":
            patches.append(kwargs["json"])
        return SimpleNamespace(status_code=200, json=lambda: {"data": [row]})

    async def cache_set(key, value, ttl):
        assert ttl == 1800
        pending[key] = value

    namespace = {
        "BaseModel": BaseModel, "EmailStr": EmailStr, "StrictBool": StrictBool,
        "field_validator": field_validator, "Optional": Optional, "Dict": Dict,
        "NEWSLETTER_CATEGORIES": NEWSLETTER_CATEGORIES,
        "normalize_newsletter_categories": normalize_newsletter_categories,
        "apply_newsletter_category_update": apply_newsletter_category_update,
        "hash_email": hash_email,
        "check_ignored_email": AsyncMock(return_value=False),
        "update_newsletter_registration_status": AsyncMock(return_value=True),
        "_get_registration_status_for_hashed_email": AsyncMock(return_value="not_signed_up"),
        "get_total_newsletter_subscribers_count": AsyncMock(return_value=1),
        "logger": logging.getLogger(__name__),
        "secrets": secrets, "datetime": datetime, "timezone": timezone,
        "celery_app": SimpleNamespace(send_task=sent),
        "NewsletterSubscribeResponse": lambda **kwargs: SimpleNamespace(**kwargs),
        "NewsletterConfirmResponse": lambda **kwargs: SimpleNamespace(**kwargs),
    }
    request_type, subscribe, confirm = load_route_logic(namespace)
    directus = SimpleNamespace(_make_api_request=api_request, base_url="https://directus.invalid")
    cache = SimpleNamespace(
        set=cache_set,
        get=AsyncMock(side_effect=lambda key: pending.get(key)),
        delete=AsyncMock(side_effect=lambda key: pending.pop(key, None)),
    )
    encryption = SimpleNamespace(encrypt_newsletter_email=AsyncMock(return_value="encrypted-synthetic-email"))

    response = await subscribe(None, request_type(email="existing@example.invalid", categories=submitted), directus, cache, encryption)
    assert response.success is True
    assert sent.call_count == 1
    assert patches == []
    assert row["categories"] == {"openmates_events": True, "software_updates": True, "apple_beta_updates": False}
    key = next(iter(pending))
    assert pending[key]["categories_patch"] == (submitted or {})
    if legacy == "raw":
        pending[key].pop("categories_patch")
        pending[key]["categories"] = submitted
    elif legacy == "missing":
        pending[key].pop("categories_patch")
        pending[key].pop("categories")

    # Another settings change can land while the email token is pending.
    row["categories"] = changed
    failed = await confirm(None, "expired-token", directus, cache, encryption)
    assert failed.success is False
    assert patches == []
    assert row["categories"] == changed

    confirmed = await confirm(None, key.removeprefix("newsletter_subscribe:"), directus, cache, encryption)
    assert confirmed.success is True
    assert len(patches) == 1
    assert patches[0]["categories"] == expected
    assert patches[0]["unsubscribe_token"] == "existing-unsubscribe-token"
    assert pending == {}


# contract-test: direct surface=rest_api assertions=newsletter.categories.default-and-migration
def test_public_choice_model_rejects_unknown_or_coerced_categories() -> None:
    namespace = {"BaseModel": BaseModel, "EmailStr": EmailStr, "StrictBool": StrictBool,
                 "field_validator": field_validator, "Optional": Optional, "Dict": Dict,
                 "NEWSLETTER_CATEGORIES": NEWSLETTER_CATEGORIES}
    request_type, _, _ = load_route_logic(namespace)
    with pytest.raises(ValidationError):
        request_type(email="test@example.invalid", categories={"unknown": True})
    with pytest.raises(ValidationError):
        request_type(email="test@example.invalid", categories={"apple_beta_updates": "true"})
