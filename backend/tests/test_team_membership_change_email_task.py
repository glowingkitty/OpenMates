"""Team membership email task uses the cache's lazy client lifecycle."""

import sys
from types import ModuleType, SimpleNamespace

import pytest

from backend.core.api.app.tasks.email_tasks.team_membership_change_email_task import (
    _send_team_membership_change_email,
)


@pytest.fixture
def anyio_backend():
    return "asyncio"


@pytest.fixture
def email_services(monkeypatch):
    state = SimpleNamespace(sent=[], cache_closed=0, encryption_closed=0, secrets_closed=0)

    class CacheService:
        # CacheService has no initialize(): its client connects on first use.
        async def get_user_by_id(self, user_id):
            assert user_id == "member-id"
            return {
                "vault_key_id": "vault-key",
                "encrypted_notification_email": "cipher-address",
                "language": "en",
            }

        async def close(self):
            state.cache_closed += 1

    class EncryptionService:
        async def initialize(self):
            pass

        async def decrypt_with_user_key(self, ciphertext, key_id):
            assert (ciphertext, key_id) == ("cipher-address", "vault-key")
            return "ci-0123456789abcdef0123456789abcdef@example.com"

        async def close(self):
            state.encryption_closed += 1

    class SecretsManager:
        async def initialize(self):
            pass

        async def aclose(self):
            state.secrets_closed += 1

    class EmailTemplateService:
        def __init__(self, *, secrets_manager):
            assert isinstance(secrets_manager, SecretsManager)
            self.translation_service = SimpleNamespace(
                get_nested_translation=lambda key, lang, context: key
            )

        async def send_email(self, **kwargs):
            state.sent.append(kwargs)
            if getattr(state, "send_error", False):
                raise RuntimeError("delivery failed")
            return True

    class DirectusService:
        def __init__(self):
            raise AssertionError("Complete cached user should not require Directus")

    modules = {
        "backend.core.api.app.services.cache": {"CacheService": CacheService},
        "backend.core.api.app.services.directus": {"DirectusService": DirectusService},
        "backend.core.api.app.services.email_template": {"EmailTemplateService": EmailTemplateService},
        "backend.core.api.app.utils.encryption": {"EncryptionService": EncryptionService},
        "backend.core.api.app.utils.secrets_manager": {"SecretsManager": SecretsManager},
        "backend.shared.python_utils.frontend_url": {
            "get_frontend_base_url": lambda: "https://app.example.com"
        },
    }
    for name, attributes in modules.items():
        module = ModuleType(name)
        for attribute, value in attributes.items():
            setattr(module, attribute, value)
        monkeypatch.setitem(sys.modules, name, module)
    return state


# contract-test: supporting surface=rest_api assertions=teams.membership.role-gated,teams.invites.fragment-key-web-flow
@pytest.mark.anyio
@pytest.mark.parametrize(
    ("change", "template"),
    [
        ("role_changed", "team-role-changed-notification"),
        ("removed", "team-removed-notification"),
    ],
)
async def test_membership_email_sends_without_cache_initialize_and_closes_services(
    email_services, change, template
):
    assert await _send_team_membership_change_email(
        user_id="member-id", team_id="team-id", change=change
    ) is True
    assert len(email_services.sent) == 1
    sent = email_services.sent[0]
    assert sent["template"] == template
    assert sent["recipient_email"] == "ci-0123456789abcdef0123456789abcdef@example.com"
    assert sent["context"] == {"open_url": "https://app.example.com", "team_id": "team-id"}
    assert (email_services.cache_closed, email_services.encryption_closed, email_services.secrets_closed) == (1, 1, 1)


# contract-test: supporting surface=rest_api assertions=teams.membership.role-gated
@pytest.mark.anyio
async def test_membership_email_closes_services_when_delivery_fails(email_services):
    email_services.send_error = True
    with pytest.raises(RuntimeError, match="delivery failed"):
        await _send_team_membership_change_email(
            user_id="member-id", team_id="team-id", change="role_changed"
        )
    assert (email_services.cache_closed, email_services.encryption_closed, email_services.secrets_closed) == (1, 1, 1)
